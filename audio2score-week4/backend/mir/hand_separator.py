"""MIDI Intelligence: piano hand separation."""

from __future__ import annotations

from mir.types import Hand, MusicalEvent


class HandSeparator:
    """Split events onto LH/RH using pitch register and existing hints."""

    SPLIT_PITCH = 60  # middle C

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        result: list[MusicalEvent] = []
        for ev in events:
            if ev.hand != Hand.UNKNOWN:
                result.append(ev)
                continue
            hand = Hand.RIGHT if ev.pitch >= self.SPLIT_PITCH else Hand.LEFT
            result.append(
                MusicalEvent(
                    pitch=ev.pitch,
                    start_beat=ev.start_beat,
                    duration_beats=ev.duration_beats,
                    velocity=ev.velocity,
                    instrument=ev.instrument,
                    voice=ev.voice,
                    hand=hand,
                    phrase_id=ev.phrase_id,
                    articulation=ev.articulation,
                    dynamic=ev.dynamic,
                    confidence=ev.confidence,
                    source_backend=ev.source_backend,
                )
            )
        return result
