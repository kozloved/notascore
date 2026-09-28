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
    inventory_markdown,
)


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
    args = parser.parse_args(argv)

    if not args.inventory and args.package is None and args.inventory_md is None:
        parser.print_help()
        return 2

    if args.inventory or args.inventory_md is not None:
        inv = asset_inventory()
        if args.inventory:
            print(json.dumps(inv, indent=2))
        if args.inventory_md is not None:
            args.inventory_md.parent.mkdir(parents=True, exist_ok=True)
            args.inventory_md.write_text(inventory_markdown(inv), encoding="utf-8")
            print(f"wrote {args.inventory_md}", file=sys.stderr)

    if args.package is not None:
        report = build_package(args.package, render=args.render)
        print(
            json.dumps(
                {
                    "out_dir": report["out_dir"],
                    "candidate_count": report["candidate_count"],
                    "musician_reviewed_complete": report["musician_reviewed_complete"],
                    "p1_complete": report["p1_complete"],
                    "package_report": str(Path(report["out_dir"]) / "package_report.md"),
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
