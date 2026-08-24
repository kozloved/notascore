"""Canonical musical-structure + notation benchmark cases (synthetic)."""

from __future__ import annotations

from dataclasses import dataclass, field

from mir.types import Hand, MusicalEvent, NoteEvent


@dataclass
class BenchmarkCase:
    name: str
    description: str
    notes: list[NoteEvent] = field(default_factory=list)
    events: list[MusicalEvent] = field(default_factory=list)
    expected_hands: dict[int, str] = field(default_factory=dict)  # pitch → hand
    expected_voice_count_rh: int | None = None
    expected_meter: str | None = None
    metadata: dict = field(default_factory=dict)


def _note(pitch, start, end, vel=80, conf=1.0) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        start_time=start,
        end_time=end,
        velocity=vel,
        confidence=conf,
    )


def _ev(pitch, start, dur, hand=None, voice=0, role=None) -> MusicalEvent:
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        hand=hand or Hand.UNKNOWN,
        voice=voice,
        role=role,
        velocity=80,
    )


def two_hand_scale_case() -> BenchmarkCase:
    events = []
    expected = {}
    for i in range(8):
        events.append(_ev(48 + i, float(i), 0.5, role="bass"))
        events.append(_ev(72 + i, float(i), 0.5, role="melody"))
        expected[48 + i] = "left"
        expected[72 + i] = "right"
    return BenchmarkCase(
        name="two_hand_scale",
        description="Parallel diatonic scales two octaves apart",
        events=events,
        expected_hands=expected,
        expected_meter="4/4",
        metadata={"kind": "hands"},
    )


def melody_below_middle_c_case() -> BenchmarkCase:
    melody = [64, 62, 60, 59, 57, 55]
    bass = [36, 38, 40, 41, 43, 45]
    events = []
    expected = {}
    for i, (m, b) in enumerate(zip(melody, bass)):
        events.append(_ev(b, float(i), 1.0, role="bass"))
        events.append(_ev(m, float(i), 1.0, role="melody"))
        expected[m] = "right"
        expected[b] = "left"
    return BenchmarkCase(
        name="melody_below_middle_c",
        description="RH melody crosses below middle C",
        events=events,
        expected_hands=expected,
        metadata={"kind": "hands"},
    )


def polyphonic_rh_case() -> BenchmarkCase:
    events = [
        _ev(60, 0.0, 4.0, hand=Hand.RIGHT, role="accompaniment"),
        _ev(76, 0.0, 1.0, hand=Hand.RIGHT, role="melody"),
        _ev(77, 1.0, 1.0, hand=Hand.RIGHT, role="melody"),
        _ev(79, 2.0, 1.0, hand=Hand.RIGHT, role="melody"),
        _ev(81, 3.0, 1.0, hand=Hand.RIGHT, role="melody"),
    ]
    return BenchmarkCase(
        name="polyphonic_rh",
        description="Sustained inner voice under RH melody",
        events=events,
        expected_voice_count_rh=2,
        expected_meter="4/4",
        metadata={"kind": "voices"},
    )


def straight_eighths_case() -> BenchmarkCase:
    events = [_ev(72, i * 0.5, 0.5, hand=Hand.RIGHT) for i in range(16)]
    return BenchmarkCase(
        name="straight_eighths",
        description="Straight eighths should read as 4/4 (or 2/4)",
        events=events,
        expected_meter="4/4",
        metadata={"kind": "meter"},
    )


ALL_CASES = [
    two_hand_scale_case(),
    melody_below_middle_c_case(),
    polyphonic_rh_case(),
    straight_eighths_case(),
]
