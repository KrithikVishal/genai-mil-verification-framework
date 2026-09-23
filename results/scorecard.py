"""
scorecard.py
------------
Target-Fitness Scorecard generator.

Reads FitnessReport objects from target_fitness_degrader.py and produces:
  1. A formatted text scorecard (results/scorecard.txt)
  2. A matplotlib PNG with two subplots:
       - Precision degradation: RMS speed error vs. dtype
       - Sample-time degradation: RMS speed error vs. Ts

The scorecard is the final deliverable of Option B (PoC-1).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.models.target_fitness_degrader import FitnessReport, VariantResult  # noqa: E402


# ---------------------------------------------------------------------------
# Text scorecard
# ---------------------------------------------------------------------------

_SEP  = "=" * 80
_SEP2 = "-" * 80

def _pass_fail(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def build_text_scorecard(
    prec_report: FitnessReport,
    ts_report:   FitnessReport,
    mil_results: list[dict] | None = None,
) -> str:
    """
    Build the full text scorecard string.

    Parameters
    ----------
    prec_report : precision degradation FitnessReport
    ts_report   : sample-time degradation FitnessReport
    mil_results : optional list of per-requirement MIL test results
    """
    lines: list[str] = []

    lines.append(_SEP)
    lines.append("TARGET-FITNESS SCORECARD — PoC-1 (MPC ACC Baseline)")
    lines.append("GenAI-Driven MIL Verification Framework  |  Option B: Shift-Left SIL")
    lines.append(_SEP)
    lines.append("")

    # ---- MIL test results ----
    if mil_results:
        lines.append("SECTION 1 — MIL TEST SUITE RESULTS  (float64 baseline)")
        lines.append(_SEP2)
        lines.append(f"  {'Req ID':<15} {'PASS/FAIL':<10}  Details")
        lines.append(_SEP2)
        total, passed = 0, 0
        for r in mil_results:
            total += 1
            if r.get("passed", False):
                passed += 1
            status = _pass_fail(r.get("passed", False))
            lines.append(f"  {r.get('requirement_id','?'):<15} {status:<10}  {r.get('details','')}")
        lines.append(_SEP2)
        lines.append(f"  Summary: {passed}/{total} requirements PASS at float64 baseline\n")

    # ---- Precision degradation ----
    lines.append("SECTION 2 — PRECISION DEGRADATION  (Ts = 0.10 s fixed)")
    lines.append(_SEP2)
    hdr = (f"  {'Variant':<14} {'RMS Spd Err':>12} {'Max Spd Err':>12} "
           f"{'RMS Dst Err':>12} {'Div@(s)':>10} "
           f"{'REQ-001':>8} {'REQ-002':>8} {'REQ-004':>8} {'Mem(B)':>7} {'Res':>10}")
    lines.append(hdr)
    lines.append(_SEP2)
    for vr in prec_report.all_results():
        div = f"{vr.divergence_time_s:.2f}" if vr.divergence_time_s is not None else "never"
        row = (f"  {vr.variant_label:<14} "
               f"{vr.rms_speed_error:>12.4f} {vr.max_speed_error:>12.4f} "
               f"{vr.rms_dist_error:>12.4f} {div:>10} "
               f"{_pass_fail(vr.passes_req001):>8} "
               f"{_pass_fail(vr.passes_req002):>8} "
               f"{_pass_fail(vr.passes_req004):>8} "
               f"{vr.memory_bytes:>7} "
               f"{vr.resolution:>10.2e}")
        lines.append(row)
    lines.append(_SEP2 + "\n")

    # ---- Sample-time degradation ----
    lines.append("SECTION 3 — SAMPLE-TIME DEGRADATION  (dtype = float64 fixed)")
    lines.append(_SEP2)
    lines.append(hdr)
    lines.append(_SEP2)
    for vr in ts_report.all_results():
        div = f"{vr.divergence_time_s:.2f}" if vr.divergence_time_s is not None else "never"
        row = (f"  {vr.variant_label:<14} "
               f"{vr.rms_speed_error:>12.4f} {vr.max_speed_error:>12.4f} "
               f"{vr.rms_dist_error:>12.4f} {div:>10} "
               f"{_pass_fail(vr.passes_req001):>8} "
               f"{_pass_fail(vr.passes_req002):>8} "
               f"{_pass_fail(vr.passes_req004):>8} "
               f"{vr.memory_bytes:>7} "
               f"{vr.resolution:>10.2e}")
        lines.append(row)
    lines.append(_SEP2 + "\n")

    # ---- Fitness verdict ----
    lines.append("SECTION 4 — TARGET-FITNESS VERDICT")
    lines.append(_SEP2)

    def _overall(vr: VariantResult) -> bool:
        return vr.passes_req001 and vr.passes_req002 and vr.passes_req004

    passed_prec = [vr for vr in prec_report.all_results() if _overall(vr)]
    failed_prec = [vr for vr in prec_report.all_results() if not _overall(vr)]

    lines.append(f"  Precision axis  → safe down to: "
                 f"{passed_prec[-1].variant_label if passed_prec else 'none'}")
    lines.append(f"  Precision axis  → fails at:     "
                 f"{failed_prec[0].variant_label if failed_prec else 'all pass'}")

    passed_ts = [vr for vr in ts_report.all_results() if _overall(vr)]
    failed_ts = [vr for vr in ts_report.all_results() if not _overall(vr)]
    lines.append(f"  Sample-time axis → safe up to:  "
                 f"{passed_ts[-1].variant_label if passed_ts else 'none'}")
    lines.append(f"  Sample-time axis → fails at:    "
                 f"{failed_ts[0].variant_label if failed_ts else 'all pass'}")

    lines.append("")
    lines.append("  Static memory footprint (6 state vars):")
    for vr in prec_report.all_results():
        lines.append(f"    {vr.dtype:<10} → {vr.memory_bytes} bytes")

    lines.append("")
    lines.append(_SEP)
    lines.append("End of Target-Fitness Scorecard")
    lines.append(_SEP)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------

def build_scorecard_plot(
    prec_report: FitnessReport,
    ts_report:   FitnessReport,
    output_path: Path,
) -> None:
    """Generate and save a 2-panel scorecard plot."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        print("  [scorecard] matplotlib not available — skipping plot.")
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle(
        "Target-Fitness Scorecard — ACC MPC PoC-1\nOption B: MIL-Stage Target-Fitness Screening",
        fontsize=13, fontweight="bold"
    )

    PASS_COLOR = "#2ecc71"
    FAIL_COLOR = "#e74c3c"
    REF_COLOR  = "#3498db"

    # --- Panel 1: Precision degradation ---
    ax = axes[0]
    vrs = prec_report.all_results()
    labels   = [vr.variant_label for vr in vrs]
    rms_vals = [vr.rms_speed_error for vr in vrs]
    colors   = []
    for i, vr in enumerate(vrs):
        if i == 0:
            colors.append(REF_COLOR)
        elif vr.passes_req001 and vr.passes_req002 and vr.passes_req004:
            colors.append(PASS_COLOR)
        else:
            colors.append(FAIL_COLOR)

    bars = ax.bar(labels, rms_vals, color=colors, edgecolor="white", linewidth=1.5)
    ax.axhline(0.5, color="orange", linestyle="--", linewidth=1.5, label="REQ-001 limit (0.5 m/s)")
    ax.set_title("Precision Degradation (Ts = 0.10 s)", fontsize=11)
    ax.set_xlabel("Numeric Precision Variant")
    ax.set_ylabel("RMS Speed Error vs. Reference (m/s)")
    ax.legend(fontsize=9)
    for bar, v in zip(bars, rms_vals):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                f"{v:.4f}", ha="center", va="bottom", fontsize=8)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.3)

    # --- Panel 2: Sample-time degradation ---
    ax = axes[1]
    vrs2     = ts_report.all_results()
    labels2  = [vr.variant_label for vr in vrs2]
    rms_vals2 = [vr.rms_speed_error for vr in vrs2]
    colors2  = []
    for i, vr in enumerate(vrs2):
        if i == 0:
            colors2.append(REF_COLOR)
        elif vr.passes_req001 and vr.passes_req002 and vr.passes_req004:
            colors2.append(PASS_COLOR)
        else:
            colors2.append(FAIL_COLOR)

    bars2 = ax.bar(labels2, rms_vals2, color=colors2, edgecolor="white", linewidth=1.5)
    ax.axhline(0.5, color="orange", linestyle="--", linewidth=1.5, label="REQ-001 limit (0.5 m/s)")
    ax.set_title("Sample-Time Degradation (dtype = float64)", fontsize=11)
    ax.set_xlabel("Sample Time Variant")
    ax.set_ylabel("RMS Speed Error vs. Reference (m/s)")
    ax.legend(fontsize=9)
    for bar, v in zip(bars2, rms_vals2):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                f"{v:.4f}", ha="center", va="bottom", fontsize=8)
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.3)

    # Legend patches
    legend_patches = [
        mpatches.Patch(color=REF_COLOR,  label="Reference (float64)"),
        mpatches.Patch(color=PASS_COLOR, label="PASS (all EARS reqs)"),
        mpatches.Patch(color=FAIL_COLOR, label="FAIL (at least one req)"),
    ]
    fig.legend(handles=legend_patches, loc="lower center", ncol=3, fontsize=9,
               bbox_to_anchor=(0.5, -0.02))

    plt.tight_layout(rect=[0, 0.04, 1, 1])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Scorecard plot saved: {output_path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Save text
# ---------------------------------------------------------------------------

def save_text_scorecard(text: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    print(f"  Scorecard text saved: {output_path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from src.models.target_fitness_degrader import run_full_screening
    prec, ts = run_full_screening()
    text = build_text_scorecard(prec, ts)
    print(text)
    save_text_scorecard(text, ROOT / "results" / "scorecard.txt")
    build_scorecard_plot(prec, ts, ROOT / "results" / "scorecard.png")
