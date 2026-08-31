"""A/B comparison of cleaner / pipeline validation modes.

Variants (Checkpoint MVP):

    A = legacy_aggressive cleaner (historical production)
    B = strict_safe validation
    C = conservative cleanup
    D = B + Gemini (skipped unless Gemini is configured)

Primary comparison is note-level F1 vs a reference (or vs variant A when
no reference exists). Do not declare a winner without numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mir.midi_cleaner import MIDICleaner
from mir.pipeline_config import ValidationMode
from mir.types import NoteEvent


VARIANTS = {
    "A": {
        "label": "current (legacy_aggressive)",
        "validation_mode": ValidationMode.LEGACY_AGGRESSIVE,
        "gemini": False,
    },
    "B": {
        "label": "raw → safe validation → notation",
        "validation_mode": ValidationMode.STRICT_SAFE,
        "gemini": False,
    },
    "C": {
        "label": "raw → conservative cleanup → notation",
        "validation_mode": ValidationMode.CONSERVATIVE,
        "gemini": False,
    },
    "D": {
        "label": "B + Gemini",
        "validation_mode": ValidationMode.STRICT_SAFE,
        "gemini": True,
    },
}


@dataclass
class VariantResult:
    key: str
    label: str
    note_count: int
    suppressed: int
    observed: int
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "note_count": self.note_count,
            "suppressed": self.suppressed,
            "observed": self.observed,
            "extra": self.extra,
        }


def compare_cleaner_variants(notes: list[NoteEvent]) -> dict[str, VariantResult]:
    """Run A/B/C of MIDICleaner on the same raw notes (no Gemini, no audio)."""
    from mir.models import CleaningAction

    results: dict[str, VariantResult] = {}
    for key in ("A", "B", "C"):
        spec = VARIANTS[key]
        cleaner = MIDICleaner(mode=spec["validation_mode"])
        cleaned, report = cleaner.clean_with_report(notes)
        suppressed = sum(1 for d in report if d.action == CleaningAction.SUPPRESS)
        observed = sum(
            1
            for d in report
            if d.action != CleaningAction.SUPPRESS and d.evidence.get("applied") is False
        )
        results[key] = VariantResult(
            key=key,
            label=str(spec["label"]),
            note_count=len(cleaned),
            suppressed=suppressed,
            observed=observed,
            extra={"mode": spec["validation_mode"].value},
        )
    return results


def write_ab_report(results: dict[str, VariantResult], path: Path) -> Path:
    payload = {k: v.to_dict() for k, v in results.items()}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _cleaner_fixture_rows() -> list[dict[str, Any]]:
    from benchmark.fixtures import ALL_CLEANER_FIXTURES, notes_from_dicts
    from mir.types import NoteEvent

    extra_cases = [
        {
            "name": "legitimate_octave",
            "raw": [
                NoteEvent(pitch=48, start_time=0.0, end_time=1.0, velocity=80, confidence=0.85),
                NoteEvent(pitch=60, start_time=0.0, end_time=1.0, velocity=78, confidence=0.82),
            ],
        },
        {
            "name": "quiet_octave",
            "raw": [
                NoteEvent(pitch=48, start_time=0.0, end_time=1.0, velocity=80, confidence=0.9),
                NoteEvent(pitch=60, start_time=0.01, end_time=1.0, velocity=28, confidence=0.4),
            ],
        },
        {
            "name": "grace_note",
            "raw": [
                NoteEvent(pitch=71, start_time=0.0, end_time=0.03, velocity=88, confidence=0.8),
                NoteEvent(pitch=72, start_time=0.10, end_time=0.50, velocity=80, confidence=0.9),
            ],
        },
        {
            "name": "repeated_notes",
            "raw": [
                NoteEvent(pitch=60, start_time=0.0, end_time=0.20, velocity=80),
                NoteEvent(pitch=60, start_time=0.22, end_time=0.42, velocity=80),
            ],
        },
        {
            "name": "dense_chord",
            "raw": [
                NoteEvent(pitch=60, start_time=0.500, end_time=1.0, velocity=80),
                NoteEvent(pitch=64, start_time=0.512, end_time=1.0, velocity=75),
                NoteEvent(pitch=67, start_time=0.525, end_time=1.0, velocity=70),
                NoteEvent(pitch=71, start_time=0.530, end_time=1.0, velocity=68),
            ],
        },
        {
            "name": "expressive_timing",
            "raw": [
                NoteEvent(pitch=60, start_time=0.103, end_time=0.410, velocity=80),
                NoteEvent(pitch=64, start_time=0.487, end_time=0.801, velocity=76),
                NoteEvent(pitch=67, start_time=0.912, end_time=1.205, velocity=70),
            ],
        },
    ]
    rows = []
    for fixture in ALL_CLEANER_FIXTURES:
        raw = notes_from_dicts(fixture["raw"])
        compared = compare_cleaner_variants(raw)
        rows.append(
            {
                "name": fixture["name"],
                "raw_count": len(raw),
                "variants": {k: v.to_dict() for k, v in compared.items()},
            }
        )
    for case in extra_cases:
        compared = compare_cleaner_variants(list(case["raw"]))
        rows.append(
            {
                "name": case["name"],
                "raw_count": len(case["raw"]),
                "variants": {k: v.to_dict() for k, v in compared.items()},
            }
        )
    return rows


def _pipeline_fixture_rows(out_root: Path) -> dict[str, Any]:
    from evaluation.execute import evaluate_case
    from evaluation.fixture import prepare_fixture
    from evaluation.schema import parse_case_dir
    from intelligence.config import gemini_config
    from mir.pipeline import UnderstandingPipeline

    case_dir = prepare_fixture()
    spec = parse_case_dir(case_dir, "development")
    gemini = gemini_config()
    rows = []
    for key in ("A", "B", "C", "D"):
        spec_v = VARIANTS[key]
        if spec_v["gemini"] and not gemini.active:
            rows.append(
                {
                    "key": key,
                    "label": spec_v["label"],
                    "status": "skipped",
                    "skip_reason": "Gemini not configured",
                }
            )
            continue
        pipe = UnderstandingPipeline(
            mode="fast",
            validation_mode=spec_v["validation_mode"],
        )
        result = evaluate_case(spec, case_out_dir=out_root / key, pipeline=pipe)
        rows.append(
            {
                "key": key,
                "label": spec_v["label"],
                "status": result.status,
                "onset_pitch_f1": (result.notes or {}).get("onset_pitch_f1"),
                "predicted_count": (result.notes or {}).get("predicted_count"),
                "reference_count": (result.notes or {}).get("reference_count"),
                "pipeline": result.pipeline,
                "notation": result.notation,
                "error": result.error,
            }
        )
    return {"case_id": spec.case_id, "variants": rows}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="A/B cleaner and pipeline comparison")
    parser.add_argument("--out", type=Path, default=Path("evaluation/results/ab.json"))
    args = parser.parse_args(argv)
    payload = {
        "cleaner_fixtures": _cleaner_fixture_rows(),
        "pipeline_fixture": _pipeline_fixture_rows(args.out.parent / "ab_pipeline"),
    }
    write_ab_report_full(payload, args.out)
    print(json.dumps(payload, indent=2, default=str))
    return 0


def write_ab_report_full(payload: dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    raise SystemExit(main())

