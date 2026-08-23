"""Melody / bass / accompaniment role separation."""

from __future__ import annotations

import statistics

from mir.types import MusicalRole, NoteEvent


class MelodyAccompanimentSeparator:
    """First-pass register + continuity based role assignment."""

    MELODY_REGISTER = 60
    BASS_REGISTER = 48

    def separate(self, notes: list[NoteEvent]) -> MusicalRole:
        if not notes:
            return MusicalRole(confidence=0.0)

        pitches = [n.pitch for n in notes]
        median_pitch = statistics.median(pitches)

        melody: list[NoteEvent] = []
        bass: list[NoteEvent] = []
        accompaniment: list[NoteEvent] = []

        for note in notes:
            if note.pitch >= max(self.MELODY_REGISTER, median_pitch + 5):
                melody.append(note)
            elif note.pitch <= min(self.BASS_REGISTER, median_pitch - 5):
                bass.append(note)
            else:
                accompaniment.append(note)

        # Promote highest note in dense chords to melody if melody empty
        if not melody and notes:
            top = max(notes, key=lambda n: n.pitch)
            melody = [top]
            accompaniment = [n for n in notes if n is not top]

        confidence = 0.5
        if melody and bass:
            confidence = 0.75
        elif melody or bass:
            confidence = 0.6

        return MusicalRole(
            melody_notes=melody,
            bass_notes=bass,
            accompaniment_notes=accompaniment,
            confidence=confidence,
        )
