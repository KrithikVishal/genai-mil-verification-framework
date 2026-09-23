"""
acc_controller.py
-----------------
MPC-inspired Adaptive Cruise Control (ACC) controller.

This is a behaviourally-correct Python approximation of the MathWorks
mpcACCsystem controller described in PoC-1.  It implements two modes:

  Mode 0 — Speed Control  : when d_actual > d_safe or no lead vehicle
  Mode 1 — Spacing Control: when d_actual <= d_safe and lead vehicle present

The controller is intentionally written as a simple proportional + feedforward
law (not a full QP-based MPC) so it can be easily quantised and degraded for
Option B target-fitness screening.

The dtype parameter controls numeric precision, which is the key parameter
varied by target_fitness_degrader.py.

ACC-REQ compliance:
  - ACC-REQ-003: D_safe = 10 + 1.4 × V_ego  (D_default=10, T_gap=1.4)
  - ACC-REQ-004: a_cmd clamped to [-3, 2] m/s²
  - ACC-REQ-005: mode switches within one sample step
"""

from __future__ import annotations

import numpy as np
from typing import Tuple

from src.utils.precision_emulator import to_dtype


class ACCController:
    """
    MPC-inspired ACC controller.

    Parameters
    ----------
    sample_time_s : float
        Controller sample time in seconds (nominal 0.1 s).
    dtype : str
        Numeric precision: 'float64', 'float32', 'fixed16', 'fixed8'.
    kp_speed : float
        Proportional gain for speed-control mode.
    kp_spacing : float
        Proportional gain for spacing-control mode.
    kd_spacing : float
        Derivative (relative speed) gain for spacing-control mode.
    D_default : float
        Default minimum gap (m) — ACC-REQ-003.
    T_gap : float
        Time-gap headway (s) — ACC-REQ-003.
    a_min : float
        Minimum acceleration command (m/s²) — ACC-REQ-004.
    a_max : float
        Maximum acceleration command (m/s²) — ACC-REQ-004.
    """

    def __init__(
        self,
        sample_time_s: float = 0.1,
        dtype: str = "float64",
        kp_speed: float = 0.5,
        kp_spacing: float = 0.4,
        kd_spacing: float = 1.2,
        D_default: float = 10.0,
        T_gap: float = 1.4,
        a_min: float = -3.0,
        a_max: float = 2.0,
    ) -> None:
        self.Ts        = sample_time_s
        self.dtype     = dtype
        self.kp_speed  = kp_speed
        self.kp_space  = kp_spacing
        self.kd_space  = kd_spacing
        self.D_default = D_default
        self.T_gap     = T_gap
        self.a_min     = a_min
        self.a_max     = a_max

        # Internal state
        self._mode: int = 0           # 0=speed, 1=spacing
        self._prev_d_error: float = 0.0

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def d_safe(self, v_ego: float) -> float:
        """Compute safe following distance per ACC-REQ-003."""
        v = to_dtype(float(v_ego), self.dtype)
        return float(to_dtype(self.D_default + self.T_gap * v, self.dtype))

    def reset(self) -> None:
        """Reset internal state."""
        self._mode = 0
        self._prev_d_error = 0.0

    # ------------------------------------------------------------------
    # Step function
    # ------------------------------------------------------------------

    def step(
        self,
        v_ego: float,
        v_lead: float,
        d_actual: float,
        v_set: float,
    ) -> Tuple[float, int]:
        """
        One control step.

        Parameters
        ----------
        v_ego    : ego vehicle speed (m/s)
        v_lead   : lead vehicle speed (m/s); use np.inf if no lead vehicle
        d_actual : current headway distance (m); use np.inf if no lead vehicle
        v_set    : driver-set speed (m/s)

        Returns
        -------
        a_cmd : float  — acceleration command in m/s² (clamped)
        mode  : int    — 0=speed control, 1=spacing control
        """
        # Cast inputs to working dtype
        v_ego    = to_dtype(v_ego,    self.dtype)
        v_lead   = to_dtype(v_lead,   self.dtype)
        d_actual = to_dtype(d_actual, self.dtype)
        v_set    = to_dtype(v_set,    self.dtype)

        ds = to_dtype(self.d_safe(v_ego), self.dtype)

        # --- Control law & Mode selection (ACC-REQ-005: single-step switch) ---
        speed_error = to_dtype(v_set - v_ego, self.dtype)
        a_speed     = to_dtype(self.kp_speed * speed_error, self.dtype)

        lead_present = (d_actual < 1e6) and (v_lead < 1e6)
        if lead_present:
            d_error = to_dtype(d_actual - ds, self.dtype)
            delta_v = to_dtype(v_lead - v_ego, self.dtype)
            a_space = to_dtype(
                self.kp_space * d_error + self.kd_space * delta_v,
                self.dtype,
            )
            if (d_actual <= ds) or (a_space < a_speed):
                self._mode = 1   # spacing control
                a_cmd = a_space
            else:
                self._mode = 0   # speed control
                a_cmd = a_speed
            self._prev_d_error = d_error
        else:
            self._mode = 0       # speed control
            a_cmd = a_speed

        # --- Actuator saturation (ACC-REQ-004) ---
        a_cmd = float(np.clip(to_dtype(a_cmd, self.dtype), self.a_min, self.a_max))

        return a_cmd, self._mode
