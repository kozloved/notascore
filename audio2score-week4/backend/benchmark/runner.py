#!/usr/bin/env python3
"""NotaScore complete-pipeline benchmark.

Usage (from audio2score-week4/backend):

  python -m benchmark.runner --mode midi
  python -m benchmark.runner --mode midi --subset ci
  python -m benchmark.runner --mode solo
  python -m benchmark.runner --mode polyphonic
  python -m benchmark.runner --mode midi --save-baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from benchmark.evaluate import MODE_LABELS, evaluate_case
from benchmark.fixtures.generate import write_corpus
from benchmark.load import filter_cases, load_cases
from benchmark.report import build_report, load_json, write_reports

RESULTS_DIR = BACKEND_ROOT / "benchmark" / "results"
REPO_ROOT = BACKEND_ROOT.parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NotaScore pipeline benchmark")
    parser.add_argument(
        "--mode",
        choices=("midi", "solo", "polyphonic", "fast", "quality", "all"),
        default="midi",
        help="midi = ingest fixtures; solo/fast = Basic Pitch; polyphonic/quality = MT3 if configured",
    )
    parser.add_argument(
        "--subset",
        choices=("all", "ci"),
        default="all",
        help="ci = synthetic MIDI / notation / hands / voices / rhythm gate",
    )
    parser.add_argument("--save-baseline", action="store_true")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=RESULTS_DIR / "baseline.json",
        help="Previous baseline JSON for regression comparison",
    )
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    return parser.parse_args(argv)


def run_mode(mode: str, subset: str, results_dir: Path) -> list[dict]:
    write_corpus()
    cases = filter_cases(load_cases(), subset=subset)
    if not cases:
        raise SystemExit("No benchmark cases found. Run fixtures.generate first.")
    work_root = results_dir / "_work"
    rows = []
    label = MODE_LABELS.get(mode, mode)
    print(f"[{label}] {len(cases)} cases (subset={subset})")
    for case in cases:
        print(f"  {case.category}/{case.case_id} ...", flush=True)
        row = evaluate_case(case, mode=mode, work_root=work_root)
        status = "SKIP" if row.skipped else ("PASS" if row.passed else "FAIL")
        extra = row.skip_reason or ",".join(row.flags)
        print(f"    {status} {extra}")
        rows.append(row.to_dict())
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    baseline = load_json(Path(args.baseline)) if args.mode != "all" else None

    if args.mode == "all":
        extra = []
        primary_rows = []
        primary_mode = "midi"
        for mode in ("midi", "solo", "polyphonic"):
            rows = run_mode(mode, args.subset, results_dir)
            report = build_report(
                mode=mode,
                cases=rows,
                repo=REPO_ROOT,
                baseline=load_json(Path(args.baseline)) if mode == "midi" else None,
            )
            extra.append(
                {
                    "mode": mode,
                    "mode_label": MODE_LABELS[mode],
                    "case_count": report["case_count"],
                    "passed": report["passed"],
                    "failed": report["failed"],
                    "skipped": report["skipped"],
                    "ok": report["ok"],
                }
            )
            if mode == primary_mode:
                primary_rows = rows
        report = build_report(
            mode=primary_mode,
            cases=primary_rows,
            repo=REPO_ROOT,
            baseline=load_json(Path(args.baseline)),
            extra_modes=extra,
        )
    else:
        rows = run_mode(args.mode, args.subset, results_dir)
        report = build_report(
            mode=args.mode,
            cases=rows,
            repo=REPO_ROOT,
            baseline=baseline,
        )

    json_path, md_path = write_reports(report, results_dir)
    if args.save_baseline:
        baseline_path = results_dir / "baseline.json"
        baseline_path.write_text(
            json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print(f"Wrote baseline {baseline_path}")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(
        f"{report['mode_label']}: "
        f"{report['passed']}/{report['case_count']} passed, "
        f"{report['fallback_count']} fallbacks, "
        f"{len(report['regressions'])} regressions"
    )
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
