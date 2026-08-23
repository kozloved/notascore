"""Map velocity to dynamic markings."""

from __future__ import annotations

from mir.types import MusicalEvent

VELOCITY_TO_DYNAMIC = [
    (24, "pp"),
    (40, "p"),
    (56, "mp"),
    (72, "mf"),
    (88, "f"),
    (104, "ff"),
    (127, "fff"),
]


class DynamicsExtractor:
    def extract(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        result: list[MusicalEvent] = []
        for ev in events:
            dynamic = "mf"
            for threshold, mark in VELOCITY_TO_DYNAMIC:
                if ev.velocity <= threshold:
                    dynamic = mark
                    break
            else:
                dynamic = "fff"
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
                    articulation=ev.articulation,
                    dynamic=dynamic,
                    confidence=ev.confidence,
                    source_backend=ev.source_backend,
                )
            )
        return result
