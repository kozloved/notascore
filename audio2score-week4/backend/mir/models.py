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
    """Adapter output: acoustic notes plus provenance. Not a score."""

    notes: list[NoteEvent]
    backend: str
    audio_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


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


@dataclass
class PlannedRest:
    start_q: float
    duration_q: float
    voice: int


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
