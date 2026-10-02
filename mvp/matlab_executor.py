"""
mvp/matlab_executor.py
----------------------
Phase 3 of the MVP loop: Execute a validated Test Intent in MATLAB.

This is the ONLY module that talks to MATLAB.  It:
  1. Serializes the Test Intent to a temp JSON file.
  2. Invokes MATLAB R2024a in batch mode, calling mvp_run_test.m.
  3. Reads the Execution Result JSON that MATLAB writes back.
  4. Returns the result as a Python dict.

Python = AI Brain.  MATLAB = Simulation Engine.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

ROOT     = Path(__file__).resolve().parents[1]
MATLAB_RUNNER_DIR = ROOT / "mvp" / "matlab_runner"
MATLAB_EXE = Path(r"C:\Program Files\MATLAB\R2024a\bin\matlab.exe")
DEFAULT_TIMEOUT = 120   # seconds per simulation run


def _find_matlab() -> Path:
    """Locate MATLAB executable; search PATH if default location missing."""
    if MATLAB_EXE.exists():
        return MATLAB_EXE
    # Try to find in PATH
    import shutil
    found = shutil.which("matlab")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "MATLAB executable not found. "
        f"Expected: {MATLAB_EXE}\n"
        "Set MATLAB_EXE env var or ensure matlab is on PATH."
    )


def run_test_in_matlab(
    intent: dict,
    timeout: int = DEFAULT_TIMEOUT,
    artifacts_dir: Optional[Path] = None,
) -> dict:
    """
    Execute a Test Intent in MATLAB and return the Execution Result dict.

    Parameters
    ----------
    intent        : Validated Test Intent (from test_generator.py).
    timeout       : MATLAB subprocess timeout in seconds.
    artifacts_dir : Directory to persist intent/result JSON files.
                    If None, uses a temporary directory.

    Returns
    -------
    Execution Result dict conforming to execution_result_schema.json.
    """
    run_uid = str(uuid.uuid4())[:8]
    test_id = intent.get("test_id", f"UNKNOWN-{run_uid}")

    # Determine where to write artefact files
    if artifacts_dir is None:
        art_dir = Path(tempfile.mkdtemp(prefix="mvp_run_"))
    else:
        art_dir = Path(artifacts_dir)
        art_dir.mkdir(parents=True, exist_ok=True)

    intent_path = art_dir / f"{test_id}_intent.json"
    result_path = art_dir / f"{test_id}_result.json"

    # Write intent so MATLAB can read it
    with open(intent_path, "w") as f:
        json.dump(intent, f, indent=2)

    matlab_exe = _find_matlab()

    # Build the MATLAB command:
    # Add the matlab_runner dir to path, then call mvp_run_test
    intent_posix = str(intent_path).replace("\\", "/")
    result_posix = str(result_path).replace("\\", "/")
    runner_posix = str(MATLAB_RUNNER_DIR).replace("\\", "/")
    src_matlab_posix = str(ROOT / "src" / "matlab").replace("\\", "/")

    matlab_cmd = (
        f"addpath('{runner_posix}');"
        f"addpath('{src_matlab_posix}');"
        f"try,"
        f"  mvp_run_test('{intent_posix}', '{result_posix}');"
        f"catch ex,"
        f"  fid = fopen('{result_posix}', 'w');"
        f"  err_struct = struct("
        f"    'test_id', '{test_id}',"
        f"    'run_id', 'RUN-ERROR',"
        f"    'requirement_id', '{intent.get('requirement_id', 'UNKNOWN')}',"
        f"    'execution_status', 'runtime_error',"
        f"    'requirement_verdict', 'ERROR',"
        f"    'measured_metrics', struct(),"
        f"    'warnings', {{}},"
        f"    'errors', {{ex.message}},"
        f"    'model_info', struct(),"
        f"    'budget_used', struct('wall_time_s', 0, 'iteration', {intent.get('iteration', 1)})"
        f"  );"
        f"  fprintf(fid, '%s', jsonencode(err_struct));"
        f"  fclose(fid);"
        f"end;"
        f"exit;"
    )

    cmd = [
        str(matlab_exe),
        "-batch",
        matlab_cmd,
    ]

    print(f"  [MATLAB] Launching simulation for {test_id} …")
    t0 = time.time()

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
    except subprocess.TimeoutExpired:
        return {
            "test_id": test_id,
            "run_id": f"RUN-TIMEOUT-{run_uid}",
            "requirement_id": intent.get("requirement_id", "UNKNOWN"),
            "execution_status": "timeout",
            "requirement_verdict": "ERROR",
            "measured_metrics": {},
            "warnings": [f"MATLAB subprocess timed out after {timeout}s"],
            "errors": [],
            "model_info": {},
            "budget_used": {"wall_time_s": time.time() - t0, "iteration": intent.get("iteration", 1)},
        }

    wall_s = time.time() - t0

    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(f"  [MATLAB STDERR] {proc.stderr[:400].rstrip()}")

    # Read result JSON written by MATLAB
    if not result_path.exists():
        return {
            "test_id": test_id,
            "run_id": f"RUN-NORESULT-{run_uid}",
            "requirement_id": intent.get("requirement_id", "UNKNOWN"),
            "execution_status": "runtime_error",
            "requirement_verdict": "ERROR",
            "measured_metrics": {},
            "warnings": [],
            "errors": [
                f"MATLAB exited (rc={proc.returncode}) but wrote no result file.",
                proc.stderr[:600] if proc.stderr else "",
            ],
            "model_info": {},
            "budget_used": {"wall_time_s": wall_s, "iteration": intent.get("iteration", 1)},
        }

    with open(result_path) as f:
        result = json.load(f)

    result["budget_used"]["wall_time_s"] = wall_s
    print(f"  [MATLAB] Done in {wall_s:.1f}s  verdict={result.get('requirement_verdict', '?')}")
    return result
