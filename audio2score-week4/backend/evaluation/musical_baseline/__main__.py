"""CLI for P1 musical baseline inventory and review package."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evaluation.musical_baseline.catalog import asset_inventory
from evaluation.musical_baseline.package import (
    DEFAULT_OUT,
    build_package,
    export_portable_bundle,
    inventory_markdown,
    report_reviews,
    write_first_session_guide,
    write_review_index,
)
from evaluation.musical_baseline.real_samples import import_real_job_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="Print asset inventory JSON (and optional markdown path)",
    )
    parser.add_argument(
        "--inventory-md",
        type=Path,
        default=None,
        help="Write inventory markdown to this path",
    )
    parser.add_argument(
        "--package",
        type=Path,
        nargs="?",
        const=DEFAULT_OUT,
        default=None,
        help="Build the review package under this directory",
    )
    parser.add_argument(
        "--render",
        action="store_true",
        help="Also attempt OSMD HTML/PNG renders when packaging",
    )
    parser.add_argument(
        "--report-reviews",
        type=Path,
        nargs="?",
        const=DEFAULT_OUT,
        default=None,
        help=(
            "Validate/summarize existing reviews without rebuilding scores "
            "or modifying human-owned review files (includes real_samples/)"
        ),
    )
    parser.add_argument(
        "--write-index",
        type=Path,
        nargs="?",
        const=DEFAULT_OUT,
        default=None,
        help="Write REVIEW_INDEX.html + FIRST_SESSION.md for an existing package",
    )
    parser.add_argument(
        "--bundle",
        type=Path,
        nargs="?",
        const=DEFAULT_OUT,
        default=None,
        help=(
            "Export a portable .tar.gz including MIDI and OSMD renders "
            "(normally gitignored) under evaluation/musical_baseline/handoff/"
        ),
    )
    parser.add_argument(
        "--engine-commit",
        default=None,
        help="Optional git commit recorded in the portable handoff / import",
    )
    parser.add_argument(
        "--import-real-job",
        type=Path,
        default=None,
        help=(
            "Import an already-downloaded job bundle into package real_samples/ "
            "(requires --job-id). Does not access production."
        ),
    )
    parser.add_argument(
        "--job-id",
        default=None,
        help="Job ID for --import-real-job",
    )
    parser.add_argument(
        "--example-id",
        default=None,
        help="Optional example_id for --import-real-job (default real-job-<job-id>)",
    )
    parser.add_argument(
        "--algorithm-version",
        default=None,
        help="Optional algorithm version evidence for --import-real-job",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Optional transcription provider evidence for --import-real-job",
    )
    parser.add_argument(
        "--permitted-use",
        default=None,
        help="Optional permitted-use note for --import-real-job",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional title for --import-real-job",
    )
    parser.add_argument(
        "--force-import",
        action="store_true",
        help="Allow re-import into an existing real_samples case directory",
    )
    args = parser.parse_args(argv)

    if (
        not args.inventory
        and args.package is None
        and args.inventory_md is None
        and args.report_reviews is None
        and args.write_index is None
        and args.bundle is None
        and args.import_real_job is None
    ):
        parser.print_help()
        return 2

    if args.import_real_job is not None:
        if not args.job_id:
            parser.error("--import-real-job requires --job-id")
        package_dir = args.package if args.package is not None else DEFAULT_OUT
        result = import_real_job_bundle(
            args.import_real_job,
            package_dir=package_dir,
            job_id=args.job_id,
            example_id=args.example_id,
            engine_commit=args.engine_commit,
            algorithm_version=args.algorithm_version,
            provider=args.provider,
            permitted_use=args.permitted_use,
            title=args.title,
            force=args.force_import,
        )
        print(json.dumps(result, indent=2, default=str))

    if args.inventory or args.inventory_md is not None:
        inv = asset_inventory()
        if args.inventory:
            print(json.dumps(inv, indent=2))
        if args.inventory_md is not None:
            args.inventory_md.parent.mkdir(parents=True, exist_ok=True)
            args.inventory_md.write_text(inventory_markdown(inv), encoding="utf-8")
            print(f"wrote {args.inventory_md}", file=sys.stderr)

    if args.package is not None and args.import_real_job is None:
        report = build_package(args.package, render=args.render)
        print(
            json.dumps(
                {
                    "out_dir": report["out_dir"],
                    "mode": report.get("mode"),
                    "candidate_count": report["candidate_count"],
                    "musician_reviewed_complete": report["musician_reviewed_complete"],
                    "musically_accepted_count": report.get("musically_accepted_count"),
                    "p1_complete": report["p1_complete"],
                    "package_report": str(Path(report["out_dir"]) / "package_report.md"),
                },
                indent=2,
            )
        )

    if args.report_reviews is not None:
        report = report_reviews(args.report_reviews)
        real = report.get("real_samples") or {}
        print(
            json.dumps(
                {
                    "out_dir": report["out_dir"],
                    "mode": report.get("mode"),
                    "musician_reviewed_complete": report["musician_reviewed_complete"],
                    "musically_accepted_count": report.get("musically_accepted_count"),
                    "reviewed_but_not_accepted_count": report.get(
                        "reviewed_but_not_accepted_count"
                    ),
                    "stale_count": (report.get("review_summary") or {}).get(
                        "stale_count"
                    ),
                    "p1_complete": report["p1_complete"],
                    "real_samples": {
                        "count": real.get("count"),
                        "musician_reviewed_complete": real.get(
                            "musician_reviewed_complete"
                        ),
                        "stale_count": real.get("stale_count"),
                    },
                    "package_report": str(Path(report["out_dir"]) / "package_report.md"),
                },
                indent=2,
            )
        )

    if args.write_index is not None:
        index = write_review_index(args.write_index)
        guide = write_first_session_guide(args.write_index)
        print(
            json.dumps(
                {"review_index": str(index), "first_session": str(guide)},
                indent=2,
            )
        )

    if args.bundle is not None:
        archive = export_portable_bundle(
            args.bundle, engine_commit=args.engine_commit
        )
        print(json.dumps({"bundle": str(archive)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
