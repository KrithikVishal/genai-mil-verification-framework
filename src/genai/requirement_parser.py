"""
requirement_parser.py
---------------------
Stage A of the GenAI pipeline:
  EARS requirement text  →  structured Test-Intent JSON

Uses the Groq API (llama-3.3-70b-versatile model) to parse each requirement
and emit a JSON object conforming to config/architecture_contract.json.

A built-in fallback (deterministic) is provided so the pipeline can still run
if no GROQ_API_KEY is set (useful for offline/CI use).

Environment:
  GROQ_API_KEY  — Groq Cloud API key (set in .env or shell)
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Optional imports — degrade gracefully
# ---------------------------------------------------------------------------
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "config" / "architecture_contract.json"

sys.path.insert(0, str(ROOT))
from requirements.acc_requirements import ALL_REQUIREMENTS, EARSRequirement  # noqa: E402

# ---------------------------------------------------------------------------
# Groq client initialisation
# ---------------------------------------------------------------------------
_client: Optional["Groq"] = None


def _get_client() -> Optional["Groq"]:
    global _client
    if _client is not None:
        return _client
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or not GROQ_AVAILABLE:
        return None
    _client = Groq(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# System prompt for the LLM
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert automotive systems verification engineer specialising in
    Model-in-the-Loop (MIL) testing for Advanced Driver Assistance Systems (ADAS).

    Your task is to parse a single EARS-syntax Adaptive Cruise Control (ACC)
    requirement and output ONE valid JSON object that strictly conforms to the
    schema below.  Do not include any markdown fences or explanation — output
    raw JSON only.

    SCHEMA REFERENCE:
    {schema}

    CONTEXT:
    - The ACC controller is a MPC-based longitudinal controller.
    - Signals available: v_ego (m/s), v_lead (m/s), d_actual (m), a_cmd (m/s²),
      d_safe (m), mode (0=speed, 1=spacing).
    - D_safe = 10 + 1.4 × v_ego
    - Acceleration bounds: a_cmd ∈ [-3, 2] m/s²
    - Nominal sample time: Ts = 0.1 s
    - generated_by should be "groq/llama-3.3-70b-versatile"
    - version: "1.0"
""")


def _build_user_prompt(req: EARSRequirement) -> str:
    return textwrap.dedent(f"""\
        Parse the following ACC requirement into a Test-Intent JSON:

        Requirement ID : {req.id}
        Category       : {req.category}
        Trigger        : {req.trigger or 'unconditional'}
        Full text      :
        {req.text}

        Additional numeric context: {json.dumps(req.numeric_params)}

        Output only the JSON object.
    """)


# ---------------------------------------------------------------------------
# LLM-based parser
# ---------------------------------------------------------------------------
def _parse_with_groq(req: EARSRequirement) -> dict:
    """Call Groq API to produce a Test-Intent dict from a single requirement."""
    client = _get_client()
    schema_text = SCHEMA_PATH.read_text(encoding="utf-8")

    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": _SYSTEM_PROMPT.format(schema=schema_text),
            },
            {
                "role": "user",
                "content": _build_user_prompt(req),
            },
        ],
        temperature=0.1,
        max_tokens=1024,
    )

    raw = response.choices[0].message.content.strip()

    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Extract JSON object with regex
    import re
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        return json.loads(match.group(0))

    return json.loads(raw)


