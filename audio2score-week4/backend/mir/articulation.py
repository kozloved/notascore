"""Detect articulations from duration and gap patterns."""

from __future__ import annotations

from mir.types import MusicalEvent

QUARTER_BEAT = 1.0
STACCATO_MAX = 0.35
LEGATO_GAP_MAX = 0.05


class ArticulationDetector:
    def detect(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        sorted_ev = sorted(events, key=lambda e: (e.pitch, e.start_beat))
        by_pitch: dict[int, list[MusicalEvent]] = {}
        for ev in sorted_ev:
            by_pitch.setdefault(ev.pitch, []).append(ev)

        articulation_map: dict[tuple[int, float], str] = {}
        for pitch, group in by_pitch.items():
            for i, ev in enumerate(group):
                art = None
                if ev.duration_beats < STACCATO_MAX * QUARTER_BEAT:
                    art = "staccato"
                elif i + 1 < len(group):
                    gap = group[i + 1].start_beat - (ev.start_beat + ev.duration_beats)
                    if gap <= LEGATO_GAP_MAX:
                        art = "legato"
                if art:
                    articulation_map[(pitch, ev.start_beat)] = art

        result: list[MusicalEvent] = []
        for ev in events:
            art = articulation_map.get((ev.pitch, ev.start_beat))
            result.append(
                MusicalEvent(
                    pitch=ev.pitch,
                    start_beat=ev.start_beat,
                    duration_beats=ev.duration_beats,
                    velocity=ev.velocity,
                    instrument=ev.instrument,
                    voice=ev.voice,
                    hand=ev.hand,
                    phrase_id=ev.phrase_id,
                    articulation=art,
                    dynamic=ev.dynamic,
                    confidence=ev.confidence,
                    source_backend=ev.source_backend,
                )
            )
        return result
