"""CLI for Checkpoint 9B evaluation alignment forensics.

Usage (from audio2score-week4/backend):

  python -m evaluation.alignment --split development
  python -m evaluation.alignment --case Case1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.alignment.analyze import (
    aggregate_tolerance_sweep,
    analyze_case,
    classify_corpus,
)
from evaluation.alignment.reports import build_markdown, write_report
from evaluation.corpus import PACKAGE_DIR, discover_cases
from evaluation.defaults import SPLITS

DIAG_ROOT = PACKAGE_DIR / "alignment_diagnostics"
EVAL_RESULTS = PACKAGE_DIR / "results"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "NotaScore Checkpoint 9B alignment forensics. "
            "Diagnostic only — does not change production transcription or tolerances."
        )
    )
    p.add_argument("--split", choices=SPLITS, default="development")
    p.add_argument("--case", default=None)
    p.add_argument("--run-id", default=None)
    p.add_argument("--out-dir", type=Path, default=DIAG_ROOT)
    p.add_argument(
        "--eval-results-root",
        type=Path,
        default=EVAL_RESULTS,
        help="Directory with existing evaluation runs containing transcription.mid",
    )
    p.add_argument("--corpus-root", type=Path, default=None)
    return p.parse_args(argv)


def _git_info() -> dict[str, str]:
    info = {"git_commit": "unknown", "git_branch": "unknown"}
    try:
        info["git_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=BACKEND_ROOT, text=True
        ).strip()
        info["git_branch"] = subprocess.check_output(
            ["git", "branch", "--show-current"], cwd=BACKEND_ROOT, text=True
        ).strip()
    except Exception:
        pass
    return info


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.corpus_root).resolve() if args.corpus_root else None
    cases = discover_cases(split=args.split, case_id=args.case, root=root)
    cases = [c for c in cases if not c.missing_audio() and not c.missing_raw_reference()]
    if not cases:
        print("[alignment] no runnable cases")
        return 1

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    eval_root = Path(args.eval_results_root)

    print(f"[alignment] run_id={run_id} cases={len(cases)}")
    payloads: list[dict] = []
    for case in cases:
        print(f"  {case.case_id} ...", flush=True)
        try:
            payload = analyze_case(
                case,
                out_dir=run_dir / case.case_id,
                eval_results_root=eval_root,
            )
        except FileNotFoundError as exc:
            print(f"    ERROR: {exc}")
            payloads.append(
                {"case_id": case.case_id, "status": "error", "reason": str(exc)}
            )
            continue
        payloads.append(payload)
        if payload.get("status") == "ok":
            b = payload["baseline_official_tolerance"]
            print(
                f"    baseline F1={b['onset_pitch_f1']:.3f} "
                f"best_off={payload['offset_search']['best_offset_ms']:.0f}ms "
                f"Δ={payload['offset_search']['delta_f1']:+.3f} "
                f"best_scale={payload['scale_search_first_onset_anchor']['best_scale']} "
                f"Δ={payload['scale_search_first_onset_anchor']['delta_f1']:+.3f} "
                f"hint={payload['case_root_cause_hint']}"
            )

    decision = classify_corpus(payloads)
    tol_agg = aggregate_tolerance_sweep(payloads)
    (run_dir / "tolerance_sweep.json").write_text(
        json.dumps({"aggregate": tol_agg, "per_case": {
            p["case_id"]: p.get("tolerance_sweep")
            for p in payloads if p.get("status") == "ok"
        }}, indent=2) + "\n",
        encoding="utf-8",
    )

    # Also mirror under evaluation/results for the requested path
    results_mirror = PACKAGE_DIR / "results" / run_id
    results_mirror.mkdir(parents=True, exist_ok=True)
    (results_mirror / "tolerance_sweep.json").write_text(
        (run_dir / "tolerance_sweep.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    git = _git_info()
    manifest = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "split": args.split,
        "cases": [c.case_id for c in cases],
        "decision": decision,
        "notes": [
            "Diagnostic only; production tolerances and transcription unchanged.",
            "Reused existing transcription.mid predictions when available.",
            "Note matching uses absolute seconds; no tempo correction applied.",
        ],
        **git,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "decision.json").write_text(
        json.dumps(decision, indent=2) + "\n", encoding="utf-8"
    )

    md = build_markdown(
        run_id=run_id,
        manifest=manifest,
        cases=payloads,
        decision=decision,
        tolerance_agg=tol_agg,
    )
    report_path = write_report(run_dir / "report.md", md)
    print(f"[alignment] decision={decision['decision']} {decision['label']}")
    print(f"[alignment] report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
