"""CLI for Checkpoint 7 real-world audio evaluation.

Usage (from audio2score-week4/backend):

  python -m evaluation.runner --prepare-fixture
  python -m evaluation.runner --case piano_quarters_120
  python -m evaluation.runner --split development
  python -m evaluation.runner --split holdout
  python -m evaluation.runner --split real_world
  python -m evaluation.runner --all
  python -m evaluation.runner --split development --save-baseline checkpoint-7-baseline
  python -m evaluation.runner --split development --compare-baseline checkpoint-7-baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.baselines import compare_to_baseline, load_baseline, save_baseline
from evaluation.corpus import check_split_leakage, discover_cases, PACKAGE_DIR
from evaluation.defaults import SPLITS
from evaluation.execute import evaluate_case
from evaluation.fixture import prepare_fixture
from evaluation.gate import gate_decision
from evaluation.report import build_report, write_reports

REPO_ROOT = BACKEND_ROOT.parents[1]
RESULTS_ROOT = PACKAGE_DIR / "results"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "NotaScore real-world evaluation (Checkpoint 7). "
            "Measurement only — does not modify production algorithms."
        )
    )
    parser.add_argument(
        "--split",
        choices=SPLITS,
        default=None,
        help="Evaluate one corpus split",
    )
    parser.add_argument(
        "--case",
        default=None,
        help="Evaluate a single case id (searches all splits unless --split is set)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate development + holdout + real_world",
    )
    parser.add_argument(
        "--prepare-fixture",
        action="store_true",
        help="Generate the repo-safe synthetic development fixture, then evaluate it",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_ROOT,
        help="Root directory for run outputs",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run id (default: UTC timestamp)",
    )
    parser.add_argument(
        "--save-baseline",
        default=None,
        metavar="NAME",
        help="Save this run as a named baseline after evaluation",
    )
    parser.add_argument(
        "--compare-baseline",
        default=None,
        metavar="NAME",
        help="Compare this run against a named baseline",
    )
    parser.add_argument(
        "--baselines-dir",
        type=Path,
        default=None,
        help="Directory for baseline JSON files",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=None,
        help="Override evaluation package root (for tests)",
    )
    parser.add_argument(
        "--validation-mode",
        default=None,
        choices=("safe", "strict_safe", "conservative", "legacy_aggressive", "legacy"),
        help="Override TRANSCRIPTION_VALIDATION_MODE for this run (A/B)",
    )
    parser.add_argument(
        "--execution-path",
        choices=("isolated", "production"),
        default="production",
        help=(
            "isolated = UnderstandingPipeline per case (stage tests). "
            "production = engine.job_runner.run_job (application entry point)."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=("solo", "polyphonic", "fast", "quality"),
        default="solo",
        help="Requested transcription mode (solo/Basic Pitch or polyphonic/MT3)",
    )
    parser.add_argument(
        "--pipeline-mode",
        choices=("legacy", "shadow", "live"),
        default=None,
        help="NEXTGEN_PIPELINE_MODE for production-path runs",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Fail the process on regressions, errors, missing cases, or all-skipped",
    )
    parser.add_argument(
        "--allow-all-skipped",
        action="store_true",
        help="Do not fail when every case is skipped (default: fail)",
    )
    return parser.parse_args(argv)


def _select_cases(args: argparse.Namespace) -> tuple[list, str | None]:
    root = Path(args.corpus_root).resolve() if args.corpus_root else None
    if args.prepare_fixture:
        prepare_fixture(root=root)
        cases = discover_cases(
            split="development",
            case_id="piano_quarters_120",
            root=root,
        )
        return cases, "development"
    if args.case:
        cases = discover_cases(split=args.split, case_id=args.case, root=root)
        return cases, args.split
    if args.all:
        return discover_cases(root=root), "all"
    if args.split:
        return discover_cases(split=args.split, root=root), args.split
    # Default: development
    return discover_cases(split="development", root=root), "development"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cases, split_label = _select_cases(args)
    if not cases:
        print("[evaluation] no cases found")
        return 1

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results_root = Path(args.results_dir)
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Leakage check across the full corpus, not only the selected subset
    all_for_leak = discover_cases(root=Path(args.corpus_root).resolve() if args.corpus_root else None)
    leakage = check_split_leakage(all_for_leak)
    for warning in leakage:
        print(f"[evaluation] WARNING: {warning}")

    rows = []
    print(
        f"[evaluation] run_id={run_id} cases={len(cases)} split={split_label} "
        f"path={args.execution_path} mode={args.mode}"
    )
    for case in cases:
        print(f"  {case.split}/{case.case_id} ...", flush=True)
        case_out = run_dir / case.case_id
        row = evaluate_case(
            case,
            case_out_dir=case_out,
            pipeline=None,
            execution_path=args.execution_path,
            mode=args.mode,
            pipeline_mode_name=args.pipeline_mode,
            validation_mode=args.validation_mode,
        )
        extra = row.skip_reason or row.error or ""
        f1 = (row.notes or {}).get("onset_pitch_f1")
        f1_s = f"F1={f1:.3f}" if isinstance(f1, float) else ""
        print(f"    {row.status} {f1_s} {extra}".rstrip())
        rows.append(row.to_dict())

    baseline_comparison = None
    if args.compare_baseline:
        try:
            baseline = load_baseline(args.compare_baseline, root=args.baselines_dir)
        except FileNotFoundError as exc:
            print(f"[evaluation] baseline unreadable: {exc}")
            return 1
        baseline_comparison = compare_to_baseline(rows, baseline)
        print(
            "[evaluation] baseline comparison:",
            baseline_comparison["counts"],
            "delta=",
            (baseline_comparison.get("aggregate") or {}).get("delta"),
        )

    from modes import parse_transcription_mode

    try:
        canonical_mode = parse_transcription_mode(args.mode)
    except ValueError:
        canonical_mode = args.mode
    report = build_report(
        cases=rows,
        repo=REPO_ROOT,
        split=split_label,
        run_id=run_id,
        leakage_warnings=leakage,
        baseline_comparison=baseline_comparison,
        pipeline_config={
            "execution_path": args.execution_path,
            "requested_mode": args.mode,
            "canonical_mode": canonical_mode,
            "requested_pipeline_mode": args.pipeline_mode,
            "validation_mode": args.validation_mode,
            "independent_pipeline_per_case": True,
        },
    )
    paths = write_reports(report, run_dir)
    for label, path in paths.items():
        print(f"Wrote {label}: {path}")

    if args.save_baseline:
        bpath = save_baseline(report, args.save_baseline, root=args.baselines_dir)
        print(f"Saved baseline: {bpath}")

    enforce_baseline = bool(args.compare_baseline) or args.gate
    allow_all_skipped = bool(args.allow_all_skipped) and not args.gate
    decision = gate_decision(
        report,
        baseline_comparison,
        fail_on_regression=enforce_baseline,
        allow_all_skipped=allow_all_skipped,
    )
    (run_dir / "gate.json").write_text(
        json.dumps(decision, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"evaluation: ran {report['ran']}/{report['case_count']}, "
        f"skipped {report['skipped']}, errors {report['errors']}"
    )
    print(f"evaluation gate: {'pass' if decision['passed'] else 'fail'} {decision['reasons']}")
    return int(decision["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
