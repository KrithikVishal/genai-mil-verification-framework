"""
mvp/test_critic.py
------------------
Phase 5 of the MVP loop: Test Critic.

The critic is the AI "judge" — it reads the evidence analysis and the
execution result, then decides:
  (a) Whether the test was adequate (coverage + oracle quality).
  (b) What specific improvements should be made.
  (c) Whether the loop should stop (verdict PASS, no gaps) or continue.

Uses Groq LLM when available; falls back to a deterministic rule-based
critic when offline.

The critic output is a structured JSON dict that feeds back into the
Test Generator's improvement prompt in the next iteration.
"""

from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


_CRITIC_SYSTEM = textwrap.dedent("""\
    You are an automotive test quality critic for an ACC (Adaptive Cruise Control)
    verification system.

    You receive:
    1. The EARS requirement being tested.
    2. The Test Intent that was executed.
    3. The Execution Evidence (measured metrics, verdict, oracle results).
    4. An Evidence Analysis (gaps, boundary proximity, diagnosis).

    Your output must be a SINGLE JSON object with exactly these keys:
    {
      "overall_quality": "GOOD" | "ADEQUATE" | "WEAK" | "INVALID",
      "stop_loop": true | false,
      "stop_reason": "<string if stop_loop=true, else null>",
      "weaknesses": ["<list of specific weaknesses>"],
      "improvement_directives": {
        "stimulus": "<what to change in stimulus/scenario>",
        "oracle": "<what to change in oracle conditions or window>",
        "duration": "<change duration_s to X? or null>",
        "sample_time": "<change sample_time_s? or null>",
        "initial_conditions": "<what to change in v_ego, v_lead, d_init?>"
      },
      "confidence": 0.0..1.0,
      "reasoning": "<2-3 sentence explanation>"
    }

    STOPPING RULES:
    - stop_loop=true ONLY if: verdict is PASS AND no coverage gaps AND oracle is rigorous.
    - stop_loop=true if: iteration >= max_iterations (you will be told this).
    - Otherwise stop_loop=false and provide directives.

    Output ONLY raw JSON. No markdown. No explanations outside the JSON.
""")


_CRITIC_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "allam-2-7b",
]


def _call_llm_critic(prompt: str) -> Optional[str]:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or not GROQ_AVAILABLE:
        return None
    client = Groq(api_key=api_key)
    last_exc = None
    for model in _CRITIC_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _CRITIC_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.05,
                max_tokens=1024,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            last_exc = e
            continue
    return None  # All models failed; caller will use deterministic fallback


def _deterministic_critic(
    intent: dict,
    result: dict,
    analysis: dict,
    iteration: int,
    max_iterations: int,
) -> dict:
    """Rule-based fallback critic (no LLM needed)."""
    verdict = result.get("requirement_verdict", "ERROR")
    gaps    = analysis.get("coverage_gaps", [])
    status  = result.get("execution_status", "unknown")

    weaknesses = list(gaps)
    if verdict == "ERROR":
        weaknesses.append("Simulation returned an error — likely a config issue.")
    if verdict == "FAIL":
        weaknesses.append(f"Oracle conditions not satisfied (verdict={verdict}).")

    # Determine quality
    if verdict == "PASS" and not gaps:
        quality    = "GOOD"
        stop_loop  = True
        stop_reason = "PASS with no gaps."
    elif verdict == "PASS" and gaps:
        quality    = "ADEQUATE"
        stop_loop  = iteration >= max_iterations
        stop_reason = "Max iterations reached." if stop_loop else None
    elif verdict == "FAIL":
        quality    = "WEAK"
        stop_loop  = iteration >= max_iterations
        stop_reason = "Max iterations reached." if stop_loop else None
    else:
        quality    = "INVALID"
        stop_loop  = True
        stop_reason = "Simulation error — cannot improve without fixing config."

    # Build directives
    ic = intent.get("stimulus", {}).get("initial_conditions", {})
    v_set = ic.get("v_set_mps", 20)
    v_ego_init = ic.get("v_ego_init_mps", v_set)
    directives = {
        "stimulus": None,
        "oracle": None,
        "duration": None,
        "sample_time": None,
        "initial_conditions": None,
    }

    metrics = result.get("measured_metrics", {})
    max_spd_err = metrics.get("max_speed_error_mps", None)
    if max_spd_err is not None and max_spd_err < 0.01:
        directives["initial_conditions"] = (
            f"Start v_ego further from v_set. "
            f"Try v_ego_init_mps={max(0, v_set - 10):.1f} "
            f"so the controller has a meaningful error to correct."
        )
    if not gaps and verdict == "FAIL":
        directives["oracle"] = (
            "Review oracle thresholds — they may be too tight for the scenario. "
            "Widen evaluation window or relax tolerances slightly."
        )
    if verdict == "ERROR":
        directives["stimulus"] = "Fix event definitions and initial condition bounds."

    reasoning = (
        f"Verdict={verdict}. "
        f"Iteration {iteration}/{max_iterations}. "
        f"{len(gaps)} coverage gap(s) detected."
    )

    return {
        "overall_quality": quality,
        "stop_loop":  stop_loop,
        "stop_reason": stop_reason,
        "weaknesses": weaknesses,
        "improvement_directives": directives,
        "confidence": 0.8 if quality == "GOOD" else 0.5,
        "reasoning": reasoning,
    }


