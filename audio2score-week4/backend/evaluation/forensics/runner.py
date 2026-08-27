"""CLI for Checkpoint 8 transcription forensics.

Usage (from audio2score-week4/backend):

  python -m evaluation.forensics --split development
  python -m evaluation.forensics --case Case1
  python -m evaluation.forensics --split development --skip-eval  # reuse existing run dir
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.corpus import discover_cases, PACKAGE_DIR
from evaluation.defaults import SPLITS
from evaluation.execute import evaluate_case
from evaluation.forensics.analyze import analyze_case, analyze_corpus
from evaluation.forensics.report import write_forensics_report
from mir.pipeline import UnderstandingPipeline

RESULTS_ROOT = PACKAGE_DIR / "results"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "NotaScore Checkpoint 8 transcription forensics. "
            "Read-only diagnostics — does not modify production algorithms."
        )
    )
    p.add_argument("--split", choices=SPLITS, default="development")
    p.add_argument("--case", default=None)
    p.add_argument("--results-dir", type=Path, default=RESULTS_ROOT)
    p.add_argument("--run-id", default=None)
    p.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip pipeline re-run; analyze an existing --run-id directory",
    )
    p.add_argument("--corpus-root", type=Path, default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.corpus_root).resolve() if args.corpus_root else None
    cases = discover_cases(split=args.split, case_id=args.case, root=root)
    if not cases:
        print("[forensics] no cases found")
        return 1

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.results_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    pipeline = None if args.skip_eval else UnderstandingPipeline(mode="fast")
    payloads: list[dict] = []
    print(f"[forensics] run_id={run_id} cases={len(cases)} skip_eval={args.skip_eval}")

    for case in cases:
        case_out = run_dir / case.case_id
        print(f"  {case.split}/{case.case_id} ...", flush=True)
        if not args.skip_eval:
            assert pipeline is not None
            row = evaluate_case(case, case_out_dir=case_out, pipeline=pipeline)
            if row.status != "ran":
                print(f"    eval {row.status}: {row.skip_reason or row.error}")
                payloads.append(
                    {
                        "case_id": case.case_id,
                        "status": row.status,
                        "reason": row.skip_reason or row.error,
                    }
                )
                continue
            predicted_tempo = (row.tempo or {}).get("predicted_bpm")
            expected_tempo = (row.tempo or {}).get("reference_bpm")
        else:
            metrics_path = case_out / "metrics.json"
            if not metrics_path.is_file():
                print(f"    missing metrics.json under {case_out}")
                payloads.append(
                    {
                        "case_id": case.case_id,
                        "status": "skipped",
                        "reason": "missing prior evaluation metrics",
                    }
                )
                continue
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            predicted_tempo = (metrics.get("tempo") or {}).get("predicted_bpm")
            expected_tempo = (metrics.get("tempo") or {}).get("reference_bpm")

        forensic = analyze_case(
            case_id=case.case_id,
            case_out_dir=case_out,
            reference_raw_path=case.reference_raw_midi or case.reference_midi,
            predicted_tempo=predicted_tempo,
            expected_tempo=expected_tempo,
        )
        fail = (forensic.get("first_stage_of_failure") or {}).get(
            "primary_failure_stage"
        )
        f1 = (
            ((forensic.get("stages") or {}).get("transcription") or {}).get("match")
            or {}
        ).get("onset_pitch_f1")
        f1_s = f"F1={f1:.3f}" if isinstance(f1, float) else ""
        print(f"    forensics {forensic.get('status')} {f1_s} fail@{fail}")
        payloads.append(forensic)

    aggregate = analyze_corpus(payloads)
    (run_dir / "forensics_aggregate.json").write_text(
        json.dumps(aggregate, indent=2, default=str) + "\n", encoding="utf-8"
    )
    report_path = write_forensics_report(aggregate, payloads, run_dir)
    print(f"Wrote aggregate: {run_dir / 'forensics_aggregate.json'}")
    print(f"Wrote report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
