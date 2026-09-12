"""Gated post-transcription filter for spurious low-confidence notes.

Off by default. Enable for comparison / validation via
NOTASCORE_DROP_LOW_CONFIDENCE=1 or min_confidence argument.
"""

from __future__ import annotations

import os
from typing import Sequence

from mir.types import NoteEvent


def drop_low_confidence_enabled() -> bool:
    raw = os.getenv("NOTASCORE_DROP_LOW_CONFIDENCE", "0")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def min_note_confidence() -> float:
    raw = os.getenv("NOTASCORE_MIN_NOTE_CONFIDENCE", "0.45")
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.45


def drop_low_confidence_notes(
    notes: Sequence[NoteEvent],
    *,
    enabled: bool | None = None,
    threshold: float | None = None,
) -> list[NoteEvent]:
    """Remove likely-spurious notes below a confidence floor.

    Notes without confidence are retained. When disabled, returns a shallow
    copy of the input list unchanged.
    """
    active = drop_low_confidence_enabled() if enabled is None else bool(enabled)
    floor = min_note_confidence() if threshold is None else float(threshold)
    if not active:
        return list(notes)
    kept: list[NoteEvent] = []
    for note in notes:
        confidence = getattr(note, "confidence", None)
        if confidence is None:
            kept.append(note)
            continue
        if float(confidence) >= floor:
            kept.append(note)
    return kept
