"""Canonical pipeline data models.

Performance (what was played) is separate from structure (what the music is)
and from notation (how a human should read it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union

from mir.types import (
    AudioSegment,
    Hand,
    InstrumentKind,
    InstrumentPrediction,
    MusicalEvent,
    NoteEvent,
    TempoMap,
)


class CleaningAction(str, Enum):
    KEEP = "keep"
    SUPPRESS = "suppress"
    UNCERTAIN = "uncertain"


@dataclass
class ControlChange:
    time_sec: float
    number: int
    value: int
    confidence: float = 1.0


@dataclass
class PedalObservation:
    time_sec: float
    value: int
    confidence: float = 0.5


@dataclass
class TempoObservation:
    time_sec: float
    bpm: float
    confidence: float = 0.5
    source: str = "unknown"


@dataclass
class TranscriptionResult:
    """Adapter output: acoustic notes plus provenance. Not a score.

    `backend` is the actual engine that produced `notes`. Requested vs actual
    identity, original notes, provider MIDI, and unsuccessful attempts are
    first-class so interpretation never has to read mutable adapter `last_*`
    fields. Filtering and notation must copy notes rather than mutate this.
    """

    notes: list[NoteEvent]
    backend: str
    audio_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    requested_backend: str = ""
    actual_backend: str = ""
    original_notes: list[NoteEvent] = field(default_factory=list)
    provider_midi_bytes: bytes | None = None
    provider_raw_sha256: str | None = None
    performance: Any = None
    provider_job_id: str | None = None
    timings: dict[str, Any] = field(default_factory=dict)
    fallback_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    unsuccessful: list[dict[str, Any]] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.actual_backend:
            self.actual_backend = self.backend
        if not self.requested_backend:
            self.requested_backend = self.backend
        if not self.original_notes:
            self.original_notes = list(self.notes)

    @property
    def used_fallback(self) -> bool:
        if self.fallback_reason:
            return True
        return bool(
            self.requested_backend
            and self.actual_backend
            and self.requested_backend != self.actual_backend
        )

    def diagnostic_payload(self) -> dict[str, Any]:
        """JSON-safe identity; never include raw MIDI bytes or secrets."""
        unsuccessful = []
        for row in self.unsuccessful or []:
            if not isinstance(row, dict):
                continue
            item = {
                key: value
                for key, value in row.items()
                if key not in {"provider_midi_bytes", "performance"}
            }
            performance = row.get("performance")
            if performance is not None:
                item["performance_midi_sha256"] = getattr(
                    performance, "midi_sha256", None
                )
                item["performance_note_count"] = len(
                    getattr(performance, "notes", ()) or ()
                )
            unsuccessful.append(item)
        return {
            "requested_backend": self.requested_backend,
            "actual_backend": self.actual_backend,
            "backend": self.backend,
            "note_count": len(self.notes),
            "original_note_count": len(self.original_notes),
            "provider_raw_sha256": self.provider_raw_sha256,
            "provider_job_id": self.provider_job_id,
            "timings": dict(self.timings or {}),
            "fallback_reason": self.fallback_reason,
            "warnings": list(self.warnings or []),
            "settings": dict(self.settings or {}),
            "unsuccessful": unsuccessful,
        }


@dataclass
class RawPerformance:
    """What was performed acoustically, before musical interpretation."""

    notes: list[NoteEvent] = field(default_factory=list)
    control_changes: list[ControlChange] = field(default_factory=list)
    pedal_events: list[PedalObservation] = field(default_factory=list)
    tempo_observations: list[TempoObservation] = field(default_factory=list)
    source_backend: str = "unknown"
    source_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class CleaningDecision:
    note_id: str
    pitch: int
    start_time: float
    action: CleaningAction
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class MeterHypothesis:
    time_signature: str
    numerator: int
    denominator: int
    measure_quarter_length: float
    score: float
    confidence: float
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class MeterDecision:
    """Canonical meter after combining estimator, grouping, and accent evidence."""

    meter: str
    confidence: float
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    evidence_sources: list[str] = field(default_factory=list)
    reason: str = ""
    was_hint_overridden: bool = False
    hypothesis: Optional[MeterHypothesis] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "meter": self.meter,
            "confidence": self.confidence,
            "candidate_scores": list(self.candidate_scores),
            "evidence_sources": list(self.evidence_sources),
            "reason": self.reason,
            "was_hint_overridden": self.was_hint_overridden,
            "extra": dict(self.extra),
        }


@dataclass
class KeyHypothesis:
    name: str
    mode: str
    tonic_pc: int
    score: float
    confidence: float


@dataclass
class MusicalStructure:
    """Explicit musical decisions. music21 must not invent these."""

    events: list[MusicalEvent] = field(default_factory=list)
    tempo_map: Optional[TempoMap] = None
    meter_hypotheses: list[MeterHypothesis] = field(default_factory=list)
    selected_meter: Optional[MeterHypothesis] = None
    key_hypotheses: list[KeyHypothesis] = field(default_factory=list)
    selected_key: Optional[KeyHypothesis] = None
    instrument: InstrumentKind = InstrumentKind.UNKNOWN
    instrument_confidence: float = 0.0
    instrument_prediction: Optional[InstrumentPrediction] = None
    segments: list[AudioSegment] = field(default_factory=list)
    phrases: dict[int, list[str]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedTuplet:
    actual: int
    normal: int
    boundary: Optional[str]
    group_id: str


@dataclass
class PlannedNote:
    pitches: list[int]
    start_q: float
    duration_q: float
    voice: int
    velocity: int = 64
    tie: Optional[str] = None
    event_ids: list[str] = field(default_factory=list)
    articulations: list[str] = field(default_factory=list)
    dynamic: Optional[str] = None
    beams: list[tuple[str, Optional[str]]] = field(default_factory=list)
    tuplet: Optional[PlannedTuplet] = None

    # Parallel to pitches/event_ids, including every fragment of a tied chord.
    velocities: list[int] = field(default_factory=list)


@dataclass
class PlannedRest:
    start_q: float
    duration_q: float
    voice: int
    hidden: bool = False
    tuplet: Optional[PlannedTuplet] = None
    kind: str = "musical"  # musical | structural


PlannedElement = Union[PlannedNote, PlannedRest]


@dataclass
class PlannedVoice:
    voice_id: int
    elements: list[PlannedElement] = field(default_factory=list)


@dataclass
class PlannedStaff:
    staff_id: int
    clef: str
    name: str = ""
    voices: list[PlannedVoice] = field(default_factory=list)


@dataclass
class PlannedMeasure:
    number: int
    start_beat: float
    duration_beats: float
    time_signature: str
    key_signature: Optional[str] = None
    staves: list[PlannedStaff] = field(default_factory=list)


@dataclass
class NotationPlan:
    """Readable-score decisions, fully explicit before MusicXML export."""

    tempo_bpm: int = 120
    time_signature: str = "4/4"
    key_signature: str = "C"
    measures: list[PlannedMeasure] = field(default_factory=list)
    title: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def staff_for_hand(hand: Hand, pitch: int) -> int:
    """Map a hand label to a staff index. Ambiguous uses a weak register prior."""
    if hand == Hand.LEFT:
        return 1
    if hand == Hand.RIGHT:
        return 0
    return 0 if pitch >= 60 else 1
