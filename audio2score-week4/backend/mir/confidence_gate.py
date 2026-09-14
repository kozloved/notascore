"""Optional post-transcription filter. Off by default.

Field semantics
---------------
* ``model_score`` — backend amplitude / frame score. Uncalibrated.
* ``velocity`` — MIDI velocity 1–127. Loudness, not correctness.
* ``confidence`` — compatibility field. Meaning depends on ``confidence_source``.
* ``confidence_source``:
    - ``amplitude``: Basic Pitch model score copied into ``confidence``
    - ``velocity``: ``velocity / 127``
    - ``default``: MIDI / MT3 placeholder ``1.0`` (not acoustic proof)
    - ``calibrated``: a probability from a measured calibration
    - ``unknown``: do not treat as a probability

Quiet notes are not presumed false. The default enabled criterion drops only
notes whose ``confidence_source`` is ``calibrated`` and whose score is below
the threshold. Amplitude, velocity, and MT3 default 1.0 are never used as
calibrated probabilities here.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Sequence

from mir.types import NoteEvent

CALIBRATED = "calibrated"
AMPLITUDE = "amplitude"
VELOCITY = "velocity"
DEFAULT = "default"
UNKNOWN = "unknown"

# Sources that must not be treated as P(note is real).
UNCALIBRATED_SOURCES = frozenset({AMPLITUDE, VELOCITY, DEFAULT, UNKNOWN, ""})


def drop_low_confidence_enabled() -> bool:
    raw = os.getenv("NOTASCORE_DROP_LOW_CONFIDENCE", "0")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def min_note_confidence() -> float:
    raw = os.getenv("NOTASCORE_MIN_NOTE_CONFIDENCE", "0.45")
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.45


def filter_criterion() -> str:
    """Which score the optional gate uses. Default: calibrated confidence only."""
    raw = (os.getenv("NOTASCORE_FILTER_CRITERION") or "calibrated_confidence").strip()
    return raw or "calibrated_confidence"


@dataclass(frozen=True)
class FilterRemoval:
    note_id: str
    pitch: int
    criterion: str
    score: float | None
    threshold: float
    confidence_source: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FilterReport:
    enabled: bool
    criterion: str
    threshold: float
    input_count: int
    kept_count: int
    removals: list[FilterRemoval]

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "criterion": self.criterion,
            "threshold": self.threshold,
            "input_count": self.input_count,
            "kept_count": self.kept_count,
            "removed_count": len(self.removals),
            "removals": [r.to_dict() for r in self.removals],
        }


def _score_for_criterion(note: NoteEvent, criterion: str) -> tuple[float | None, str]:
    source = str(getattr(note, "confidence_source", "") or UNKNOWN)
    if criterion == "calibrated_confidence":
        if source != CALIBRATED:
            return None, source
        value = getattr(note, "confidence", None)
        return (None if value is None else float(value)), source
    if criterion == "model_score":
        value = getattr(note, "model_score", None)
        if value is None:
            return None, source
        return float(value), source or AMPLITUDE
    if criterion == "confidence":
        # Explicit compatibility path. Still refuses MT3 default 1.0-as-proof
        # by skipping default/unknown sources unless they are calibrated.
        if source in UNCALIBRATED_SOURCES and source != AMPLITUDE:
            return None, source
        value = getattr(note, "confidence", None)
        return (None if value is None else float(value)), source
    return None, source


def apply_optional_filter(
    notes: Sequence[NoteEvent],
    *,
    enabled: bool | None = None,
    threshold: float | None = None,
    criterion: str | None = None,
) -> tuple[list[NoteEvent], FilterReport]:
    """Return (derived notes, report). Never mutates the input list or notes."""
    active = drop_low_confidence_enabled() if enabled is None else bool(enabled)
    floor = min_note_confidence() if threshold is None else float(threshold)
    used = criterion if criterion is not None else filter_criterion()
    original = list(notes)
    if not active:
        return original, FilterReport(
            enabled=False,
            criterion=used,
            threshold=floor,
            input_count=len(original),
            kept_count=len(original),
            removals=[],
        )
    kept: list[NoteEvent] = []
    removals: list[FilterRemoval] = []
    for note in original:
        score, source = _score_for_criterion(note, used)
        if score is None or score >= floor:
            kept.append(note)
            continue
        removals.append(
            FilterRemoval(
                note_id=note.note_id,
                pitch=int(note.pitch),
                criterion=used,
                score=score,
                threshold=floor,
                confidence_source=source,
            )
        )
    return kept, FilterReport(
        enabled=True,
        criterion=used,
        threshold=floor,
        input_count=len(original),
        kept_count=len(kept),
        removals=removals,
    )


def drop_low_confidence_notes(
    notes: Sequence[NoteEvent],
    *,
    enabled: bool | None = None,
    threshold: float | None = None,
    criterion: str | None = None,
) -> list[NoteEvent]:
    """Remove notes below a floor. Default criterion is calibrated confidence.

    Notes without a usable score for the active criterion are retained. When
    disabled, returns a shallow copy of the input list unchanged.
    """
    kept, _report = apply_optional_filter(
        notes, enabled=enabled, threshold=threshold, criterion=criterion
    )
    return kept
