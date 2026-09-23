"""
run_poc.py
----------
Main entry point for PoC-1: GenAI-Driven MIL Verification Framework
for Adaptive Cruise Control (MPC Baseline).

8-Step execution pipeline (mirrors PoC-1 Section 5):

  Step 1  — Load EARS requirements
  Step 2  — Parse requirements → Test-Intent JSON  (Groq LLM or fallback)
  Step 3  — Generate MIL test scripts              (Groq LLM or fallback)
  Step 4  — Generate HIL stubs                     (Groq LLM or fallback)
  Step 5  — Run MIL baseline suite (float64)
  Step 6  — Run Option B: Target-Fitness Screening
              6a. Precision degradation (float64→float32→fixed16→fixed8)
              6b. Sample-time degradation (Ts=0.1→0.2→0.5 s)
  Step 7  — Generate scorecard (text + PNG plot)
  Step 8  — Print traceability matrix and summary

Usage
-----
  python run_poc.py                     # Full pipeline with Groq LLM
  python run_poc.py --no-llm            # Deterministic fallback only
  python run_poc.py --skip-gen          # Skip LLM stages, use cached intents
  python run_poc.py --steps 5,6,7       # Run only specific steps

Environment
-----------
  GROQ_API_KEY  — Groq Cloud API key (set in .env or shell)
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(step: int, title: str) -> None:
    print(f"\n{'='*70}")
    print(f"  STEP {step}: {title}")
    print(f"{'='*70}")


def _load_cached_intents(cache_dir: Path) -> list[dict] | None:
    """Load previously saved Test-Intent JSONs from disk."""
    files = sorted(cache_dir.glob("*_intent.json"))
    if not files:
        return None
    intents = []
    for f in files:
        intents.append(json.loads(f.read_text(encoding="utf-8")))
    print(f"  Loaded {len(intents)} cached intents from {cache_dir.relative_to(ROOT)}")
    return intents


def _load_and_run_mil_tests(mil_dir: Path, dtype: str = "float64") -> list[dict]:
    """
    Dynamically import and execute each generated MIL test function.

    Falls back to embedded runner if generated files aren't present.
    """
    results = []
    test_files = sorted(mil_dir.glob("test_acc_req_*.py"))

    if not test_files:
        print("  No generated test files found — running built-in fallback tests.")
        return _run_builtin_mil_tests(dtype)

    for fpath in test_files:
        mod_name = f"tests.mil.{fpath.stem}"
        fn_name  = fpath.stem.replace("test_", "run_")
        try:
            spec = importlib.util.spec_from_file_location(mod_name, fpath)
            mod  = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            fn = getattr(mod, fn_name)
            r  = fn(dtype=dtype)
            results.append(r)
        except Exception as exc:  # noqa: BLE001
            req_id = fpath.stem.replace("test_", "").upper().replace("_", "-")
            results.append({
                "requirement_id": req_id,
                "passed": False,
                "details": f"Test execution error: {exc}",
                "signals": {},
            })
    return results


def _run_builtin_mil_tests(dtype: str = "float64") -> list[dict]:
    """Run the fallback test suite directly without generated files."""
    from src.models.acc_controller import ACCController
    from src.models.plant_model    import PlantModel
    import numpy as np

    results = []
    Ts = 0.1; T = 20.0; v_set = 30.0

    def _simulate(v_ego0, d_init, v_lead0, event_t=None, lead_decel=0.0):
        ctrl  = ACCController(Ts, dtype=dtype)
        plant = PlantModel(Ts)
        plant.reset(v_ego_init=v_ego0, d_init=d_init, v_lead_init=v_lead0)
        sig = {k: [] for k in ["time","v_ego","v_lead","d_actual","a_cmd","mode","d_safe"]}
        for i in range(int(T/Ts)):
            t = i*Ts
            if event_t and t >= event_t:
                plant.lead_decelerate(lead_decel)
            s = plant.state()
            a_cmd, mode = ctrl.step(s["v_ego"], s["v_lead"], s["d_actual"], v_set)
            plant.step(a_cmd)
            sig["time"].append(t); sig["v_ego"].append(s["v_ego"])
            sig["v_lead"].append(s["v_lead"]); sig["d_actual"].append(s["d_actual"])
            sig["a_cmd"].append(a_cmd); sig["mode"].append(mode)
            sig["d_safe"].append(ctrl.d_safe(s["v_ego"]))
        return {k: np.array(v) for k, v in sig.items()}

    # REQ-001
    s = _simulate(28.0, 60.0, 35.0)
    mask = s["time"] >= 5.0
    passed = bool(np.all(np.abs(s["v_ego"][mask] - v_set) <= 0.5))
    results.append({"requirement_id":"ACC-REQ-001","passed":passed,
                    "details":f"Max spd err={np.max(np.abs(s['v_ego'][mask]-v_set)):.3f} m/s","signals":{}})

    # REQ-002
    s = _simulate(30.0, 45.0, 30.0, event_t=2.0, lead_decel=-3.0)
    mask = s["time"] >= 5.0
    passed = bool(np.all(s["d_actual"][mask] >= s["d_safe"][mask]))
    results.append({"requirement_id":"ACC-REQ-002","passed":passed,
                    "details":f"Min gap surplus={np.min(s['d_actual'][mask]-s['d_safe'][mask]):.3f} m","signals":{}})

    # REQ-003
    s = _simulate(25.0, 60.0, 30.0)
    expected = 10.0 + 1.4 * s["v_ego"]
    err = float(np.max(np.abs(s["d_safe"] - expected)))
    results.append({"requirement_id":"ACC-REQ-003","passed": err < 1e-9,
                    "details":f"D_safe formula err={err:.2e}","signals":{}})

    # REQ-004
    s = _simulate(30.0, 40.0, 30.0, event_t=3.0, lead_decel=-5.0)
    passed = bool(np.all(s["a_cmd"] >= -3.0) and np.all(s["a_cmd"] <= 2.0))
    results.append({"requirement_id":"ACC-REQ-004","passed":passed,
                    "details":f"a_cmd range=[{s['a_cmd'].min():.3f},{s['a_cmd'].max():.3f}]","signals":{}})

    # REQ-005
    s = _simulate(30.0, 42.0, 30.0, event_t=1.0, lead_decel=-4.0)
    post = s["time"] >= 1.0
    switch = np.where(post & (s["mode"] == 1))[0]
    if len(switch) == 0:
        results.append({"requirement_id":"ACC-REQ-005","passed":False,
                        "details":"Mode never switched","signals":{}})
    else:
        delay = float(s["time"][switch[0]]) - 1.0
        results.append({"requirement_id":"ACC-REQ-005","passed": delay <= Ts + 1e-9,
                        "details":f"Switch delay={delay:.3f} s (limit {Ts} s)","signals":{}})
    return results


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(args: argparse.Namespace) -> None:
    t_start = time.perf_counter()

    steps = set(args.steps.split(",")) if args.steps else None

    def should_run(step_num: int) -> bool:
        return steps is None or str(step_num) in steps

    use_llm  = not args.no_llm
    mil_dir  = ROOT / "tests" / "mil"
    hil_dir  = ROOT / "tests" / "hil"
    intent_dir = mil_dir / "intents"
    results_dir = ROOT / "results"

    intents: list[dict] | None = None
    mil_results: list[dict] = []

    # ---- Step 1 ----
    if should_run(1):
        _banner(1, "Load EARS Requirements")
        from requirements.acc_requirements import ALL_REQUIREMENTS
        for req in ALL_REQUIREMENTS:
            print(f"  {req.id}  [{req.category}]")

    # ---- Step 2 ----
    if should_run(2):
        _banner(2, "Parse Requirements -> Test-Intent JSON  (Groq LLM)")
        if args.skip_gen:
            intents = _load_cached_intents(intent_dir)
        if intents is None:
            from src.genai.requirement_parser import parse_all_requirements, save_intents
            intents = parse_all_requirements(use_llm=use_llm)
            save_intents(intents, intent_dir)
    elif not args.skip_gen:
        intents = _load_cached_intents(intent_dir) or []

    # ---- Step 3 ----
    if should_run(3) and not args.skip_gen:
        _banner(3, "Generate MIL Test Scripts  (Groq LLM)")
        if intents:
            from src.genai.test_generator_mil import generate_all_mil_tests, save_mil_tests
            tests = generate_all_mil_tests(intents, use_llm=use_llm)
            save_mil_tests(tests, mil_dir)
        else:
            print("  No intents available — skipping MIL test generation.")

    # ---- Step 4 ----
    if should_run(4) and not args.skip_gen:
        _banner(4, "Generate HIL Stubs  (Groq LLM)")
        if intents:
            from src.genai.test_generator_hil import generate_all_hil_stubs, save_hil_stubs
            stubs = generate_all_hil_stubs(intents, use_llm=use_llm)
            save_hil_stubs(stubs, hil_dir)
        else:
            print("  No intents available — skipping HIL stub generation.")

    # ---- Step 5 ----
    if should_run(5):
        _banner(5, "Run MIL Baseline Test Suite  (float64)")
        mil_results = _load_and_run_mil_tests(mil_dir, dtype="float64")
        total, passed = len(mil_results), sum(1 for r in mil_results if r.get("passed"))
        print(f"\n  {'Req ID':<15} {'PASS/FAIL':<10}  Details")
        print(f"  {'-'*65}")
        for r in mil_results:
            pf = "PASS" if r.get("passed") else "FAIL"
            print(f"  {r.get('requirement_id','?'):<15} {pf:<10}  {r.get('details','')}")
        print(f"\n  Result: {passed}/{total} requirements PASS at float64 baseline")

    # ---- Step 6 ----
    if should_run(6):
        _banner(6, "Option B — Target-Fitness Screening")
        from src.models.target_fitness_degrader import run_full_screening
        prec_report, ts_report = run_full_screening()
    else:
        prec_report, ts_report = None, None

    # ---- Step 7 ----
    if should_run(7):
        _banner(7, "Generate Target-Fitness Scorecard")
        if prec_report and ts_report:
            from results.scorecard import (
                build_text_scorecard, save_text_scorecard, build_scorecard_plot
            )
            text = build_text_scorecard(prec_report, ts_report, mil_results or None)
            save_text_scorecard(text, results_dir / "scorecard.txt")
            build_scorecard_plot(prec_report, ts_report, results_dir / "scorecard.png")
            print("\n" + text)
        else:
            print("  Screening results not available — run steps 6 first.")

    # ---- Step 8 ----
    if should_run(8):
        _banner(8, "Traceability Matrix & Summary")
        if intents:
            print(f"\n  {'Req ID':<15} {'Category':<22} {'MIL Result':<12}  Test-Intent Generated By")
            print(f"  {'-'*75}")
            mil_map = {r["requirement_id"]: r for r in mil_results}
            for intent in intents:
                rid      = intent["requirement_id"]
                cat      = intent.get("category", "?")
                gen_by   = intent.get("metadata", {}).get("generated_by", "?")
                mil_r    = mil_map.get(rid, {})
                pf       = "PASS" if mil_r.get("passed") else ("FAIL" if mil_r else "N/A")
                print(f"  {rid:<15} {cat:<22} {pf:<12}  {gen_by}")
        else:
            print("  No intents available for traceability matrix.")

    elapsed = time.perf_counter() - t_start
    print(f"\n{'='*70}")
    print(f"  PoC-1 pipeline complete in {elapsed:.1f} s")
    print(f"  Outputs:")
    print(f"    tests/mil/intents/     — Test-Intent JSONs")
    print(f"    tests/mil/             — Generated MIL test scripts")
    print(f"    tests/hil/             — HIL stub descriptors")
    print(f"    results/scorecard.txt  — Target-Fitness Scorecard (text)")
    print(f"    results/scorecard.png  — Target-Fitness Scorecard (plot)")
    print(f"{'='*70}\n")


def run_matlab_pipeline() -> None:
    """Execute the PoC-1 verification pipeline directly in MATLAB R2024a."""
    import shutil
    import subprocess

    matlab_bin = shutil.which("matlab")
    if not matlab_bin:
        candidates = [
            Path("C:/Program Files/MATLAB/R2024a/bin/matlab.exe"),
            Path("C:/Program Files/MATLAB/R2023b/bin/matlab.exe"),
            Path("C:/Program Files/MATLAB/R2023a/bin/matlab.exe"),
        ]
        for c in candidates:
            if c.exists():
                matlab_bin = str(c)
                break

    if not matlab_bin:
        print("ERROR: MATLAB executable could not be found in PATH or standard Program Files locations.")
        sys.exit(1)

    print(f"\n[MATLAB] Invoking MATLAB engine at: {matlab_bin}")
    print("[MATLAB] Executing run_poc.m in batch mode...\n")

    cmd = [matlab_bin, "-batch", "run_poc; exit"]
    p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in iter(p.stdout.readline, ''):
        print(line, end='', flush=True)
    p.stdout.close()
    return_code = p.wait()
    if return_code != 0:
        print(f"\n[MATLAB] Execution exited with error code {return_code}")
        sys.exit(return_code)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="PoC-1: GenAI-Driven MIL Verification Framework for ACC"
    )
    ap.add_argument(
        "--matlab", action="store_true",
        help="Run verification directly on real MATLAB engine (R2024a)"
    )
    ap.add_argument(
        "--no-llm", action="store_true",
        help="Skip Groq LLM; use deterministic fallback for all GenAI stages"
    )
    ap.add_argument(
        "--skip-gen", action="store_true",
        help="Skip Steps 2-4 (use cached intents and generated test files)"
    )
    ap.add_argument(
        "--steps", default=None,
        help="Comma-separated step numbers to run, e.g. '5,6,7' (default: all)"
    )
    args = ap.parse_args()

    if args.matlab:
        run_matlab_pipeline()
    else:
        run_pipeline(args)
