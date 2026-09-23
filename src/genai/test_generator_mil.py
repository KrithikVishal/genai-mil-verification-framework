"""
test_generator_mil.py
---------------------
Stage B of the GenAI pipeline:
  Test-Intent JSON  →  executable Python MIL test functions

Uses the Groq API (llama-3.3-70b-versatile) to write a Python test function
for each Test-Intent.  The generated function:
  - builds a scenario stimulus time-series
  - runs the ACC closed-loop simulation
  - evaluates the oracle and returns PASS / FAIL + signal traces

A deterministic fallback generates the test functions without LLM if no key
is available.

Environment:
  GROQ_API_KEY — Groq Cloud API key (set in .env or shell)
"""

from __future__ import annotations

import importlib
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

# ---------------------------------------------------------------------------
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
# System prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert automotive verification engineer.  You write Python MIL
    test functions for an Adaptive Cruise Control (ACC) controller.

    The test harness provides:
      from src.models.acc_controller  import ACCController
      from src.models.plant_model     import PlantModel
      from src.utils.signal_metrics   import evaluate_oracle

    ACCController(sample_time_s, dtype='float64')
      .step(v_ego, v_lead, d_actual, v_set) → a_cmd, mode

    PlantModel(sample_time_s)
      .step(a_cmd, v_lead) → v_ego, x_ego, d_actual, v_lead_new

    evaluate_oracle(oracle_dict, signals_dict) → bool
      signals_dict keys: 'time','v_ego','v_lead','d_actual','a_cmd','mode','d_safe'

    Write ONE Python function named  run_<req_id_lower>  (e.g. run_acc_req_001).
    The function signature is: def run_acc_req_001(dtype='float64') -> dict:
    It must return:
      {
        'requirement_id': str,
        'passed': bool,
        'signals': {
            'time': list,
            'v_ego': list, 'v_lead': list, 'd_actual': list,
            'a_cmd': list, 'mode': list, 'd_safe': list,
        },
        'details': str,
      }

    Use only the standard library + numpy.  Do not import matplotlib.
    Output ONLY the Python function code, no markdown fences, no explanation.
