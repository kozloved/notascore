"""Error taxonomy labels and row records for Checkpoint 8 forensics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


# Reference-centric classifications
REF_MATCH = "MATCH"
REF_MISSED = "MISSED"
REF_PITCH_ERROR = "PITCH_ERROR"
REF_ONSET_ERROR = "ONSET_ERROR"
REF_OFFSET_ERROR = "OFFSET_ERROR"
REF_FRAGMENTED = "FRAGMENTED"
REF_MERGED = "MERGED"

# Prediction-centric classifications
PRED_MATCH = "MATCH"
PRED_SPURIOUS = "SPURIOUS"
PRED_DUPLICATE = "DUPLICATE"
PRED_PITCH_CONFUSION = "PITCH_CONFUSION"
PRED_EARLY = "EARLY"
PRED_LATE = "LATE"
PRED_EXTRA_FRAGMENT = "EXTRA_FRAGMENT"

REF_CLASSES = (
    REF_MATCH,
    REF_MISSED,
    REF_PITCH_ERROR,
    REF_ONSET_ERROR,
    REF_OFFSET_ERROR,
    REF_FRAGMENTED,
    REF_MERGED,
)

PRED_CLASSES = (
    PRED_MATCH,
    PRED_SPURIOUS,
    PRED_DUPLICATE,
    PRED_PITCH_CONFUSION,
    PRED_EARLY,
    PRED_LATE,
    PRED_EXTRA_FRAGMENT,
)


def midi_note_name(pitch: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    p = int(pitch)
    return f"{names[p % 12]}{p // 12 - 1}"


@dataclass
class NoteErrorRow:
    """One row of note_errors.csv / JSON diagnostics."""

    case_id: str
    stage: str
    side: str  # "reference" | "predicted" | "pair"
    classification: str
    reference_index: int | None = None
    predicted_index: int | None = None
    reference_pitch: int | None = None
    reference_note_name: str | None = None
    reference_onset: float | None = None
    reference_offset: float | None = None
    reference_duration: float | None = None
    predicted_pitch: int | None = None
    predicted_note_name: str | None = None
    predicted_onset: float | None = None
    predicted_offset: float | None = None
    predicted_duration: float | None = None
    pitch_error_semitones: int | None = None
    onset_error_ms: float | None = None
    offset_error_ms: float | None = None
    duration_error_ms: float | None = None
    velocity_reference: int | None = None
    velocity_predicted: int | None = None
    local_polyphony: int | None = None
    reference_tempo: float | None = None
    predicted_tempo: float | None = None
    nearest_reference_distance_ms: float | None = None
    nearest_predicted_distance_ms: float | None = None
    confidence: float | None = None
    reason: str = ""
    related_indices: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaxonomySummary:
    """Counts for one stage comparison."""

    stage: str
    reference_count: int
    predicted_count: int
    reference_classes: dict[str, int] = field(default_factory=dict)
    predicted_classes: dict[str, int] = field(default_factory=dict)
    matched_pairs: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    pitch_errors: int = 0
    onset_errors: int = 0
    offset_errors: int = 0
    fragmented: int = 0
    merged: int = 0
    duplicates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
