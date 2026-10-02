"""
mvp/test_generator.py
---------------------
Phase 1+2 of the MVP loop: EARS Requirement → Validated Test Intent JSON.

Calls the Groq LLM to generate a test intent, validates it against the
JSON schema, and returns either a valid dict or raises ValidationError.

Python handles ALL AI interaction. MATLAB handles ALL simulation.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Optional

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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

SCHEMA_PATH = ROOT / "mvp" / "schemas" / "test_intent_schema.json"
_schema_cache: Optional[dict] = None


def _schema() -> dict:
    global _schema_cache
    if _schema_cache is None:
        with open(SCHEMA_PATH) as f:
            _schema_cache = json.load(f)
    return _schema_cache


_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert automotive verification engineer for ADAS/ACC systems.
    Your job: convert ONE EARS requirement into a structured Test Intent JSON.

    CRITICAL RULES:
    1. Output ONLY raw JSON — no markdown fences, no explanation, no comments.
    2. The JSON MUST conform exactly to the schema below.
    3. All numeric values must be realistic for a physical ACC system.
    4. 'iteration' should be set to the value provided in the user message.
    5. 'generated_by' must be "groq/llama-3.3-70b-versatile".

    SCHEMA:
    {schema}

    PHYSICAL CONSTRAINTS:
    - Vehicle: passenger car, mass ~1500 kg
    - Signals: v_ego (m/s), v_lead (m/s), d_actual (m), a_cmd (m/s²), d_safe (m), mode (0/1)
    - COMPUTED oracle signals (use these for cleaner conditions):
        speed_error = |v_ego - v_set|    (m/s)  — use this for speed tolerance checks
        gap_surplus = d_actual - d_safe  (m)    — use this for safe-distance checks
    - D_safe = 10 + 1.4 × v_ego
    - a_cmd ∈ [-3.0, 2.0] m/s²
    - Nominal Ts = 0.1 s, duration ∈ [5, 30] s
    - Evaluation window must be within [0, duration_s]

    ORACLE SIGNAL RULES — oracle conditions MUST use ONLY these signal names:
      v_ego, v_lead, d_actual, a_cmd, d_safe, mode, speed_error, gap_surplus
    Any other signal name is INVALID and will cause a runtime error.

    PREFERRED ORACLE PATTERNS:
    - Speed tracking: {{ "signal": "speed_error", "operator": "<=", "threshold": 0.5 }}
    - Safe distance: {{ "signal": "gap_surplus", "operator": ">=", "threshold": 0.0 }}
    - Accel bounds:  {{ "signal": "a_cmd", "operator": ">=", "threshold": -3.0 }}
                     {{ "signal": "a_cmd", "operator": "<=", "threshold": 2.0 }}
    - Mode check:    {{ "signal": "mode", "operator": "==", "threshold": 1.0 }}
""")

_USER_TEMPLATE = textwrap.dedent("""\
    Requirement ID  : {req_id}
    Requirement text: {req_text}
    Numeric params  : {numeric}
    Iteration       : {iteration}

    Generate test_id as: {req_id}-T1-I{iteration}

    Output ONLY the JSON object.
""")

_IMPROVEMENT_PROMPT = textwrap.dedent("""\
    The previous test iteration FAILED or was UNCERTAIN.
    Below is the previous test intent and the execution evidence.

    PREVIOUS TEST INTENT:
    {prev_intent}

    EXECUTION EVIDENCE:
    {evidence}

    CRITIC ANALYSIS:
    {critic}

    YOUR TASK:
    Generate an IMPROVED test intent for the SAME requirement.
    Fix the weaknesses identified by the critic.
    Increment the 'iteration' field by 1.
    Use the SAME schema as before.
    Output ONLY the JSON object.
""")


def _get_client() -> Optional["Groq"]:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or not GROQ_AVAILABLE:
        return None
    return Groq(api_key=api_key)


def _validate(intent: dict) -> dict:
    """Validate intent against JSON schema. Raises jsonschema.ValidationError on failure."""
    jsonschema.validate(instance=intent, schema=_schema())
    return intent


