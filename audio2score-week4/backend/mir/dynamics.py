"""Map velocity to dynamic markings."""

from __future__ import annotations

from mir.types import MusicalEvent, copy_event

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
            result.append(copy_event(ev, dynamic=dynamic))
        return result
