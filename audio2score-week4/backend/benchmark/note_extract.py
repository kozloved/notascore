"""Extract comparable NoteEvent lists from pipeline MIDI output."""

from __future__ import annotations

from pathlib import Path

import pretty_midi

from mir.types import NoteEvent


def notes_from_midi(path: str | Path) -> list[NoteEvent]:
    midi = pretty_midi.PrettyMIDI(str(path))
    notes: list[NoteEvent] = []
    for inst in midi.instruments:
        for note in inst.notes:
            notes.append(
                NoteEvent(
                    pitch=int(note.pitch),
                    start_time=float(note.start),
                    end_time=float(note.end),
                    velocity=int(note.velocity),
                    confidence=1.0,
                )
            )
    return sorted(notes, key=lambda n: (n.start_time, n.pitch))