""")


def _build_user_prompt(intent: dict) -> str:
    return textwrap.dedent(f"""\
        Generate the MIL test function for this Test-Intent:

        {json.dumps(intent, indent=2)}

        Remember: function name = run_{intent['requirement_id'].lower().replace('-','_')}
        Output only the Python function.
    """)


# ---------------------------------------------------------------------------
# LLM-based generator
# ---------------------------------------------------------------------------
def _generate_with_groq(intent: dict) -> str:
    client = _get_client()
    model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    import time
    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": _build_user_prompt(intent)},
                ],
                temperature=0.2,
                max_tokens=4096,
            )
            break
        except Exception as e:
            if ("429" in str(e) or "rate_limit" in str(e).lower()) and attempt < 3:
                time.sleep(4.0)
            else:
                raise
    raw = response.choices[0].message.content.strip()
    import re
    code_match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", raw)
    if code_match:
        raw = code_match.group(1).strip()
    elif "def run_" in raw:
        idx = raw.index("def run_")
        raw = raw[idx:].strip()

    return raw


# ---------------------------------------------------------------------------
# Deterministic fallback templates
# ---------------------------------------------------------------------------
_FALLBACK_TEMPLATES: dict[str, str] = {
    "ACC-REQ-001": textwrap.dedent("""\
        def run_acc_req_001(dtype='float64'):
            import numpy as np
            from src.models.acc_controller import ACCController
            from src.models.plant_model    import PlantModel
            Ts      = 0.1
            v_set   = 30.0
            d_init  = 50.0
            T_total = 20.0
            ctrl  = ACCController(Ts, dtype=dtype)
            plant = PlantModel(Ts)
            plant.reset(v_ego_init=28.0, d_init=d_init, v_lead_init=35.0)
            sig = {k: [] for k in ['time','v_ego','v_lead','d_actual','a_cmd','mode','d_safe']}
            for i in range(int(T_total/Ts)):
                t = i * Ts
                s = plant.state()
                a_cmd, mode = ctrl.step(s['v_ego'], s['v_lead'], s['d_actual'], v_set)
                plant.step(a_cmd)
                sig['time'].append(t); sig['v_ego'].append(s['v_ego'])
                sig['v_lead'].append(s['v_lead']); sig['d_actual'].append(s['d_actual'])
                sig['a_cmd'].append(a_cmd); sig['mode'].append(mode)
                sig['d_safe'].append(10.0 + 1.4*s['v_ego'])
            time  = np.array(sig['time'])
            v_ego = np.array(sig['v_ego'])
            mask  = time >= 5.0
            passed = bool(np.all(np.abs(v_ego[mask] - v_set) <= 0.5))
            details = (f"Max speed error in window [5,20]s = "
                       f"{np.max(np.abs(v_ego[mask]-v_set)):.3f} m/s  (limit 0.5 m/s)")
            return dict(requirement_id='ACC-REQ-001', passed=passed,
                        signals={k:list(v) for k,v in sig.items()}, details=details)
    """),

    "ACC-REQ-002": textwrap.dedent("""\
        def run_acc_req_002(dtype='float64'):
            import numpy as np
            from src.models.acc_controller import ACCController
            from src.models.plant_model    import PlantModel
            Ts = 0.1; T_total = 15.0; v_set = 30.0
            ctrl  = ACCController(Ts, dtype=dtype)
            plant = PlantModel(Ts)
            plant.reset(v_ego_init=30.0, d_init=45.0, v_lead_init=30.0)
            sig = {k: [] for k in ['time','v_ego','v_lead','d_actual','a_cmd','mode','d_safe']}
            for i in range(int(T_total/Ts)):
                t = i*Ts
                if t >= 2.0:
                    plant.lead_decelerate(-3.0)
                s = plant.state()
                a_cmd, mode = ctrl.step(s['v_ego'], s['v_lead'], s['d_actual'], v_set)
                plant.step(a_cmd)
                ds = 10.0 + 1.4*s['v_ego']
                sig['time'].append(t); sig['v_ego'].append(s['v_ego'])
                sig['v_lead'].append(s['v_lead']); sig['d_actual'].append(s['d_actual'])
                sig['a_cmd'].append(a_cmd); sig['mode'].append(mode); sig['d_safe'].append(ds)
            time = np.array(sig['time']); d_actual=np.array(sig['d_actual']); d_safe=np.array(sig['d_safe'])
            mask = time >= 5.0
            passed = bool(np.all(d_actual[mask] >= d_safe[mask]))
            details = (f"Min (d_actual-d_safe) in [5,15]s = "
                       f"{np.min(d_actual[mask]-d_safe[mask]):.3f} m (must be >= 0)")
            return dict(requirement_id='ACC-REQ-002', passed=passed,
                        signals={k:list(v) for k,v in sig.items()}, details=details)
    """),

    "ACC-REQ-003": textwrap.dedent("""\
        def run_acc_req_003(dtype='float64'):
            import numpy as np
            from src.models.acc_controller import ACCController
            from src.models.plant_model    import PlantModel
            Ts=0.1; T_total=10.0; v_set=25.0
            ctrl  = ACCController(Ts, dtype=dtype)
            plant = PlantModel(Ts)
            plant.reset(v_ego_init=25.0, d_init=60.0, v_lead_init=30.0)
            sig = {k: [] for k in ['time','v_ego','v_lead','d_actual','a_cmd','mode','d_safe']}
            for i in range(int(T_total/Ts)):
                t=i*Ts; s=plant.state()
                a_cmd,mode=ctrl.step(s['v_ego'],s['v_lead'],s['d_actual'],v_set)
                plant.step(a_cmd)
                ds_ctrl = ctrl.d_safe(s['v_ego'])
                ds_formula = 10.0 + 1.4*s['v_ego']
                sig['time'].append(t); sig['v_ego'].append(s['v_ego'])
                sig['v_lead'].append(s['v_lead']); sig['d_actual'].append(s['d_actual'])
                sig['a_cmd'].append(a_cmd); sig['mode'].append(mode)
                sig['d_safe'].append(ds_ctrl)
            d_safe_arr=np.array(sig['d_safe']); v_ego_arr=np.array(sig['v_ego'])
            expected = 10.0 + 1.4*v_ego_arr
            err = np.max(np.abs(d_safe_arr - expected))
            passed = bool(err < 1e-9)
            return dict(requirement_id='ACC-REQ-003', passed=passed,
                        signals={k:list(v) for k,v in sig.items()},
                        details=f"Max D_safe formula error = {err:.2e} m")
    """),

    "ACC-REQ-004": textwrap.dedent("""\
        def run_acc_req_004(dtype='float64'):
            import numpy as np
            from src.models.acc_controller import ACCController
            from src.models.plant_model    import PlantModel
            Ts=0.1; T_total=20.0; v_set=30.0
            ctrl  = ACCController(Ts, dtype=dtype)
            plant = PlantModel(Ts)
            plant.reset(v_ego_init=30.0, d_init=40.0, v_lead_init=30.0)
            sig = {k: [] for k in ['time','v_ego','v_lead','d_actual','a_cmd','mode','d_safe']}
            for i in range(int(T_total/Ts)):
                t=i*Ts
                if t >= 3.0:
                    plant.lead_decelerate(-5.0)
                s=plant.state()
                a_cmd,mode=ctrl.step(s['v_ego'],s['v_lead'],s['d_actual'],v_set)
                plant.step(a_cmd)
                sig['time'].append(t); sig['v_ego'].append(s['v_ego'])
                sig['v_lead'].append(s['v_lead']); sig['d_actual'].append(s['d_actual'])
                sig['a_cmd'].append(a_cmd); sig['mode'].append(mode)
                sig['d_safe'].append(10.0+1.4*s['v_ego'])
            a_cmd_arr=np.array(sig['a_cmd'])
            passed = bool(np.all(a_cmd_arr >= -3.0) and np.all(a_cmd_arr <= 2.0))
            details=(f"a_cmd range: [{a_cmd_arr.min():.3f}, {a_cmd_arr.max():.3f}] m/s²  "
                     f"(limit [-3, 2] m/s²)")
            return dict(requirement_id='ACC-REQ-004', passed=passed,
                        signals={k:list(v) for k,v in sig.items()}, details=details)
    """),

    "ACC-REQ-005": textwrap.dedent("""\
        def run_acc_req_005(dtype='float64'):
            import numpy as np
            from src.models.acc_controller import ACCController
            from src.models.plant_model    import PlantModel
            Ts=0.1; T_total=10.0; v_set=30.0; event_t=1.0
            ctrl  = ACCController(Ts, dtype=dtype)
            plant = PlantModel(Ts)
            plant.reset(v_ego_init=30.0, d_init=42.0, v_lead_init=30.0)
            sig = {k: [] for k in ['time','v_ego','v_lead','d_actual','a_cmd','mode','d_safe']}
            for i in range(int(T_total/Ts)):
                t=i*Ts
                if t >= event_t:
                    plant.lead_decelerate(-4.0)
                s=plant.state()
                a_cmd,mode=ctrl.step(s['v_ego'],s['v_lead'],s['d_actual'],v_set)
                plant.step(a_cmd)
                sig['time'].append(t); sig['v_ego'].append(s['v_ego'])
                sig['v_lead'].append(s['v_lead']); sig['d_actual'].append(s['d_actual'])
                sig['a_cmd'].append(a_cmd); sig['mode'].append(mode)
                sig['d_safe'].append(10.0+1.4*s['v_ego'])
            mode_arr=np.array(sig['mode']); time_arr=np.array(sig['time'])
            # Find first sample >= event where mode == 1 (spacing)
            post_mask = time_arr >= event_t
            switch_indices = np.where(post_mask & (mode_arr == 1))[0]
            if len(switch_indices) == 0:
                passed = False
                details = "Mode never switched to spacing control after event."
            else:
                switch_t = time_arr[switch_indices[0]]
                delay = switch_t - event_t
                passed = bool(delay <= Ts + 1e-9)
                details = f"Mode switch delay = {delay:.3f} s  (limit {Ts} s)"
            return dict(requirement_id='ACC-REQ-005', passed=passed,
                        signals={k:list(v) for k,v in sig.items()}, details=details)
    """),
}


def _generate_fallback(intent: dict) -> str:
    req_id = intent["requirement_id"]
    code = _FALLBACK_TEMPLATES.get(req_id, "")
    if not code:
        raise ValueError(f"No fallback template for {req_id}")
    return code


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_mil_test(intent: dict, use_llm: bool = True) -> str:
    """
    Generate a Python MIL test function string from a Test-Intent dict.

    Parameters
    ----------
    intent  : Test-Intent dict (from requirement_parser.parse_requirement)
    use_llm : Use Groq LLM if key available; else deterministic fallback

    Returns
    -------
    Python source code as a string
    """
    req_id = intent["requirement_id"]
    client = _get_client()
    if use_llm and client is not None:
        print(f"  [Groq] Generating MIL test for {req_id} …", end=" ", flush=True)
        try:
            code = _generate_with_groq(intent)
            func_name = f"run_{req_id.lower().replace('-','_')}"
            if f"def {func_name}" not in code:
                raise ValueError(f"Missing required function definition 'def {func_name}'")
            test_header = (
                "import sys\nimport numpy as np\n"
                "from src.models.acc_controller import ACCController\n"
                "from src.models.plant_model import PlantModel\n"
                "from src.utils.signal_metrics import evaluate_oracle\n"
            )
            compile(test_header + code, f"<{func_name}>", "exec")
            print("OK")
            return code
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED ({exc}) — using fallback")
            return _generate_fallback(intent)
    else:
        mode_str = "fallback (no GROQ_API_KEY)" if not client else "fallback (use_llm=False)"
        print(f"  [{mode_str}] Generating MIL test for {req_id}")
        return _generate_fallback(intent)


def generate_all_mil_tests(intents: list[dict], use_llm: bool = True) -> dict[str, str]:
    """Generate MIL test functions for all intents. Returns {req_id: code_str}."""
    print("\n=== Stage B: MIL Test Generation ===")
    tests = {}
    for intent in intents:
        code = generate_mil_test(intent, use_llm=use_llm)
        tests[intent["requirement_id"]] = code
    print(f"  Generated {len(tests)} test functions.\n")
    return tests


def save_mil_tests(tests: dict[str, str], output_dir: Path) -> list[Path]:
    """Write each test function to tests/mil/ and return the saved paths."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write individual files
    saved = []
    for req_id, code in tests.items():
        fname = f"test_{req_id.lower().replace('-','_')}.py"
        path = output_dir / fname
        header = textwrap.dedent(f"""\
            \"\"\"
            Auto-generated MIL test for {req_id}
            Generated by: src/genai/test_generator_mil.py
            \"\"\"
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

            import numpy as np
            from src.models.acc_controller import ACCController
            from src.models.plant_model import PlantModel
            from src.utils.signal_metrics import evaluate_oracle

        """)
        path.write_text(header + code, encoding="utf-8")
        saved.append(path)
        print(f"  Saved: {path.relative_to(ROOT)}")

    # Write a combined runner
    _write_test_runner(output_dir, list(tests.keys()))
    return saved


