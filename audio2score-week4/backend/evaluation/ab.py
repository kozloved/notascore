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