def critique(
    req_id: str,
    req_text: str,
    intent: dict,
    result: dict,
    analysis: dict,
    iteration: int,
    max_iterations: int,
) -> dict:
    """
    Run the Test Critic on one execution cycle.

    Returns a critic JSON dict with keys:
        overall_quality, stop_loop, stop_reason, weaknesses,
        improvement_directives, confidence, reasoning.
    """
    stop_due_to_max = iteration >= max_iterations
    verdict = result.get("requirement_verdict", "ERROR")

    print(f"  [Critic] Evaluating iteration {iteration}/{max_iterations} "
          f"(verdict={verdict}) …", end=" ")

    # Slim payloads — signal_traces are large float arrays that blow the context window
    slim_result   = {k: v for k, v in result.items() if k != "signal_traces"}
    slim_analysis = {k: v for k, v in analysis.items() if k != "diagnosis"}
    slim_intent   = {k: v for k, v in intent.items()
                     if k in ("test_id", "requirement_id", "stimulus",
                               "oracle", "observed_signals", "duration_s", "iteration")}

    # Try LLM critic first
    user_prompt = (
        f"REQUIREMENT:\nID: {req_id}\nText: {req_text}\n\n"
        f"TEST INTENT (iter {iteration}/{max_iterations}):\n"
        + json.dumps(slim_intent, indent=2)
        + "\n\nEXECUTION EVIDENCE (metrics + oracle, no signal arrays):\n"
        + json.dumps(slim_result, indent=2)
        + "\n\nEVIDENCE ANALYSIS:\n"
        + json.dumps(slim_analysis, indent=2)
        + f"\n\nMax iterations: {max_iterations}  Current: {iteration}  StopIfMax: {stop_due_to_max}\n"
    )

    raw = _call_llm_critic(user_prompt)

    if raw is None:
        print("(offline — using rule-based critic)")
        return _deterministic_critic(intent, result, analysis, iteration, max_iterations)

    # Parse LLM output
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(l for l in lines[1:] if l.strip() != "```")
        crit = json.loads(raw)
    except json.JSONDecodeError:
        print("(LLM JSON error — using rule-based critic)")
        return _deterministic_critic(intent, result, analysis, iteration, max_iterations)

    # Override stop_loop if max_iterations reached
    if stop_due_to_max:
        crit["stop_loop"]   = True
        crit["stop_reason"] = f"Max iterations ({max_iterations}) reached."

    print(f"quality={crit.get('overall_quality', '?')}  stop={crit.get('stop_loop', '?')}")
    return crit
