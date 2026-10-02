"""
mvp/evidence_analyzer.py
------------------------
Phase 4 of the MVP loop: Evidence Analyzer.

Takes the raw Execution Result from MATLAB and enriches it with:
  - Per-condition analysis
  - Coverage gap detection
  - Boundary proximity scoring
  - Plain-language diagnosis

This is PURE Python — no AI call, no MATLAB.  It is fully deterministic
and works offline.  Its output feeds the Test Critic in Phase 5.
"""

from __future__ import annotations

from typing import Any


# Boundary proximity: within this % of threshold we flag as "BOUNDARY"
_BOUNDARY_RATIO = 0.10


def analyze(intent: dict, result: dict) -> dict:
    """
    Analyze execution evidence.

    Parameters
    ----------
    intent : Validated Test Intent dict.
    result : Execution Result dict from MATLAB.

    Returns
    -------
    Evidence Analysis dict with the following keys:
        verdict_summary    : str — human-readable one-line summary
        coverage_gaps      : list[str] — untested conditions / edge-cases
        boundary_proximity : dict[str, float] — 0..1 proximity to failure
        condition_analysis : list[dict] — per-oracle-condition breakdown
        diagnosis          : str — multi-line diagnosis text
        recommend_improvement : bool — True if loop should continue
        stop_reason        : str | None — if not improving, why we stopped
    """
    status  = result.get("execution_status", "unknown")
    verdict = result.get("requirement_verdict", "ERROR")
    metrics = result.get("measured_metrics", {})
    oracle_conds = intent.get("oracle", {}).get("conditions", [])
    eval_start = intent.get("oracle", {}).get("evaluation_window_start_s", 0)
    eval_end   = intent.get("oracle", {}).get("evaluation_window_end_s", intent.get("duration_s", 10))
    duration_s = intent.get("duration_s", 10)

    # ------------------------------------------------------------------ #
    # 1. Per-condition analysis                                            #
    # ------------------------------------------------------------------ #
    condition_analysis = []
    boundary_proximity: dict[str, float] = {}

    # Pull oracle results from MATLAB if available
    matlab_cond_results = result.get("oracle_conditions", [])
    cond_map = {c["signal"]: c for c in matlab_cond_results if isinstance(c, dict)}

    for cond in oracle_conds:
        sig     = cond["signal"]
        op      = cond["operator"]
        thresh  = cond["threshold"]
        m_cond  = cond_map.get(sig, {})
        measured = m_cond.get("measured", None)
        passed   = m_cond.get("passed", False)

        proximity = None
        if measured is not None and thresh != 0:
            proximity = abs(measured - thresh) / (abs(thresh) + 1e-9)
            boundary_proximity[f"{sig}/{op}/{thresh}"] = round(proximity, 4)

        condition_analysis.append({
            "signal":    sig,
            "operator":  op,
            "threshold": thresh,
            "measured":  measured,
            "passed":    passed,
            "proximity": round(proximity, 4) if proximity is not None else None,
            "near_boundary": (proximity is not None and proximity < _BOUNDARY_RATIO),
        })

    # ------------------------------------------------------------------ #
    # 2. Coverage gap detection                                            #
    # ------------------------------------------------------------------ #
    gaps = []
    scenario_type = intent.get("stimulus", {}).get("scenario_type", "unknown")
    events = intent.get("stimulus", {}).get("events", [])

    # Gap: evaluation window too short relative to duration
    eval_width = eval_end - eval_start
    if eval_width < 0.3 * duration_s:
        gaps.append(
            f"Evaluation window ({eval_width:.1f}s) is only "
            f"{100*eval_width/duration_s:.0f}% of simulation duration — "
            "steady-state might not be reached."
        )

    # Gap: no disturbance events tested
    has_lead_event = any(e.get("type") != "none" for e in events)
    if scenario_type == "lead_deceleration" and not has_lead_event:
        gaps.append("Scenario type is 'lead_deceleration' but no deceleration event is defined.")

    # Gap: safe distance never observed
    observed = intent.get("observed_signals", [])
    oracle_signals = [c.get("signal", "") for c in oracle_conds]
    dist_signals = {"d_safe", "d_actual", "gap_surplus"}
    accel_signals = {"a_cmd"}
    speed_signals = {"speed_error", "v_ego"}

    if not dist_signals.intersection(set(observed) | set(oracle_signals)):
        gaps.append("Neither d_safe, d_actual, nor gap_surplus is in observed_signals or oracle — safe-distance oracle is untestable.")

    # Gap: acceleration bounds not checked
    if not accel_signals.intersection(set(observed) | set(oracle_signals)):
        gaps.append("a_cmd not in observed_signals or oracle — acceleration bounds cannot be verified.")

    # Gap: only PASS with small margin is suspicious
    max_spd_err = metrics.get("max_speed_error_mps", None)
    if verdict == "PASS" and max_spd_err is not None and max_spd_err < 0.01:
        gaps.append(
            "Speed error is near zero throughout — initial conditions may be too close to steady state. "
            "Consider starting further from set-point."
        )

    # Gap: very short simulation
    if duration_s < 5:
        gaps.append(f"Simulation duration ({duration_s}s) may be too short to observe transient response.")

    # ------------------------------------------------------------------ #
    # 3. Plain-language diagnosis                                          #
    # ------------------------------------------------------------------ #
    diag_lines = []
    diag_lines.append(f"Execution status : {status}")
    diag_lines.append(f"Requirement verdict: {verdict}")
    diag_lines.append("")

    for ca in condition_analysis:
        mark = "✓" if ca["passed"] else "✗"
        prox_str = f"  (boundary proximity: {ca['proximity']:.3f})" if ca["proximity"] is not None else ""
        diag_lines.append(
            f"  [{mark}] {ca['signal']} {ca['operator']} {ca['threshold']} "
            f"→ measured={ca['measured']}{prox_str}"
        )

    diag_lines.append("")
    if metrics:
        diag_lines.append("Key metrics:")
        for k, v in metrics.items():
            diag_lines.append(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    if gaps:
        diag_lines.append("")
        diag_lines.append("Coverage gaps detected:")
        for g in gaps:
            diag_lines.append(f"  ⚠ {g}")

    for err in result.get("errors", []):
        if err:
            diag_lines.append(f"  ✗ ERROR: {err}")

    diagnosis = "\n".join(diag_lines)

    # ------------------------------------------------------------------ #
    # 4. Recommend improvement?                                            #
    # ------------------------------------------------------------------ #
    recommend = False
    stop_reason = None

    if verdict in ("FAIL", "ERROR", "UNCERTAIN"):
        recommend = True
    elif verdict == "PASS" and gaps:
        recommend = True
    elif verdict == "PASS" and not gaps:
        stop_reason = "PASS with no coverage gaps — requirement is verified."

    return {
        "verdict_summary":    f"{verdict} — {status}",
        "coverage_gaps":      gaps,
        "boundary_proximity": boundary_proximity,
        "condition_analysis": condition_analysis,
        "diagnosis":          diagnosis,
        "recommend_improvement": recommend,
        "stop_reason":        stop_reason,
    }
