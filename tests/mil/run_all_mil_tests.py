"""
run_all_mil_tests.py
--------------------
Runs all generated MIL test functions and prints a summary table.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.mil.test_acc_req_001 import run_acc_req_001
from tests.mil.test_acc_req_002 import run_acc_req_002
from tests.mil.test_acc_req_003 import run_acc_req_003
from tests.mil.test_acc_req_004 import run_acc_req_004
from tests.mil.test_acc_req_005 import run_acc_req_005


def run_all(dtype='float64'):
    results = []
    results.append(run_acc_req_001(dtype=dtype))
    results.append(run_acc_req_002(dtype=dtype))
    results.append(run_acc_req_003(dtype=dtype))
    results.append(run_acc_req_004(dtype=dtype))
    results.append(run_acc_req_005(dtype=dtype))
    return results


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--dtype', default='float64',
                    choices=['float64','float32','fixed16','fixed8'],
                    help='Numeric precision variant')
    args = ap.parse_args()

    print(f"\n=== MIL Test Suite  [dtype={args.dtype}] ===")
    results = run_all(dtype=args.dtype)
    print()
    print(f"{'Req ID':<15} {'Result':<8}  Details")
    print("-" * 70)
    passed_count = 0
    for r in results:
        status = 'PASS' if r['passed'] else 'FAIL'
        if r['passed']:
            passed_count += 1
        print(f"  {r['requirement_id']:<13} {status:<8}  {r.get('details','')}")
    print("-" * 70)
    print(f"  {passed_count}/{len(results)} passed\n")
