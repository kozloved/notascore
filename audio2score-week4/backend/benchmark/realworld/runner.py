"""Run a local real-world evaluation corpus.

Usage (from audio2score-week4/backend):

  python -m benchmark.realworld.runner --prepare-smoke
  python -m benchmark.realworld.runner --manifest benchmark/realworld/manifests/smoke.json
  python -m benchmark.realworld.runner --manifest path/to/my_manifest.json --local-root ~/notascore-realworld
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from benchmark.realworld.evaluate import evaluate_realworld_case
from benchmark.realworld.report import build_realworld_report, write_realworld_reports
from benchmark.realworld.schema import PACKAGE_DIR, load_manifest
from benchmark.realworld.smoke import prepare_smoke
from mir.pipeline import UnderstandingPipeline

RESULTS_DIR = BACKEND_ROOT / "benchmark" / "results" / "realworld"
REPO_ROOT = BACKEND_ROOT.parents[1]
DEFAULT_MANIFEST = PACKAGE_DIR / "manifests" / "smoke.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Observational real-world evaluation (local audio, not git-tracked)"
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="JSON manifest of cases (paths are relative to --local-root)",
    )
    parser.add_argument(
        "--local-root",
        type=Path,
        default=None,
        help="Directory that holds audio/MIDI. Default: NOTASCORE_REALWORLD_DIR or package local/",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
    )
    parser.add_argument(
        "--prepare-smoke",
        action="store_true",
        help="Generate the 3-case synthetic smoke files into the local root, then evaluate",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    local_root = Path(args.local_root).expanduser().resolve() if args.local_root else None
    if args.prepare_smoke:
        generated = prepare_smoke(local_root)
        print(f"[realworld] wrote smoke files via {generated}")
        if local_root is None:
            local_root = generated.parent

    cases, meta = load_manifest(args.manifest, local_root=local_root)
    if not cases:
        print("[realworld] manifest has no cases")
        return 1

    work_root = Path(args.results_dir) / "_work"
    pipeline = UnderstandingPipeline(mode="fast")
    rows = []
    print(f"[realworld] {len(cases)} cases from {meta['manifest_path']}")
    for case in cases:
        print(f"  {case.case_id} ...", flush=True)
        row = evaluate_realworld_case(case, work_root=work_root, pipeline=pipeline)
        extra = row.skip_reason or row.error or row.meter.get("predicted") or ""
        print(f"    {row.status} {extra}")
        rows.append(row.to_dict())

    report = build_realworld_report(cases=rows, repo=REPO_ROOT, manifest_meta=meta)
    paths = write_realworld_reports(report, Path(args.results_dir))
    for label, path in paths.items():
        print(f"Wrote {label}: {path}")
    print(
        f"realworld: ran {report['ran']}/{report['case_count']}, "
        f"skipped {report['skipped']}, errors {report['errors']}, "
        f"fallbacks {report['fallback_count']}"
    )
    return 0 if report["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
