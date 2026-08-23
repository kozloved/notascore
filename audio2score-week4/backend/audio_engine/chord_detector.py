"""Chord detection from simultaneous notes."""

from __future__ import annotations

from mir.types import Chord, NoteEvent

CHORD_TEMPLATES = {
    "C": {0, 4, 7},
    "Cm": {0, 3, 7},
    "C7": {0, 4, 7, 10},
    "Cmaj7": {0, 4, 7, 11},
    "D": {2, 6, 9},
    "Dm": {2, 5, 9},
    "E": {4, 8, 11},
    "Em": {4, 7, 11},
    "F": {5, 9, 0},
    "Fm": {5, 8, 0},
    "G": {7, 11, 2},
    "Gm": {7, 10, 2},
    "A": {9, 1, 4},
    "Am": {9, 0, 4},
    "B": {11, 3, 6},
    "Bm": {11, 2, 6},
}


class ChordDetector:
    """Label simultaneous pitch-class sets."""

    def __init__(self, simultaneity_sec: float = 0.05):
        self.simultaneity_sec = simultaneity_sec

    def detect(self, notes: list[NoteEvent]) -> list[Chord]:
        if not notes:
            return []

        groups = self._group_simultaneous(notes)
        chords: list[Chord] = []
        for start, group in groups:
            pcs = {n.pitch % 12 for n in group}
            name, conf = self._match_template(pcs)
            chords.append(
                Chord(
                    name=name,
                    notes=sorted(n.pitch for n in group),
                    confidence=conf,
                    start_time=start,
                )
            )
        return chords

    def _group_simultaneous(
        self, notes: list[NoteEvent]
    ) -> list[tuple[float, list[NoteEvent]]]:
        sorted_notes = sorted(notes, key=lambda n: n.start_time)
        groups: list[tuple[float, list[NoteEvent]]] = []
        i = 0
        while i < len(sorted_notes):
            start = sorted_notes[i].start_time
            group = [sorted_notes[i]]
            j = i + 1
            while j < len(sorted_notes) and sorted_notes[j].start_time - start <= self.simultaneity_sec:
                group.append(sorted_notes[j])
                j += 1
            if len(group) >= 2:
                groups.append((start, group))
            i = j if j > i + 1 else i + 1
        return groups

    def _match_template(self, pitch_classes: set[int]) -> tuple[str, float]:
        best_name = "unknown"
        best_score = 0.0
        for name, template in CHORD_TEMPLATES.items():
            overlap = len(pitch_classes & template)
            score = overlap / max(len(template), 1)
            if score > best_score:
                best_score = score
                best_name = name
        if best_score < 0.6:
            return "cluster", best_score
        return best_name, min(1.0, best_score)