def _write_test_runner(output_dir: Path, req_ids: list[str]) -> None:
    """Write tests/mil/run_all_mil_tests.py — imports and runs every test."""
    imports = []
    calls = []
    for req_id in req_ids:
        mod = f"test_{req_id.lower().replace('-','_')}"
        fn  = f"run_{req_id.lower().replace('-','_').replace('-','_')}"
        imports.append(f"from tests.mil.{mod} import {fn}")
        calls.append(f"    results.append({fn}(dtype=dtype))")

    runner = textwrap.dedent("""\
        \"\"\"
        run_all_mil_tests.py
        --------------------
        Runs all generated MIL test functions and prints a summary table.
        \"\"\"
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

        {imports}


        def run_all(dtype='float64'):
            results = []
        {calls}
            return results


        if __name__ == '__main__':
            import argparse
            ap = argparse.ArgumentParser()
            ap.add_argument('--dtype', default='float64',
                            choices=['float64','float32','fixed16','fixed8'],
                            help='Numeric precision variant')
            args = ap.parse_args()

            print(f"\\n=== MIL Test Suite  [dtype={{args.dtype}}] ===")
            results = run_all(dtype=args.dtype)
            print()
            print(f"{{'Req ID':<15}} {{'Result':<8}}  Details")
            print("-" * 70)
            passed_count = 0
            for r in results:
                status = 'PASS' if r['passed'] else 'FAIL'
                if r['passed']:
                    passed_count += 1
                print(f"  {{r['requirement_id']:<13}} {{status:<8}}  {{r.get('details','')}}")
            print("-" * 70)
            print(f"  {{passed_count}}/{{len(results)}} passed\\n")
    """).format(
        imports="\n".join(imports),
        calls="\n".join(calls),
    )

    path = output_dir / "run_all_mil_tests.py"
    path.write_text(runner, encoding="utf-8")
    print(f"  Saved: {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# CLI quick-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    from src.genai.requirement_parser import parse_all_requirements

    ap = argparse.ArgumentParser(description="Generate MIL tests via Groq")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--out", default="tests/mil")
    args = ap.parse_args()

    intents = parse_all_requirements(use_llm=not args.no_llm)
    tests   = generate_all_mil_tests(intents, use_llm=not args.no_llm)
    save_mil_tests(tests, ROOT / args.out)
