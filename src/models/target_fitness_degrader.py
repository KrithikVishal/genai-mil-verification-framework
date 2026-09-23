"""
target_fitness_degrader.py
--------------------------
Option B — MIL-Stage Target-Fitness Screening ("Shift-Left SIL")

Implements the core degradation loop described in Doc9 Section 4 / Option B:

  1. Take the working float64 ACC controller as the reference baseline.
  2. Re-simulate under progressively harsher, target-like conditions:
       - Reduced numeric precision: float64 → float32 → fixed16 → fixed8
       - Coarser sample times:      0.1 s → 0.2 s → 0.5 s
  3. Compare each degraded variant back-to-back against the reference.
  4. Find the divergence point on each axis.
  5. Emit a target-fitness scorecard row per variant.

This module is framework-independent — it uses only the Python models and
utility functions defined in this project.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from src.models.acc_controller import ACCController
from src.models.plant_model    import PlantModel
from src.utils.precision_emulator import (
    dtype_resolution,
    dtype_range,
    static_memory_bytes,
)
from src.utils.signal_metrics import (
    rms_error,
    max_abs_error,
    divergence_index,
)

# ---------------------------------------------------------------------------
# Degradation ladder
# ---------------------------------------------------------------------------

PRECISION_VARIANTS: list[str] = ["float64", "float32", "fixed16", "fixed8"]

SAMPLE_TIME_VARIANTS: list[float] = [0.1, 0.2, 0.5]   # seconds


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class SimResult:
    """Signals from one closed-loop simulation run."""
    time:     np.ndarray
    v_ego:    np.ndarray
    v_lead:   np.ndarray
    d_actual: np.ndarray
    a_cmd:    np.ndarray
    mode:     np.ndarray
    d_safe:   np.ndarray

    def as_dict(self) -> dict[str, np.ndarray]:
        return {k: getattr(self, k) for k in
                ["time","v_ego","v_lead","d_actual","a_cmd","mode","d_safe"]}


@dataclass
class VariantResult:
    """Comparison result for one degraded variant vs. the float64 reference."""
    variant_label:     str          # e.g. "float32" or "Ts=0.20s"
    dtype:             str
    sample_time_s:     float
    rms_speed_error:   float        # RMS |v_ego_var - v_ego_ref|
    max_speed_error:   float
    rms_dist_error:    float        # RMS |d_actual_var - d_actual_ref|
    max_dist_error:    float
    divergence_step:   Optional[int]  # First step where speed error > tol
    divergence_time_s: Optional[float]
    passes_req001:     bool         # Speed tracking ±0.5 m/s
    passes_req002:     bool         # d_actual >= d_safe in window
    passes_req004:     bool         # Acceleration bounds
    memory_bytes:      int
    resolution:        float
    wall_time_s:       float        # Compute time of this variant


@dataclass
class FitnessReport:
    """Aggregated target-fitness results for all variants."""
    scenario_label:  str
    reference:       VariantResult
    variants:        list[VariantResult] = field(default_factory=list)

    def all_results(self) -> list[VariantResult]:
        return [self.reference] + self.variants


# ---------------------------------------------------------------------------
# Core simulation runner
# ---------------------------------------------------------------------------

def _run_simulation(
    dtype: str,
    sample_time_s: float,
    v_set:    float = 30.0,
    v_lead_init: float = 30.0,
    d_init:   float = 42.0,
    v_ego_init: float = 28.0,
    event_t:  float = 2.0,
    lead_decel: float = -3.0,
    T_total:  float = 15.0,
) -> SimResult:
    """
    Run the ACC closed-loop simulation for a single variant.

    Uses a combined scenario (steady-state then lead-decel event) that
    exercises all five ACC requirements simultaneously.
    """
    Ts    = sample_time_s
    n_steps = int(T_total / Ts)

    ctrl  = ACCController(sample_time_s=Ts, dtype=dtype)
    plant = PlantModel(sample_time_s=Ts)
    plant.reset(v_ego_init=v_ego_init, d_init=d_init, v_lead_init=v_lead_init)

    time_arr     = np.zeros(n_steps)
    v_ego_arr    = np.zeros(n_steps)
    v_lead_arr   = np.zeros(n_steps)
    d_actual_arr = np.zeros(n_steps)
    a_cmd_arr    = np.zeros(n_steps)
    mode_arr     = np.zeros(n_steps, dtype=int)
    d_safe_arr   = np.zeros(n_steps)

    for i in range(n_steps):
        t = i * Ts
        s = plant.state()

        a_cmd, mode = ctrl.step(s["v_ego"], s["v_lead"], s["d_actual"], v_set)

        time_arr[i]     = t
        v_ego_arr[i]    = s["v_ego"]
        v_lead_arr[i]   = s["v_lead"]
        d_actual_arr[i] = s["d_actual"]
        a_cmd_arr[i]    = a_cmd
        mode_arr[i]     = mode
        d_safe_arr[i]   = ctrl.d_safe(s["v_ego"])

        if t >= event_t:
            plant.lead_decelerate(lead_decel)
        plant.step(a_cmd)

    return SimResult(
        time=time_arr,
        v_ego=v_ego_arr,
        v_lead=v_lead_arr,
        d_actual=d_actual_arr,
        a_cmd=a_cmd_arr,
        mode=mode_arr,
        d_safe=d_safe_arr,
    )


def _evaluate_variant(
    variant: SimResult,
    reference: SimResult,
    dtype: str,
    sample_time_s: float,
    label: str,
    wall_time_s: float,
    tolerance_speed: float = 0.5,
) -> VariantResult:
    """Compare variant signals to reference and produce a VariantResult."""
    # Interpolate variant onto reference time axis if sample times differ
    if len(variant.time) != len(reference.time):
        v_ego_var    = np.interp(reference.time, variant.time, variant.v_ego)
        d_actual_var = np.interp(reference.time, variant.time, variant.d_actual)
        a_cmd_var    = np.interp(reference.time, variant.time, variant.a_cmd)
    else:
        v_ego_var    = variant.v_ego
        d_actual_var = variant.d_actual
        a_cmd_var    = variant.a_cmd

    rms_spd  = rms_error(v_ego_var, reference.v_ego)
    max_spd  = max_abs_error(v_ego_var, reference.v_ego)
    rms_dist = rms_error(d_actual_var, reference.d_actual)
    max_dist = max_abs_error(d_actual_var, reference.d_actual)

    div_step = divergence_index(v_ego_var, reference.v_ego, tolerance=tolerance_speed)
    div_t    = float(reference.time[div_step]) if div_step is not None else None

    # REQ-001: speed fidelity within ±0.5 m/s of baseline
    passes_001 = bool(max_spd <= tolerance_speed)

    # REQ-002: d_actual >= d_safe in settled window [5, 15]s
    d_safe_var = 10.0 + 1.4 * v_ego_var
    mask_event = reference.time >= 5.0
    passes_002 = bool(np.all(d_actual_var[mask_event] >= d_safe_var[mask_event]))

    # REQ-004: acceleration bounds [-3, 2]
    passes_004 = bool(np.all(a_cmd_var >= -3.0) and np.all(a_cmd_var <= 2.0))

    return VariantResult(
        variant_label     = label,
        dtype             = dtype,
        sample_time_s     = sample_time_s,
        rms_speed_error   = rms_spd,
        max_speed_error   = max_spd,
        rms_dist_error    = rms_dist,
        max_dist_error    = max_dist,
        divergence_step   = div_step,
        divergence_time_s = div_t,
        passes_req001     = passes_001,
        passes_req002     = passes_002,
        passes_req004     = passes_004,
        memory_bytes      = static_memory_bytes(dtype),
        resolution        = dtype_resolution(dtype),
        wall_time_s       = wall_time_s,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_precision_screening(scenario_label: str = "lead_deceleration") -> FitnessReport:
    """
    Run precision degradation screening.

    Runs the reference simulation (float64) and then float32, fixed16, fixed8
    variants.  Returns a FitnessReport with all comparison results.
    """
    print("\n--- Precision screening ---")

    # Reference
    t0 = _time.perf_counter()
    ref_sim = _run_simulation(dtype="float64", sample_time_s=0.1)
    ref_wall = _time.perf_counter() - t0
    ref_result = _evaluate_variant(ref_sim, ref_sim, "float64", 0.1, "float64 (ref)", ref_wall)
    print(f"  [REF]  float64  wall={ref_wall*1000:.1f} ms")

    report = FitnessReport(scenario_label=scenario_label, reference=ref_result)

    for dtype in ["float32", "fixed16", "fixed8"]:
        t0 = _time.perf_counter()
        var_sim = _run_simulation(dtype=dtype, sample_time_s=0.1)
        wall = _time.perf_counter() - t0
        vr = _evaluate_variant(var_sim, ref_sim, dtype, 0.1, dtype, wall)
        report.variants.append(vr)
        status = "PASS" if (vr.passes_req001 and vr.passes_req002 and vr.passes_req004) else "FAIL"
        print(f"  [{status}]  {dtype:<8}  rms_spd={vr.rms_speed_error:.4f} m/s  "
              f"div_t={vr.divergence_time_s}  mem={vr.memory_bytes}B  "
              f"wall={wall*1000:.1f} ms")

    return report


def run_sample_time_screening(scenario_label: str = "lead_deceleration") -> FitnessReport:
    """
    Run sample-time degradation screening (reference dtype=float64).

    Tests Ts = 0.1, 0.2, 0.5 s.
    """
    print("\n--- Sample-time screening ---")

    t0 = _time.perf_counter()
    ref_sim = _run_simulation(dtype="float64", sample_time_s=0.1)
    ref_wall = _time.perf_counter() - t0
    ref_result = _evaluate_variant(ref_sim, ref_sim, "float64", 0.1, "Ts=0.10s (ref)", ref_wall)

    report = FitnessReport(scenario_label=scenario_label + "_Ts", reference=ref_result)

    for Ts in [0.2, 0.5]:
        t0 = _time.perf_counter()
        var_sim = _run_simulation(dtype="float64", sample_time_s=Ts)
        wall = _time.perf_counter() - t0
        label = f"Ts={Ts:.2f}s"
        vr = _evaluate_variant(var_sim, ref_sim, "float64", Ts, label, wall)
        report.variants.append(vr)
        status = "PASS" if (vr.passes_req001 and vr.passes_req002 and vr.passes_req004) else "FAIL"
        print(f"  [{status}]  {label:<12}  rms_spd={vr.rms_speed_error:.4f} m/s  "
              f"div_t={vr.divergence_time_s}  wall={wall*1000:.1f} ms")

    return report


def run_full_screening() -> tuple[FitnessReport, FitnessReport]:
    """Run both precision and sample-time screening. Returns (prec_report, ts_report)."""
    print("\n=== Option B: Target-Fitness Screening ===")
    prec_report = run_precision_screening()
    ts_report   = run_sample_time_screening()
    return prec_report, ts_report


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    prec, ts = run_full_screening()
    print(f"\nPrecision variants:   {len(prec.all_results())}")
    print(f"Sample-time variants: {len(ts.all_results())}")
