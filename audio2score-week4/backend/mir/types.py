"""Common Musical Representation (CMR) types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class InstrumentKind(str, Enum):
    PIANO = "piano"
    GUITAR = "guitar"
    VOICE = "voice"
    DRUMS = "drums"
    STRINGS = "strings"
    UNKNOWN = "unknown"


class Hand(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    UNKNOWN = "unknown"


@dataclass
class InstrumentCharacteristics:
    polyphony: float = 0.0
    pitch_range_semitones: float = 0.0
    attack_profile: float = 0.0
    sustain_profile: float = 0.0


@dataclass
class InstrumentPrediction:
    instrument: InstrumentKind
    confidence: float
    characteristics: InstrumentCharacteristics = field(
        default_factory=InstrumentCharacteristics
    )


@dataclass
class AudioSegment:
    start_time: float
    end_time: float
    estimated_tempo: float = 120.0
    energy_profile: float = 0.0


@dataclass
class OnsetCandidate:
    timestamp: float
    strength: float
    confidence: float


@dataclass
class PitchMatrix:
    """Frame-wise pitch activations (never raw FFT peaks)."""

    times: list[float]
    pitch_bins: list[int]
    probabilities: list[list[float]]
    confidence: float = 1.0


@dataclass
class NoteEvent:
    """Raw detected note in seconds (pre-notation)."""

    pitch: int
    start_time: float
    end_time: float
    velocity: int = 64
    confidence: float = 1.0
    hand: Hand = Hand.UNKNOWN

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


@dataclass
class TempoPoint:
    time_sec: float
    beat: float
    bpm: float
    confidence: float = 1.0


@dataclass
class TempoMap:
    points: list[TempoPoint] = field(default_factory=list)

    def sorted_points(self) -> list[TempoPoint]:
        return sorted(self.points, key=lambda p: p.time_sec)

    def bpm_at(self, time_sec: float) -> float:
        points = self.sorted_points()
        if not points:
            return 120.0
        best = points[0]
        for pt in points:
            if pt.time_sec <= time_sec:
                best = pt
            else:
                break
        return best.bpm

    def seconds_to_beats(self, time_sec: float) -> float:
        points = self.sorted_points()
        if not points:
            return time_sec * (120.0 / 60.0)
        beat = 0.0
        prev_t = 0.0
        prev_bpm = points[0].bpm
        for pt in points:
            if pt.time_sec >= time_sec:
                dt = time_sec - prev_t
                beat += dt * (prev_bpm / 60.0)
                return beat
            dt = pt.time_sec - prev_t
            beat += dt * (prev_bpm / 60.0)
            prev_t = pt.time_sec
            prev_bpm = pt.bpm
        dt = time_sec - prev_t
        beat += dt * (prev_bpm / 60.0)
        return beat

    def beats_to_seconds(self, beat: float) -> float:
        points = self.sorted_points()
        if not points:
            return beat * (60.0 / 120.0)
        prev_t = 0.0
        prev_beat = 0.0
        prev_bpm = max(points[0].bpm, 1e-6)
        for pt in points:
            if pt.time_sec > prev_t:
                interval_beats = (pt.time_sec - prev_t) * (prev_bpm / 60.0)
                if prev_beat + interval_beats >= beat:
                    return prev_t + (beat - prev_beat) * (60.0 / prev_bpm)
                prev_beat += interval_beats
                prev_t = pt.time_sec
            prev_bpm = max(pt.bpm, 1e-6)
        return prev_t + (beat - prev_beat) * (60.0 / prev_bpm)

    def median_bpm(self) -> float:
        points = self.sorted_points()
        if not points:
            return 120.0
        bpms = sorted(p.bpm for p in points)
        mid = len(bpms) // 2
        if len(bpms) % 2:
            return float(bpms[mid])
        return float(bpms[mid - 1] + bpms[mid]) / 2.0


@dataclass
class Chord:
    name: str
    notes: list[int]
    confidence: float
    start_time: float = 0.0


@dataclass
class MusicalRole:
    melody_notes: list[NoteEvent] = field(default_factory=list)
    bass_notes: list[NoteEvent] = field(default_factory=list)
    accompaniment_notes: list[NoteEvent] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class MusicalEvent:
    """Unified event for notation (source-agnostic)."""

    pitch: int
    start_beat: float
    duration_beats: float
    velocity: int = 64
    instrument: InstrumentKind = InstrumentKind.UNKNOWN
    voice: int = 0
    hand: Hand = Hand.UNKNOWN
    phrase_id: Optional[int] = None
    articulation: Optional[str] = None
    dynamic: Optional[str] = None
    confidence: float = 1.0
    source_backend: str = "unknown"


@dataclass
class ScoreMeta:
    key_hint: Optional[str] = None
    time_sig_hint: Optional[str] = None
    instrument_prediction: Optional[InstrumentPrediction] = None
    segments: list[AudioSegment] = field(default_factory=list)
    display_tempo_bpm: int = 120
    tempo_map: Optional[TempoMap] = None
    extra: dict[str, Any] = field(default_factory=dict)
