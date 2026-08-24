#!/usr/bin/env python3
"""Run the canonical musical-structure benchmark suite.

Usage (from audio2score-week4/backend):
  python -m benchmark.run_suite
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from benchmark.suite import passed, run_suite


def main() -> int:
    results = run_suite()
    print("Canonical pipeline benchmark")
    print("=" * 60)
    ok = True
    for r in results:
        status = "PASS" if passed(r) else "FAIL"
        if status == "FAIL":
            ok = False
        bits = [f"hands={r.hand_accuracy}", f"voices={r.voice_ok}", f"meter={r.meter_ok}", f"measures={r.measure_sum_ok}"]
        print(f"  [{status}] {r.name:24s} " + " ".join(bits))
    print("=" * 60)
    print("ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
