"""Simple phrase boundary detection from note gaps."""

from __future__ import annotations

from mir.types import MusicalEvent, NoteEvent


class PhraseDetector:
    """Assign phrase IDs based on inter-onset gaps in beat space."""

    def __init__(self, gap_beats: float = 1.0):
        self.gap_beats = gap_beats

    def detect_from_notes(self, notes: list[NoteEvent], bpm: float = 120.0) -> dict[tuple[int, float], int]:
        if not notes:
            return {}
        spb = 60.0 / bpm
        sorted_notes = sorted(notes, key=lambda n: n.start_time)
        phrase_id = 0
        mapping: dict[tuple[int, float], int] = {}
        prev_end = sorted_notes[0].start_time
        for n in sorted_notes:
            if n.start_time - prev_end > self.gap_beats * spb:
                phrase_id += 1
            mapping[(n.pitch, round(n.start_time, 4))] = phrase_id
            prev_end = max(prev_end, n.end_time)
        return mapping

    def apply(self, events: list[MusicalEvent], mapping: dict[tuple[int, float], int], bpm: float = 120.0) -> list[MusicalEvent]:
        spb = 60.0 / bpm
        result: list[MusicalEvent] = []
        for ev in events:
            t_sec = ev.start_beat * spb
            pid = mapping.get((ev.pitch, round(t_sec, 4)))
            result.append(
                MusicalEvent(
                    pitch=ev.pitch,
                    start_beat=ev.start_beat,
                    duration_beats=ev.duration_beats,
                    velocity=ev.velocity,
                    instrument=ev.instrument,
                    voice=ev.voice,
                    hand=ev.hand,
                    phrase_id=pid,
                    articulation=ev.articulation,
                    dynamic=ev.dynamic,
                    confidence=ev.confidence,
                    source_backend=ev.source_backend,
                )
            )
        return result
