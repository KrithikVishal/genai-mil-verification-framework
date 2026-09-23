"""
precision_emulator.py
---------------------
Numeric precision helpers for Option B — Target-Fitness Screening.

Supported dtypes
----------------
  'float64'  — IEEE 754 double precision  (reference baseline)
  'float32'  — IEEE 754 single precision
  'fixed16'  — Emulated 16-bit signed fixed-point  (Q8.8 format)
  'fixed8'   — Emulated  8-bit signed fixed-point  (Q4.4 format)

The fixed-point emulation uses truncation (rounding toward zero) and
saturating arithmetic — matching the typical behaviour of automotive
embedded targets.
"""

from __future__ import annotations

import numpy as np
from typing import Union

Number = Union[float, int, np.floating]


# ---------------------------------------------------------------------------
# Fixed-point parameters
# ---------------------------------------------------------------------------

_FIXED_PARAMS: dict[str, dict] = {
    "fixed16": {
        "int_bits":  8,
        "frac_bits": 8,
        "n_bits":    16,
    },
    "fixed8": {
        "int_bits":  4,
        "frac_bits": 4,
        "n_bits":    8,
    },
}


def _to_fixed(value: float, n_bits: int, frac_bits: int) -> float:
    """
    Quantise `value` to an emulated signed fixed-point number.

    The integer representation uses (n_bits - frac_bits) integer bits and
    `frac_bits` fractional bits.  Saturating arithmetic is applied.

    Returns the quantised floating-point equivalent.
    """
    scale = 2 ** frac_bits
    # Maximum and minimum representable value
    max_val =  (2 ** (n_bits - 1) - 1) / scale
    min_val = -(2 ** (n_bits - 1))     / scale

    # Saturate then truncate (toward zero)
    clamped  = float(np.clip(value, min_val, max_val))
    quantised = int(clamped * scale) / scale   # truncation
    return float(quantised)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def to_dtype(value: Number, dtype: str) -> float:
    """
    Convert a scalar value to the specified numeric precision.

    Parameters
    ----------
    value : scalar numeric value
    dtype : one of 'float64', 'float32', 'fixed16', 'fixed8'

    Returns
    -------
    float — value after precision reduction
    """
    v = float(value)

    if dtype == "float64":
        return v

    if dtype == "float32":
        return float(np.float32(v))

    if dtype in _FIXED_PARAMS:
        p = _FIXED_PARAMS[dtype]
        return _to_fixed(v, p["n_bits"], p["frac_bits"])

    raise ValueError(f"Unknown dtype: {dtype!r}.  Choose from float64, float32, fixed16, fixed8.")


def array_to_dtype(arr: np.ndarray, dtype: str) -> np.ndarray:
    """
    Apply precision reduction to every element of a NumPy array.

    Parameters
    ----------
    arr   : 1-D or N-D float64 array
    dtype : target precision string

    Returns
    -------
    np.ndarray — same shape, values quantised
    """
    if dtype == "float64":
        return arr.astype(np.float64)

    if dtype == "float32":
        return arr.astype(np.float32).astype(np.float64)   # back to float64 for arithmetic

    if dtype in _FIXED_PARAMS:
        vfunc = np.vectorize(lambda x: _to_fixed(x, _FIXED_PARAMS[dtype]["n_bits"],
                                                   _FIXED_PARAMS[dtype]["frac_bits"]))
        return vfunc(arr)

    raise ValueError(f"Unknown dtype: {dtype!r}")


def dtype_resolution(dtype: str) -> float:
    """
    Return the smallest representable step (resolution) for a dtype.

    Useful for reporting fixed-point word-length effects.
    """
    if dtype == "float64":
        return float(np.finfo(np.float64).resolution)
    if dtype == "float32":
        return float(np.finfo(np.float32).resolution)
    if dtype in _FIXED_PARAMS:
        p = _FIXED_PARAMS[dtype]
        return 1.0 / (2 ** p["frac_bits"])
    raise ValueError(f"Unknown dtype: {dtype!r}")


def dtype_range(dtype: str) -> tuple[float, float]:
    """Return (min, max) representable value for a dtype."""
    if dtype == "float64":
        return (float(np.finfo(np.float64).min), float(np.finfo(np.float64).max))
    if dtype == "float32":
        return (float(np.finfo(np.float32).min), float(np.finfo(np.float32).max))
    if dtype in _FIXED_PARAMS:
        p = _FIXED_PARAMS[dtype]
        scale = 2 ** p["frac_bits"]
        return (-(2 ** (p["n_bits"] - 1)) / scale,
                 (2 ** (p["n_bits"] - 1) - 1) / scale)
    raise ValueError(f"Unknown dtype: {dtype!r}")


def static_memory_bytes(dtype: str, n_state_vars: int = 6) -> int:
    """
    Estimate controller static memory footprint in bytes.

    Parameters
    ----------
    dtype        : precision string
    n_state_vars : number of internal controller state variables
    """
    bits_map = {"float64": 64, "float32": 32, "fixed16": 16, "fixed8": 8}
    bits = bits_map.get(dtype, 64)
    return (bits // 8) * n_state_vars


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Precision Emulator — dtype summary")
    print("=" * 55)
    for d in ["float64", "float32", "fixed16", "fixed8"]:
        lo, hi = dtype_range(d)
        res     = dtype_resolution(d)
        mem     = static_memory_bytes(d)
        print(f"  {d:<10}  range=[{lo:>10.2f}, {hi:>10.2f}]  "
              f"res={res:.2e}  mem={mem} B")

    print("\nSample quantisation (value=3.14159):")
    for d in ["float64", "float32", "fixed16", "fixed8"]:
        q = to_dtype(3.14159, d)
        print(f"  {d:<10}  → {q}")
