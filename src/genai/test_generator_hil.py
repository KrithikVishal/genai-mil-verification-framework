"""
test_generator_hil.py
---------------------
Stage B (HIL branch) of the GenAI pipeline:
  Test-Intent JSON  →  HIL stub descriptor (YAML)

Uses Groq (llama-3.3-70b-versatile) to generate a YAML stub that describes
how each MIL test would map onto a real-time Hardware-in-the-Loop target
(e.g., dSPACE MicroLabBox or similar).

The YAML stubs are written to tests/hil/ for future toolchain integration.
They are NOT executed in PoC-1 (HIL is out of scope) but are generated to
demonstrate the full pipeline architecture.

Environment:
  GROQ_API_KEY — Groq Cloud API key
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Optional

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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

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
_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an automotive HIL (Hardware-in-the-Loop) test engineer.
    Given a MIL Test-Intent JSON, produce a YAML HIL stub descriptor that maps
    the test to a real-time target environment.

    The YAML stub must include:
      requirement_id:     string
      hil_target:         string (e.g. "dSPACE MicroLabBox")
      sample_time_s:      float
      io_mapping:
        inputs:           list of {signal, channel, unit, range}
        outputs:          list of {signal, channel, unit}
      scenario:
        type:             string
        duration_s:       float
        events:           list of {time_s, description, value}
      pass_criteria:
        signal:           string
        condition:        string (human-readable)
      notes:              string

    Output ONLY the YAML.  No markdown fences, no explanation.
""")


def _generate_hil_stub_groq(intent: dict) -> str:
    client = _get_client()
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": f"Generate HIL stub for:\n{json.dumps(intent, indent=2)}"},
        ],
        temperature=0.2,
        max_tokens=1024,
    )
    raw = response.choices[0].message.content.strip()
    if raw.startswith("```"):
        raw = "\n".join(raw.split("\n")[1:])
        if raw.endswith("```"):
            raw = raw[:-3]
    return raw.strip()


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------
def _generate_hil_stub_fallback(intent: dict) -> str:
    req_id   = intent["requirement_id"]
    stimulus = intent.get("stimulus", {})
    oracle   = intent.get("oracle", {})

    lines = [
        f"requirement_id: {req_id}",
        f"hil_target: dSPACE MicroLabBox (simulated stub — PoC-1 HIL out of scope)",
        f"sample_time_s: {stimulus.get('sample_time_s', 0.1)}",
        "io_mapping:",
        "  inputs:",
        "    - signal: v_lead",
        "      channel: AI_0",
        "      unit: m/s",
        "      range: [0, 50]",
        "    - signal: v_set",
        "      channel: AI_1",
        "      unit: m/s",
        "      range: [0, 50]",
        "  outputs:",
        "    - signal: v_ego",
        "      channel: AO_0",
        "      unit: m/s",
        "    - signal: a_cmd",
        "      channel: AO_1",
        "      unit: m/s2",
        "    - signal: d_actual",
        "      channel: AO_2",
        "      unit: m",
        f"scenario:",
        f"  type: {stimulus.get('type', 'steady_state')}",
        f"  duration_s: {stimulus.get('duration_s', 10.0)}",
        "  events: []",
        f"pass_criteria:",
        f"  signal: {oracle.get('signal', 'v_ego')}",
        f"  condition: see MIL oracle for {req_id}",
        f"notes: >",
        f"  Auto-generated HIL stub for {req_id}.",
        f"  Real-time execution requires dSPACE TargetLink code generation",
        f"  and XCP-based signal injection.  This stub is out of scope for PoC-1.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_hil_stub(intent: dict, use_llm: bool = True) -> str:
    req_id = intent["requirement_id"]
    client = _get_client()
    if use_llm and client is not None:
        print(f"  [Groq] Generating HIL stub for {req_id} …", end=" ", flush=True)
        try:
            stub = _generate_hil_stub_groq(intent)
            print("OK")
            return stub
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED ({exc}) — using fallback")
            return _generate_hil_stub_fallback(intent)
    else:
        mode_str = "fallback (no GROQ_API_KEY)" if not client else "fallback (use_llm=False)"
        print(f"  [{mode_str}] Generating HIL stub for {req_id}")
        return _generate_hil_stub_fallback(intent)


def generate_all_hil_stubs(intents: list[dict], use_llm: bool = True) -> dict[str, str]:
    print("\n=== Stage B (HIL): HIL Stub Generation ===")
    stubs = {}
    for intent in intents:
        stubs[intent["requirement_id"]] = generate_hil_stub(intent, use_llm=use_llm)
    print(f"  Generated {len(stubs)} HIL stubs.\n")
    return stubs


def save_hil_stubs(stubs: dict[str, str], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for req_id, stub in stubs.items():
        fname = f"{req_id.lower().replace('-','_')}_hil_stub.yaml"
        path  = output_dir / fname
        header = (
            f"# HIL stub for {req_id}\n"
            f"# Auto-generated by src/genai/test_generator_hil.py\n"
            f"# NOTE: PoC-1 executes MIL only; this stub is for architecture demonstration.\n\n"
        )
        path.write_text(header + stub, encoding="utf-8")
        print(f"  Saved: {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    from src.genai.requirement_parser import parse_all_requirements

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    intents = parse_all_requirements(use_llm=not args.no_llm)
    stubs   = generate_all_hil_stubs(intents, use_llm=not args.no_llm)
    save_hil_stubs(stubs, ROOT / "tests" / "hil")
