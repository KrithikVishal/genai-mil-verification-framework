"""
signal_metrics.py
-----------------
Signal quality and oracle evaluation utilities.

Used by:
  - Generated MIL test functions (to evaluate PASS/FAIL)
  - target_fitness_degrader.py (back-to-back comparison)
  - scorecard.py (divergence detection)
"""

from __future__ import annotations

import numpy as np
from typing import Optional


# ---------------------------------------------------------------------------
# Basic metrics
# ---------------------------------------------------------------------------

def rms_error(signal: np.ndarray, reference: np.ndarray) -> float:
    """Root-mean-square error between signal and reference."""
    diff = np.asarray(signal, dtype=float) - np.asarray(reference, dtype=float)
    return float(np.sqrt(np.mean(diff ** 2)))


def max_abs_error(signal: np.ndarray, reference: np.ndarray) -> float:
    """Maximum absolute error between signal and reference."""
    diff = np.asarray(signal, dtype=float) - np.asarray(reference, dtype=float)
    return float(np.max(np.abs(diff)))


def settling_time(
    time: np.ndarray,
    signal: np.ndarray,
    target: float,
    tolerance: float,
    window_s: float = 1.0,
) -> Optional[float]:
    """
    Find the first time at which `signal` enters and stays within
    `target ± tolerance` for at least `window_s` seconds.

    Returns None if the signal never settles.
    """
    time   = np.asarray(time,   dtype=float)
    signal = np.asarray(signal, dtype=float)
    in_band = np.abs(signal - target) <= tolerance
    dt = float(time[1] - time[0]) if len(time) > 1 else 1.0
    win_steps = max(1, int(window_s / dt))

    for i in range(len(time) - win_steps):
        if np.all(in_band[i: i + win_steps]):
            return float(time[i])
    return None


def divergence_index(
    signal: np.ndarray,
    reference: np.ndarray,
    tolerance: float,
) -> Optional[int]:
    """
    Return the first sample index at which abs(signal - reference) > tolerance.
    Returns None if no divergence.
    """
    diff = np.abs(np.asarray(signal, dtype=float) - np.asarray(reference, dtype=float))
    indices = np.where(diff > tolerance)[0]
    return int(indices[0]) if len(indices) > 0 else None


# ---------------------------------------------------------------------------
# Oracle evaluator
# ---------------------------------------------------------------------------

def evaluate_oracle(oracle: dict, signals: dict[str, np.ndarray]) -> tuple[bool, str]:
    """
    Evaluate an oracle dict against a set of signal arrays.

    Parameters
    ----------
    oracle  : oracle sub-dict from a Test-Intent JSON
    signals : dict with keys 'time', 'v_ego', 'v_lead', 'd_actual',
              'a_cmd', 'mode', 'd_safe'  — all as np.ndarray

    Returns
    -------
    (passed: bool, details: str)
    """
    time = np.asarray(signals["time"], dtype=float)
    sig_name = oracle.get("signal", "v_ego")
    sig = np.asarray(signals[sig_name], dtype=float)

    # Restrict to evaluation window
    window = oracle.get("evaluation_window_s", [0.0, float(time[-1])])
    t_start, t_end = window[0], window[1]
    mask = (time >= t_start) & (time <= t_end)

    if not np.any(mask):
        return False, f"No samples in evaluation window [{t_start}, {t_end}] s"

    sig_win  = sig[mask]
    time_win = time[mask]

    oracle_type = oracle.get("type", "tolerance_band")

    # --- tolerance_band ---
    if oracle_type == "tolerance_band":
        tol = oracle.get("tolerance_mps", 0.5)
        ref_name = oracle.get("reference_signal", None)
        ref = (np.asarray(signals[ref_name], dtype=float)[mask]
               if ref_name and ref_name in signals else np.zeros_like(sig_win))
        err = np.max(np.abs(sig_win - ref))
        passed = bool(err <= tol)
        return passed, f"Max |err| = {err:.4f}  (limit ±{tol})"

    # --- lower_bound ---
    if oracle_type == "lower_bound":
        ref_name = oracle.get("reference_signal", None)
        if ref_name and ref_name in signals:
            ref_win = np.asarray(signals[ref_name], dtype=float)[mask]
            deficit = ref_win - sig_win
        else:
            min_val = oracle.get("min_value", 0.0)
            deficit = min_val - sig_win
        passed = bool(np.all(deficit <= 0))
        return passed, f"Max violation = {float(np.max(deficit)):.4f} m"

    # --- upper_bound ---
    if oracle_type == "upper_bound":
        max_val = oracle.get("max_value", np.inf)
        excess = sig_win - max_val
        passed = bool(np.all(excess <= 0))
        return passed, f"Max excess = {float(np.max(excess)):.4f}"

    # --- exact_bound (checks min AND max) ---
    if oracle_type == "exact_bound":
        results, msgs = [], []
        if "min_value" in oracle:
            v = oracle["min_value"]
            ok = bool(np.all(sig_win >= v))
            results.append(ok)
            msgs.append(f"min check {'OK' if ok else 'FAIL'} (min={sig_win.min():.4f} >= {v})")
        if "max_value" in oracle:
            v = oracle["max_value"]
            ok = bool(np.all(sig_win <= v))
            results.append(ok)
            msgs.append(f"max check {'OK' if ok else 'FAIL'} (max={sig_win.max():.4f} <= {v})")
        # Also handles formula verification (d_safe)
        ref_name = oracle.get("reference_signal", None)
        if ref_name and ref_name in signals:
            ref_win = np.asarray(signals[ref_name], dtype=float)[mask]
            err = max_abs_error(sig_win, ref_win)
            ok = err < 1e-9
            results.append(ok)
            msgs.append(f"formula error = {err:.2e}")
        passed = all(results) if results else True
        return passed, ";  ".join(msgs)

    # --- timing_constraint ---
    if oracle_type == "timing_constraint":
        tol_t = oracle.get("timing_tolerance_s", 0.1)
        # Find first switch in window
        mode_arr = np.asarray(signals.get("mode", sig), dtype=float)[mask]
        switch_idx = np.where(mode_arr == 1)[0]
        if len(switch_idx) == 0:
            return False, "Mode never switched to spacing control in window"
        switch_t  = float(time_win[switch_idx[0]])
        event_t   = float(t_start)
        delay     = switch_t - event_t
        passed    = bool(delay <= tol_t + 1e-9)
        return passed, f"Mode switch delay = {delay:.3f} s  (limit {tol_t} s)"

    return False, f"Unknown oracle type: {oracle_type}"


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Quick self-test
    t = np.linspace(0, 10, 100)
    v = np.ones(100) * 30.0 + np.random.normal(0, 0.1, 100)
    passed, msg = evaluate_oracle(
        {"type": "tolerance_band", "signal": "v_ego",
         "evaluation_window_s": [5.0, 10.0], "tolerance_mps": 0.5},
        {"time": t, "v_ego": v},
    )
    print(f"Self-test PASS={passed}: {msg}")
