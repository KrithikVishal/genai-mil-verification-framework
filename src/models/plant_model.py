"""
plant_model.py
--------------
Longitudinal vehicle plant model for MIL simulation.

Models two vehicles:
  Ego vehicle  — driven by the ACC controller's a_cmd
  Lead vehicle — follows a prescribed velocity profile (constant or deceleration)

Dynamics use Euler integration at the controller sample time.

The plant does NOT depend on numeric dtype — it is always run in float64 so
that it represents the "true" physical environment.  Only the controller
(acc_controller.py) has its precision varied during target-fitness screening.
"""

from __future__ import annotations

import numpy as np
from typing import Optional


class StepResult(dict):
    """Dict-compatible result that also allows tuple unpacking as (v_ego, x_ego, d_actual, v_lead)."""
    def __iter__(self):
        yield self["v_ego"]
        yield self["x_ego"]
        yield self["d_actual"]
        yield self["v_lead"]


class PlantModel:
    """
    Simple 1-D longitudinal dynamics for ego + lead vehicle pair.

    Parameters
    ----------
    sample_time_s : float
        Simulation step size (should match controller Ts).
    """

    def __init__(self, sample_time_s: float = 0.1) -> None:
        self.Ts = sample_time_s

        # Ego state
        self._v_ego: float = 0.0
        self._x_ego: float = 0.0

        # Lead state
        self._v_lead: float = np.inf   # inf = no lead vehicle
        self._x_lead: float = np.inf

        # Lead deceleration bookkeeping
        self._lead_decel: float = 0.0   # applied next step

    # ------------------------------------------------------------------
    # Initialise
    # ------------------------------------------------------------------

    def reset(
        self,
        v_ego_init: float = 0.0,
        d_init: float = 50.0,
        v_lead_init: float = np.inf,
        x_ego_init: float = 0.0,
    ) -> None:
        """
        Initialise plant state.

        Parameters
        ----------
        v_ego_init  : Initial ego speed (m/s)
        d_init      : Initial headway distance (m)
        v_lead_init : Initial lead speed (m/s); np.inf = free-driving (no lead)
        x_ego_init  : Initial ego longitudinal position (m)
        """
        self._v_ego   = float(v_ego_init)
        self._x_ego   = float(x_ego_init)
        self._v_lead  = float(v_lead_init)
        self._x_lead  = float(x_ego_init + d_init)
        self._lead_decel = 0.0

    # ------------------------------------------------------------------
    # Lead vehicle commands (called by scenario scripts)
    # ------------------------------------------------------------------

    def lead_decelerate(self, decel_mps2: float) -> None:
        """
        Apply a sustained deceleration to the lead vehicle.
        Call every step to maintain the deceleration.
        decel_mps2 should be negative (e.g. -3.0 for 3 m/s² braking).
        """
        self._lead_decel = float(decel_mps2)

    def lead_constant(self) -> None:
        """Set lead vehicle to hold current speed."""
        self._lead_decel = 0.0

    # ------------------------------------------------------------------
    # State accessor
    # ------------------------------------------------------------------

    def state(self) -> dict:
        """
        Return current plant state before the next integration step.

        Returns
        -------
        dict with keys: v_ego, x_ego, v_lead, x_lead, d_actual
        """
        if self._x_lead < 1e6:
            d_actual = max(0.0, self._x_lead - self._x_ego)
        else:
            d_actual = np.inf

        return {
            "v_ego":    self._v_ego,
            "x_ego":    self._x_ego,
            "v_lead":   self._v_lead,
            "x_lead":   self._x_lead,
            "d_actual": d_actual,
        }

    # Integration step
    # ------------------------------------------------------------------

    def step(self, a_cmd: float, v_lead: Optional[float] = None) -> StepResult:
        """
        Advance plant by one sample period using Euler integration.

        Parameters
        ----------
        a_cmd  : Acceleration command from controller (m/s²)
        v_lead : Optional updated lead vehicle speed (m/s)

        Returns
        -------
        StepResult dict (keys: v_ego, x_ego, v_lead, x_lead, d_actual; also unpackable as 4-tuple)
        """
        Ts = self.Ts

        if v_lead is not None:
            self._v_lead = float(v_lead)

        # --- Ego vehicle ---
        self._v_ego = max(0.0, self._v_ego + a_cmd * Ts)
        self._x_ego = self._x_ego + self._v_ego * Ts

        # --- Lead vehicle ---
        if self._v_lead < 1e6:
            new_v_lead = max(0.0, self._v_lead + self._lead_decel * Ts)
            self._x_lead = self._x_lead + self._v_lead * Ts
            self._v_lead = new_v_lead

        # Reset decel each step (caller must re-apply)
        self._lead_decel = 0.0

        return StepResult(self.state())
