"""Polyphonic voice assignment within a staff."""

from __future__ import annotations

from mir.types import Hand, MusicalEvent


class VoiceSeparator:
    """Assign voice numbers to avoid cross-voice collisions on one staff."""

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        by_hand: dict[Hand, list[MusicalEvent]] = {}
        for ev in events:
            by_hand.setdefault(ev.hand, []).append(ev)

        result: list[MusicalEvent] = []
        for hand, group in by_hand.items():
            group.sort(key=lambda e: (e.start_beat, e.pitch))
            active: list[tuple[float, int]] = []
            voice_counter = 0
            for ev in group:
                active = [(end, v) for end, v in active if end > ev.start_beat]
                used = {v for _, v in active}
                voice = 0
                while voice in used:
                    voice += 1
                if voice > voice_counter:
                    voice_counter = voice
                end_beat = ev.start_beat + ev.duration_beats
                active.append((end_beat, voice))
                result.append(
                    MusicalEvent(
                        pitch=ev.pitch,
                        start_beat=ev.start_beat,
                        duration_beats=ev.duration_beats,
                        velocity=ev.velocity,
                        instrument=ev.instrument,
                        voice=voice,
                        hand=hand,
                        phrase_id=ev.phrase_id,
                        articulation=ev.articulation,
                        dynamic=ev.dynamic,
                        confidence=ev.confidence,
                        source_backend=ev.source_backend,
                    )
                )
        return sorted(result, key=lambda e: (e.hand.value, e.start_beat, e.pitch))