# ---------------------------------------------------------------------------
# Deterministic fallback parser
# ---------------------------------------------------------------------------
_FALLBACK_INTENTS: dict[str, dict] = {
    "ACC-REQ-001": {
        "requirement_id": "ACC-REQ-001",
        "requirement_text": (
            "WHEN the lead vehicle is absent or travelling faster than the set speed, "
            "the ACC system shall maintain ego-vehicle speed within ±0.5 m/s of V_set "
            "in steady-state (settled after 5 s)."
        ),
        "category": "speed_tracking",
        "stimulus": {
            "type": "steady_state",
            "duration_s": 20.0,
            "sample_time_s": 0.1,
            "parameters": {
                "v_set_mps": 30.0,
                "v_lead_initial_mps": 35.0,
                "d_initial_m": 50.0,
            },
        },
        "oracle": {
            "type": "tolerance_band",
            "signal": "v_ego",
            "evaluation_window_s": [5.0, 20.0],
            "tolerance_mps": 0.5,
        },
        "metadata": {"generated_by": "fallback/deterministic", "version": "1.0"},
    },
    "ACC-REQ-002": {
        "requirement_id": "ACC-REQ-002",
        "requirement_text": (
            "WHEN a lead vehicle is present and D_actual < D_safe, the ACC system shall "
            "reduce ego-vehicle speed so that D_actual >= D_safe within 3 s."
        ),
        "category": "safe_distance",
        "stimulus": {
            "type": "lead_deceleration",
            "duration_s": 15.0,
            "sample_time_s": 0.1,
            "parameters": {
                "v_set_mps": 30.0,
                "v_lead_initial_mps": 30.0,
                "v_lead_final_mps": 15.0,
                "d_initial_m": 45.0,
                "lead_decel_mps2": -3.0,
                "event_time_s": 2.0,
            },
        },
        "oracle": {
            "type": "lower_bound",
            "signal": "d_actual",
            "evaluation_window_s": [5.0, 15.0],
            "reference_signal": "d_safe",
        },
        "metadata": {"generated_by": "fallback/deterministic", "version": "1.0"},
    },
    "ACC-REQ-003": {
        "requirement_id": "ACC-REQ-003",
        "requirement_text": (
            "The safe following distance shall be computed as "
            "D_safe = D_default + T_gap × V_ego  (D_default=10 m, T_gap=1.4 s)."
        ),
        "category": "distance_formula",
        "stimulus": {
            "type": "steady_state",
            "duration_s": 10.0,
            "sample_time_s": 0.1,
            "parameters": {
                "v_set_mps": 25.0,
                "v_lead_initial_mps": 30.0,
                "d_initial_m": 60.0,
            },
        },
        "oracle": {
            "type": "exact_bound",
            "signal": "d_safe",
            "evaluation_window_s": [0.0, 10.0],
            "reference_signal": "d_safe",
        },
        "metadata": {"generated_by": "fallback/deterministic", "version": "1.0"},
    },
    "ACC-REQ-004": {
        "requirement_id": "ACC-REQ-004",
        "requirement_text": (
            "Ego acceleration shall be constrained to [-3, 2] m/s² at all times, "
            "regardless of controller mode or implementation."
        ),
        "category": "acceleration_bounds",
        "stimulus": {
            "type": "lead_deceleration",
            "duration_s": 20.0,
            "sample_time_s": 0.1,
            "parameters": {
                "v_set_mps": 30.0,
                "v_lead_initial_mps": 30.0,
                "v_lead_final_mps": 0.0,
                "d_initial_m": 40.0,
                "lead_decel_mps2": -5.0,
                "event_time_s": 3.0,
            },
        },
        "oracle": {
            "type": "exact_bound",
            "signal": "a_cmd",
            "evaluation_window_s": [0.0, 20.0],
            "min_value": -3.0,
            "max_value": 2.0,
        },
        "metadata": {"generated_by": "fallback/deterministic", "version": "1.0"},
    },
    "ACC-REQ-005": {
        "requirement_id": "ACC-REQ-005",
        "requirement_text": (
            "WHEN a lead-vehicle deceleration event would breach D_safe, the system "
            "shall switch to spacing-control mode within one sample period (Ts = 0.1 s)."
        ),
        "category": "mode_switch",
        "stimulus": {
            "type": "lead_deceleration",
            "duration_s": 10.0,
            "sample_time_s": 0.1,
            "parameters": {
                "v_set_mps": 30.0,
                "v_lead_initial_mps": 30.0,
                "v_lead_final_mps": 10.0,
                "d_initial_m": 42.0,
                "lead_decel_mps2": -4.0,
                "event_time_s": 1.0,
            },
        },
        "oracle": {
            "type": "timing_constraint",
            "signal": "mode",
            "evaluation_window_s": [1.0, 5.0],
            "timing_tolerance_s": 0.1,
        },
        "metadata": {"generated_by": "fallback/deterministic", "version": "1.0"},
    },
}


def _parse_fallback(req: EARSRequirement) -> dict:
    intent = _FALLBACK_INTENTS.get(req.id)
    if intent is None:
        raise ValueError(f"No fallback intent for requirement {req.id}")
    return intent


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_requirement(req: EARSRequirement, use_llm: bool = True) -> dict:
    """
    Parse one EARS requirement into a Test-Intent dict.

    Parameters
    ----------
    req      : EARSRequirement instance
    use_llm  : If True and GROQ_API_KEY is set, use Groq LLM.
               Otherwise falls back to deterministic mapping.

    Returns
    -------
    dict conforming to architecture_contract.json
    """
    client = _get_client()
    if use_llm and client is not None:
        print(f"  [Groq] Parsing {req.id} …", end=" ", flush=True)
        try:
            result = _parse_with_groq(req)
            print("OK")
            return result
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED ({exc}) — using fallback")
            return _parse_fallback(req)
    else:
        mode = "fallback (no GROQ_API_KEY)" if not client else "fallback (use_llm=False)"
        print(f"  [{mode}] Parsing {req.id}")
        return _parse_fallback(req)


def parse_all_requirements(use_llm: bool = True) -> list[dict]:
    """Parse all five ACC requirements and return a list of Test-Intent dicts."""
    print("\n=== Stage A: Requirement Parsing ===")
    results = []
    for req in ALL_REQUIREMENTS:
        intent = parse_requirement(req, use_llm=use_llm)
        results.append(intent)
    print(f"  Parsed {len(results)} requirements.\n")
    return results


def save_intents(intents: list[dict], output_dir: Path) -> None:
    """Write each Test-Intent to a JSON file in output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for intent in intents:
        req_id = intent["requirement_id"]
        path = output_dir / f"{req_id}_intent.json"
        path.write_text(json.dumps(intent, indent=2), encoding="utf-8")
        print(f"  Saved: {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# CLI quick-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Parse ACC EARS requirements via Groq")
    ap.add_argument("--no-llm", action="store_true", help="Skip LLM, use fallback")
    ap.add_argument("--out", default="tests/mil", help="Output directory for intent JSONs")
    args = ap.parse_args()

    intents = parse_all_requirements(use_llm=not args.no_llm)
    out_dir = ROOT / args.out / "intents"
    save_intents(intents, out_dir)
    print(f"\nAll intents saved to {out_dir}")