_MODELS = [
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "allam-2-7b",
]


def _call_llm(system_prompt: str, user_prompt: str, model: str = None) -> str:
    client = _get_client()
    if client is None:
        raise RuntimeError("Groq client not available — check GROQ_API_KEY.")
    models_to_try = ([model] + _MODELS) if model else _MODELS
    last_exc = None
    for m in models_to_try:
        try:
            resp = client.chat.completions.create(
                model=m,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=2048,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            last_exc = e
            continue
    raise RuntimeError(f"All Groq models failed. Last error: {last_exc}") from last_exc


def _strip_fences(text: str) -> str:
    """Remove markdown code fences if LLM adds them despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence line
        inner = [l for l in lines[1:] if l.strip() != "```"]
        text = "\n".join(inner)
    return text.strip()


def _slim_evidence(evidence: dict) -> dict:
    """
    Remove large array fields from execution evidence before sending to LLM.
    signal_traces can be 1000s of floats — this blows the context window.
    We keep only the scalar summary metrics.
    """
    slim = {k: v for k, v in evidence.items() if k != "signal_traces"}
    # Also trim oracle_conditions to just pass/fail/measured (no full arrays)
    if "oracle_conditions" in slim:
        slim["oracle_conditions"] = [
            {"signal": c.get("signal"), "operator": c.get("operator"),
             "threshold": c.get("threshold"), "measured": c.get("measured"),
             "passed": c.get("passed")}
            for c in slim["oracle_conditions"]
            if isinstance(c, dict)
        ]
    return slim


def _slim_intent(intent: dict) -> dict:
    """Keep only the fields the LLM needs to improve from."""
    keep = {"test_id", "requirement_id", "test_objective", "stimulus",
            "observed_signals", "oracle", "duration_s", "sample_time_s", "iteration"}
    return {k: v for k, v in intent.items() if k in keep}

def generate_test_intent(
    req_id: str,
    req_text: str,
    numeric_params: dict,
    iteration: int = 1,
    prev_intent: Optional[dict] = None,
    evidence: Optional[dict] = None,
    critic: Optional[dict] = None,
) -> dict:
    """
    Generate (or improve) a validated Test Intent for one EARS requirement.

    Parameters
    ----------
    req_id        : requirement identifier, e.g. "ACC-REQ-001"
    req_text      : full requirement text
    numeric_params: dict of numeric constants from the requirement
    iteration     : current loop iteration (>1 means improvement mode)
    prev_intent   : previous Test Intent dict (improvement mode only)
    evidence      : Execution Result dict (improvement mode only)
    critic        : Critic Analysis dict (improvement mode only)

    Returns
    -------
    Validated Test Intent dict conforming to test_intent_schema.json
    """
    schema_str = json.dumps(_schema(), indent=2)
    system = _SYSTEM_PROMPT.format(schema=schema_str)

    if iteration > 1 and prev_intent and evidence and critic:
        user = _IMPROVEMENT_PROMPT.format(
            prev_intent=json.dumps(_slim_intent(prev_intent), indent=2),
            evidence=json.dumps(_slim_evidence(evidence), indent=2),
            critic=json.dumps(critic, indent=2),
        )
    else:
        user = _USER_TEMPLATE.format(
            req_id=req_id,
            req_text=req_text,
            numeric=json.dumps(numeric_params),
            iteration=iteration,
        )

    print(f"  [LLM] Generating test intent for {req_id} (iteration={iteration})…", end=" ")
    raw = _call_llm(system, user)
    raw = _strip_fences(raw)

    try:
        intent = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}\n--- RAW ---\n{raw}") from e

    # Force correct values regardless of what LLM set
    intent["requirement_id"] = req_id
    intent["iteration"] = iteration
    intent["generated_by"] = "groq/llama-3.3-70b-versatile"
    if "test_id" not in intent:
        intent["test_id"] = f"{req_id}-T1-I{iteration}"

    _validate(intent)
    print("OK")
    return intent
