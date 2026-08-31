"""Human-readable RAW → VALIDATED → STRUCTURED → QUANTIZED diffs.

Usage (from audio2score-week4/backend):

  python -m evaluation.stage_diff piano_quarters_120
  python -m evaluation.stage_diff --prepare-fixture
  python -m evaluation.stage_diff --split development
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.corpus import PACKAGE_DIR, discover_cases
from evaluation.execute import CaseResult, evaluate_case
from evaluation.fixture import prepare_fixture
from evaluation.preservation import (
    PreservationReport,
    QuantizationReport,
    stage_preservation_bundle,
)
from mir.pipeline import UnderstandingPipeline
from mir.types import TempoMap

RESULTS_ROOT = PACKAGE_DIR / "results"


def _rate(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def _ms(value: float) -> str:
    return f"{value:.1f}ms"


def format_preservation_block(
    title: str,
    report: PreservationReport | dict[str, Any],
    *,
    underline: str | None = None,
) -> str:
    data = report.to_dict() if isinstance(report, PreservationReport) else dict(report)
    bar = underline or ("-" * len(title))
    lines = [
        title,
        bar,
        f"notes: {data.get('raw_count')} → {data.get('later_count')}",
        f"deleted: {data.get('deleted_from_raw')}",
        f"added: {data.get('added_vs_raw')}",
        f"pitch changed: {data.get('pitch_changed_vs_raw')}",
        f"onset changed: {data.get('onset_changed_vs_raw')}",
        f"duration changed: {data.get('duration_changed_vs_raw')}",
        f"raw_event_preservation_rate: {_rate(float(data.get('raw_event_preservation_rate') or 0.0))}",
    ]
    return "\n".join(lines)


def format_quantization_block(report: QuantizationReport | dict[str, Any]) -> str:
    data = report.to_dict() if isinstance(report, QuantizationReport) else dict(report)
    warning = ""
    if data.get("count_drop_warning"):
        warning = (
            "\nWARNING: quantization dropped events "
            f"({data.get('source_event_count')} → {data.get('quantized_event_count')})"
        )
    lines = [
        "STRUCTURED → QUANTIZED",
        "----------------------",
        f"notes: {data.get('source_event_count')} → {data.get('quantized_event_count')}",
        f"timing changed: {data.get('events_moved')}",
        f"unchanged: {data.get('events_unchanged')}",
        f"mean onset shift: {_ms(float(data.get('average_onset_shift_ms') or 0.0))}",
        f"max onset shift: {_ms(float(data.get('max_onset_shift_ms') or 0.0))}",
        f"mean duration change: {_ms(float(data.get('average_duration_change_ms') or 0.0))}",
        f"notes added: {data.get('notes_added')}",
        f"notes deleted: {data.get('notes_deleted')}",
        f"percent events changed: {float(data.get('percent_events_changed') or 0.0):.1f}%",
    ]
    return "\n".join(lines) + warning


def format_stage_diff(
    bundle: dict[str, Any],
    *,
    f1_by_stage: dict[str, float] | None = None,
) -> str:
    blocks = [
        format_preservation_block("RAW → VALIDATED", bundle.get("raw_vs_validated") or {}),
        "",
        format_preservation_block(
            "VALIDATED → STRUCTURED",
            bundle.get("validated_vs_structured") or bundle.get("raw_vs_structured") or {},
        ),
        "",
        format_quantization_block(bundle.get("quantization") or {}),
    ]
    counts = [
        f"raw_note_count: {bundle.get('raw_note_count')}",
        f"validated_note_count: {bundle.get('validated_note_count')}",
        f"structured_note_count: {bundle.get('structured_note_count')}",
        f"quantized_note_count: {bundle.get('quantized_note_count')}",
    ]
    if f1_by_stage:
        counts.append("")
        for key in (
            "raw_vs_reference_F1",
            "validated_vs_reference_F1",
            "structured_vs_reference_F1",
            "quantized_vs_reference_F1",
        ):
            if key in f1_by_stage and f1_by_stage[key] is not None:
                counts.append(f"{key}: {float(f1_by_stage[key]):.3f}")
    return "\n".join(counts) + "\n\n" + "\n".join(blocks) + "\n"


def bundle_from_pipeline(
    pipe: UnderstandingPipeline,
    *,
    fallback_bpm: float = 120.0,
) -> dict[str, Any]:
    structure = pipe.last_structure
    tempo_map: TempoMap | None = structure.tempo_map if structure is not None else None
    bpm = fallback_bpm
    if tempo_map is not None:
        bpm = float(tempo_map.bpm_at(0.0) or fallback_bpm)
    return stage_preservation_bundle(
        raw_notes=pipe.last_raw_notes,
        validated_notes=pipe.last_validated_notes,
        structured_events=list(structure.events) if structure is not None else [],
        quantized_events=list(pipe.last_quantized_events or []),
        tempo_map=tempo_map,
        fallback_bpm=bpm,
    )


def f1_from_case_result(result: CaseResult) -> dict[str, float]:
    out: dict[str, float] = {}
    alias = {
        "transcription": "raw_vs_reference_F1",
        "post_cleaner": "validated_vs_reference_F1",
        "structured": "structured_vs_reference_F1",
        "quantized": "quantized_vs_reference_F1",
    }
    for stage in (result.stages or {}).get("stages") or []:
        name = stage.get("name")
        key = alias.get(name)
        if not key:
            continue
        metrics = stage.get("metrics") or {}
        f1 = metrics.get("onset_pitch_f1")
        if isinstance(f1, (int, float)):
            out[key] = float(f1)
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage-by-stage RAW preservation report for one evaluation case."
    )
    parser.add_argument(
        "case",
        nargs="?",
        default=None,
        help="Case id (searches evaluation splits unless --split is set)",
    )
    parser.add_argument("--split", default=None, help="Limit discovery to one split")
    parser.add_argument(
        "--prepare-fixture",
        action="store_true",
        help="Generate the repo-safe synthetic fixture, then diff it",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_ROOT,
        help="Where to write the evaluation run used for the diff",
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
        help="Override TRANSCRIPTION_VALIDATION_MODE for this run",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the preservation bundle as JSON instead of the text report",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.corpus_root).resolve() if args.corpus_root else None
    if args.prepare_fixture:
        prepare_fixture(root=root)
        case_id = args.case or "piano_quarters_120"
        split = args.split or "development"
    else:
        case_id = args.case
        split = args.split
    if not case_id:
        print("[stage_diff] pass a case id or --prepare-fixture", file=sys.stderr)
        return 2

    cases = discover_cases(split=split, case_id=case_id, root=root)
    if not cases:
        print(f"[stage_diff] case not found: {case_id}", file=sys.stderr)
        return 1
    case = cases[0]
    if case.missing_audio() or case.missing_reference():
        print(
            "[stage_diff] audio/reference pair missing for "
            f"{case.split}/{case.case_id}. Not fabricating results.",
            file=sys.stderr,
        )
        return 1

    from datetime import datetime, timezone

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.results_dir) / f"stage-diff-{run_id}" / case.case_id
    pipe = UnderstandingPipeline(mode="fast", validation_mode=args.validation_mode)
    result = evaluate_case(case, case_out_dir=out_dir, pipeline=pipe)
    if result.status != "ran":
        print(
            f"[stage_diff] case {case.case_id} status={result.status} "
            f"{result.skip_reason or result.error or ''}",
            file=sys.stderr,
        )
        return 1

    bundle = result.preservation or bundle_from_pipeline(pipe)
    f1 = f1_from_case_result(result)
    (out_dir / "stage_diff.txt").write_text(
        format_stage_diff(bundle, f1_by_stage=f1), encoding="utf-8"
    )
    (out_dir / "preservation.json").write_text(
        json.dumps(bundle, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if args.json:
        print(json.dumps({"preservation": bundle, "f1": f1}, indent=2, default=str))
    else:
        print(format_stage_diff(bundle, f1_by_stage=f1))
    print(f"[stage_diff] wrote {out_dir / 'stage_diff.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
