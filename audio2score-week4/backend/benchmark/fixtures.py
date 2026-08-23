"""Before/after fixtures for MIDICleaner evaluation."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mir.types import NoteEvent


def notes_from_dicts(rows: list[dict[str, Any]]) -> list[NoteEvent]:
    return [
        NoteEvent(
            pitch=int(r["pitch"]),
            start_time=float(r["start_time"]),
            end_time=float(r["end_time"]),
            velocity=int(r.get("velocity", 64)),
            confidence=float(r.get("confidence", 1.0)),
        )
        for r in rows
    ]


def notes_to_dicts(notes: list[NoteEvent]) -> list[dict[str, Any]]:
    return [asdict(n) for n in notes]


# C / E / G micro-misaligned chord (plan example)
FIXTURE_CHORD_MISALIGNED = {
    "name": "c_major_misaligned",
    "raw": [
        {"pitch": 60, "start_time": 0.500, "end_time": 1.200, "velocity": 80},
        {"pitch": 64, "start_time": 0.502, "end_time": 1.200, "velocity": 75},
        {"pitch": 67, "start_time": 0.501, "end_time": 1.200, "velocity": 70},
    ],
    "expected_after": [
        {"pitch": 60, "start_time": 0.500, "end_time": 1.200, "velocity": 80},
        {"pitch": 64, "start_time": 0.500, "end_time": 1.200, "velocity": 75},
        {"pitch": 67, "start_time": 0.500, "end_time": 1.200, "velocity": 70},
    ],
}

# Resonance duplicate + micro-note garbage
FIXTURE_RESONANCE_GARBAGE = {
    "name": "resonance_and_micro",
    "raw": [
        {"pitch": 60, "start_time": 0.000, "end_time": 0.800, "velocity": 90},
        {"pitch": 60, "start_time": 0.012, "end_time": 0.820, "velocity": 40},
        {"pitch": 72, "start_time": 0.400, "end_time": 0.420, "velocity": 30},
        {"pitch": 67, "start_time": 0.500, "end_time": 1.000, "velocity": 70},
    ],
    "expected_after": [
        {"pitch": 60, "start_time": 0.000, "end_time": 0.820, "velocity": 90},
        {"pitch": 67, "start_time": 0.500, "end_time": 1.000, "velocity": 70},
    ],
}

# Melody line that should mostly survive cleaning
FIXTURE_MELODY_PRESERVE = {
    "name": "melody_preserve",
    "raw": [
        {"pitch": 72, "start_time": 0.00, "end_time": 0.40, "velocity": 88},
        {"pitch": 74, "start_time": 0.50, "end_time": 0.90, "velocity": 86},
        {"pitch": 76, "start_time": 1.00, "end_time": 1.40, "velocity": 90},
        {"pitch": 77, "start_time": 1.50, "end_time": 1.90, "velocity": 85},
    ],
    "expected_after": [
        {"pitch": 72, "start_time": 0.00, "end_time": 0.40, "velocity": 88},
        {"pitch": 74, "start_time": 0.50, "end_time": 0.90, "velocity": 86},
        {"pitch": 76, "start_time": 1.00, "end_time": 1.40, "velocity": 90},
        {"pitch": 77, "start_time": 1.50, "end_time": 1.90, "velocity": 85},
    ],
}

ALL_CLEANER_FIXTURES = [
    FIXTURE_CHORD_MISALIGNED,
    FIXTURE_RESONANCE_GARBAGE,
    FIXTURE_MELODY_PRESERVE,
]
