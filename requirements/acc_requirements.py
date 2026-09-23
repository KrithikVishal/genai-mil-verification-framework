"""
acc_requirements.py
-------------------
Formalised EARS (Easy Approach to Requirements Syntax) requirements for the
Adaptive Cruise Control (mpcACCsystem) controller, as specified in PoC-1.

Each requirement is stored as a dataclass so it can be imported by the
GenAI pipeline stages without re-parsing unstructured text.

EARS Syntax reminder
--------------------
  WHEN <optional trigger condition>,
  the <system name> shall <system response>.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class EARSRequirement:
    """One formalised EARS requirement."""
    id: str                        # e.g. "ACC-REQ-001"
    text: str                      # Full EARS sentence
    category: str                  # Functional bucket
    trigger: Optional[str]         # WHEN clause (None if unconditional)
    system_response: str           # Shall clause
    numeric_params: dict = field(default_factory=dict)   # Key constants


# ---------------------------------------------------------------------------
# ACC Requirements (verbatim from PoC-1, Section 4)
# ---------------------------------------------------------------------------

ACC_REQ_001 = EARSRequirement(
    id="ACC-REQ-001",
    text=(
        "WHEN the lead vehicle is absent or travelling faster than the set speed, "
        "the ACC system shall maintain ego-vehicle speed within ±0.5 m/s of the "
        "driver-set speed V_set in steady-state conditions (settled after 5 s)."
    ),
    category="speed_tracking",
    trigger="lead vehicle absent or V_lead > V_set",
    system_response="Maintain V_ego within ±0.5 m/s of V_set in steady state",
    numeric_params={
        "tolerance_mps": 0.5,
        "settling_time_s": 5.0,
    },
)

ACC_REQ_002 = EARSRequirement(
    id="ACC-REQ-002",
    text=(
        "WHEN a lead vehicle is present and D_actual < D_safe, "
        "the ACC system shall reduce ego-vehicle speed so that D_actual ≥ D_safe "
        "within 3 s of entering spacing-control mode."
    ),
    category="safe_distance",
    trigger="lead vehicle present AND D_actual < D_safe",
    system_response="Reduce speed so D_actual >= D_safe within 3 s",
    numeric_params={
        "recovery_time_s": 3.0,
    },
)

ACC_REQ_003 = EARSRequirement(
    id="ACC-REQ-003",
    text=(
        "The safe following distance shall be computed as "
        "D_safe = D_default + T_gap × V_ego, "
        "where D_default = 10 m and T_gap = 1.4 s."
    ),
    category="distance_formula",
    trigger=None,
    system_response="Compute D_safe = D_default + T_gap × V_ego",
    numeric_params={
        "D_default_m": 10.0,
        "T_gap_s":     1.4,
    },
)

ACC_REQ_004 = EARSRequirement(
    id="ACC-REQ-004",
    text=(
        "Ego acceleration shall be constrained to [−3, 2] m/s² at all times, "
        "regardless of controller mode or implementation."
    ),
    category="acceleration_bounds",
    trigger=None,
    system_response="Clamp a_cmd to [−3, 2] m/s² unconditionally",
    numeric_params={
        "a_min_mps2": -3.0,
        "a_max_mps2":  2.0,
    },
)

ACC_REQ_005 = EARSRequirement(
    id="ACC-REQ-005",
    text=(
        "WHEN a lead-vehicle deceleration event would breach D_safe, "
        "the system shall switch to spacing-control mode within one sample "
        "period (T_s = 0.1 s)."
    ),
    category="mode_switch",
    trigger="lead-vehicle deceleration event breaches D_safe",
    system_response="Switch to spacing-control mode within one sample period",
    numeric_params={
        "sample_time_s":       0.1,
        "max_switch_delay_s":  0.1,
    },
)

# ---------------------------------------------------------------------------
# Registry — ordered list for pipeline iteration
# ---------------------------------------------------------------------------

ALL_REQUIREMENTS: list[EARSRequirement] = [
    ACC_REQ_001,
    ACC_REQ_002,
    ACC_REQ_003,
    ACC_REQ_004,
    ACC_REQ_005,
]

REQUIREMENTS_BY_ID: dict[str, EARSRequirement] = {r.id: r for r in ALL_REQUIREMENTS}


if __name__ == "__main__":
    print("ACC Requirements Registry")
    print("=" * 60)
    for req in ALL_REQUIREMENTS:
        print(f"\n{req.id}  [{req.category}]")
        print(f"  {req.text[:100]}...")
        if req.numeric_params:
            print(f"  Params: {req.numeric_params}")
