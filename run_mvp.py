#!/usr/bin/env python3
"""
run_mvp.py
----------
Master Orchestrator — Autonomous GenAI Test Generation & Improvement Loop.

Architecture:
  Python  = AI Brain  (Groq LLM: test generation, test critic)
  MATLAB  = Simulation Engine  (ACC controller + plant model)

Loop per requirement:
  ┌──────────────────────────────────────────────────────────────────┐
  │  [Phase 1] EARS Requirements                                     │
  │      ↓                                                           │
  │  [Phase 2] LLM → Test Intent JSON  (test_generator.py)          │
  │      ↓                                                           │
  │  [Phase 3] MATLAB → Execution Result  (matlab_executor.py)      │
  │      ↓                                                           │
  │  [Phase 4] Evidence Analyzer  (evidence_analyzer.py)            │
  │      ↓                                                           │
  │  [Phase 5] Test Critic  (test_critic.py)                        │
  │      ↓                                                           │
  │  stop? ──yes──→ [Phase 6] Report Writer  (report_writer.py)     │
  │      │                                                           │
  │      no → back to [Phase 2] with improvement context            │
  └──────────────────────────────────────────────────────────────────┘

Usage:
  python run_mvp.py                         # run all 5 requirements
  python run_mvp.py --req ACC-REQ-001       # single requirement
  python run_mvp.py --req ACC-REQ-001 --max-iterations 5
  python run_mvp.py --dry-run               # skip MATLAB, use mock results
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Force UTF-8 so emoji/unicode in print() works on Windows terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# ── Internal MVP modules ──────────────────────────────────────────────────
from mvp.test_generator   import generate_test_intent
from mvp.matlab_executor  import run_test_in_matlab
from mvp.evidence_analyzer import analyze
from mvp.test_critic      import critique
from mvp.report_writer    import write_report

# ── Requirements (re-use the existing EARS model) ────────────────────────
sys.path.insert(0, str(ROOT))
from requirements.acc_requirements import ALL_REQUIREMENTS

STORE_DIR = ROOT / "mvp" / "store"
ARTIFACTS_DIR = ROOT / "mvp" / "artifacts"

# ──────────────────────────────────────────────────────────────────────────
# Dry-run mock executor (skips MATLAB, returns synthetic data)
# ──────────────────────────────────────────────────────────────────────────
def _mock_execute(intent: dict) -> dict:
    """Return a plausible synthetic result without invoking MATLAB."""
    import random, math
    v_set   = intent["stimulus"]["initial_conditions"].get("v_set_mps", 20)
    rng     = random.Random(hash(intent["test_id"]) % (2**31))
    err     = rng.uniform(0.05, 0.6)
    verdict = "PASS" if err < 0.5 else "FAIL"
    return {
        "test_id":             intent["test_id"],
        "run_id":              f"MOCK-{intent['iteration']:02d}",
        "requirement_id":      intent["requirement_id"],
        "execution_status":    "success",
        "requirement_verdict": verdict,
        "measured_metrics": {
            "max_speed_error_mps": err,
            "rms_speed_error_mps": err * 0.6,
            "min_gap_surplus_m":   rng.uniform(-1, 5),
            "a_cmd_min_mps2":      rng.uniform(-3, -1),
            "a_cmd_max_mps2":      rng.uniform(0.5, 2),
        },
        "signal_traces": {},
        "oracle_conditions": [
            {"signal": c["signal"], "operator": c["operator"],
             "threshold": c["threshold"], "measured": c["threshold"] + rng.uniform(-0.3, 0.3),
             "passed": verdict == "PASS"}
            for c in intent.get("oracle", {}).get("conditions", [])
        ],
        "warnings": [],
        "errors": [],
        "model_info": {"controller": "ACCController_MOCK", "plant": "PlantModel_MOCK"},
        "budget_used": {"wall_time_s": rng.uniform(0.1, 0.5), "iteration": intent["iteration"]},
    }


# ──────────────────────────────────────────────────────────────────────────
# Core per-requirement loop
# ──────────────────────────────────────────────────────────────────────────
def run_loop(
    req,
    max_iterations: int = 3,
    dry_run: bool = False,
) -> dict:
    """
    Run the full improvement loop for a single EARS requirement.

    Returns a summary dict.
    """
    req_id   = req.id
    req_text = req.text
    numeric  = req.numeric_params

    print()
    print("=" * 70)
    print(f"  REQUIREMENT: {req_id}")
    print(f"  {req_text[:80]}{'...' if len(req_text)>80 else ''}")
    print("=" * 70)

    loop_history = []
    prev_intent  = None
    prev_result  = None
    prev_analysis = None
    prev_critic  = None
    iteration    = 1

    while True:
        print(f"\n  --- Iteration {iteration}/{max_iterations} ---")

        # ── Phase 2: Generate / Improve Test Intent ──
        print()
        print("  [Phase 2] Test Generator …")
        try:
            intent = generate_test_intent(
                req_id=req_id,
                req_text=req_text,
                numeric_params=numeric,
                iteration=iteration,
                prev_intent=prev_intent,
                evidence=prev_result,
                critic=prev_critic,
            )
        except Exception as e:
            print(f"  [FATAL] Test Generator failed: {e}")
            break

        # Save intent
        intent_path = ARTIFACTS_DIR / f"{req_id}_I{iteration}_intent.json"
        intent_path.parent.mkdir(parents=True, exist_ok=True)
        with open(intent_path, "w") as f:
            json.dump(intent, f, indent=2)

        # ── Phase 3: Execute in MATLAB (or mock) ──
        print()
        print("  [Phase 3] MATLAB Executor …")
        if dry_run:
            result = _mock_execute(intent)
        else:
            result = run_test_in_matlab(intent, artifacts_dir=ARTIFACTS_DIR)

        # Save result
        result_path = ARTIFACTS_DIR / f"{req_id}_I{iteration}_result.json"
        with open(result_path, "w") as f:
            json.dump(result, f, indent=2)

        # ── Phase 4: Evidence Analyzer ──
        print()
        print("  [Phase 4] Evidence Analyzer …")
        analysis = analyze(intent, result)
        print(f"           Verdict summary: {analysis['verdict_summary']}")
        if analysis["coverage_gaps"]:
            print(f"           Gaps found ({len(analysis['coverage_gaps'])}):")
            for g in analysis["coverage_gaps"]:
                print(f"             ⚠ {g}")

        # ── Phase 5: Test Critic ──
        print()
        print("  [Phase 5] Test Critic …")
        critic = critique(
            req_id=req_id,
            req_text=req_text,
            intent=intent,
            result=result,
            analysis=analysis,
            iteration=iteration,
            max_iterations=max_iterations,
        )

        # Record this iteration
        loop_history.append({
            "intent":   intent,
            "result":   result,
            "analysis": analysis,
            "critic":   critic,
        })

        # ── Check stopping condition ──
        if critic.get("stop_loop", False):
            reason = critic.get("stop_reason", "Critic stopped loop.")
            print(f"\n  [Loop] STOPPING: {reason}")
            break

        # Prepare next iteration
        prev_intent   = intent
        prev_result   = result
        prev_analysis = analysis
        prev_critic   = critic
        iteration    += 1

    # ── Phase 6: Write Reports ──
    if not loop_history:
        print(f"\n  [Loop] No iterations completed for {req_id}. Skipping report.")
        return {
            "requirement_id": req_id,
            "final_verdict":  "ERROR",
            "iterations_run": 0,
            "scorecard":      "N/A",
        }

    print()
    print("  [Phase 6] Writing Reports …")
    scorecard_path = write_report(
        req_id=req_id,
        req_text=req_text,
        loop_history=loop_history,
        output_dir=STORE_DIR,
    )

    final_verdict = loop_history[-1]["result"].get("requirement_verdict", "ERROR")
    return {
        "requirement_id":   req_id,
        "final_verdict":    final_verdict,
        "iterations_run":   len(loop_history),
        "scorecard":        str(scorecard_path),
    }


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="MVP Autonomous GenAI Verification Loop"
    )
    parser.add_argument(
        "--req", default=None,
        help="Run only this requirement, e.g. ACC-REQ-001 (default: all)"
    )
    parser.add_argument(
        "--max-iterations", type=int, default=3,
        help="Maximum improvement iterations per requirement (default: 3)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip MATLAB; use mock simulation results (for testing the loop logic)"
    )
    args = parser.parse_args()

    print()
    print("=" * 70)
    print("  MVP: Autonomous GenAI Test Generation & Improvement Loop")
    print(f"  Mode: {'DRY RUN (mock MATLAB)' if args.dry_run else 'LIVE (real MATLAB)'}")
    print(f"  Max iterations per requirement: {args.max_iterations}")
    print("=" * 70)

    # Select requirements
    if args.req:
        reqs = [r for r in ALL_REQUIREMENTS if r.id == args.req]
        if not reqs:
            print(f"ERROR: Requirement '{args.req}' not found.")
            print(f"Available: {[r.id for r in ALL_REQUIREMENTS]}")
            sys.exit(1)
    else:
        reqs = ALL_REQUIREMENTS

    t_total = time.time()
    summaries = []

    for req in reqs:
        summary = run_loop(
            req=req,
            max_iterations=args.max_iterations,
            dry_run=args.dry_run,
        )
        summaries.append(summary)

    # ── Final summary table ──────────────────────────────────────────────
    elapsed = time.time() - t_total
    print()
    print("=" * 70)
    print("  FINAL SUMMARY")
    print("=" * 70)
    print(f"  {'Requirement':<18} {'Verdict':<12} {'Iterations':<12} Scorecard")
    print(f"  {'-'*18} {'-'*12} {'-'*12} {'-'*30}")
    for s in summaries:
        icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "ERROR": "[ERR ]"}.get(s["final_verdict"], "[?   ]")
        sc   = Path(s["scorecard"]).name if s["scorecard"] != "N/A" else "N/A"
        print(f"  {s['requirement_id']:<18} {icon} {s['final_verdict']:<10} {s['iterations_run']:<12} {sc}")

    print(f"\n  Total wall time: {elapsed:.1f}s")
    print(f"  Reports in: {STORE_DIR}")
    print()


if __name__ == "__main__":
    main()
