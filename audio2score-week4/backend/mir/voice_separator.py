"""Polyphonic voice assignment within a staff."""

from __future__ import annotations

from dataclasses import replace

from mir.types import Hand, MusicalEvent

CHORD_START_WINDOW = 0.08
CHORD_DURATION_RATIO = 0.5


def _is_chord_mate(a: MusicalEvent, b: MusicalEvent) -> bool:
    if abs(a.start_beat - b.start_beat) > CHORD_START_WINDOW:
        return False
    short, long = sorted((a.duration_beats, b.duration_beats))
    return short >= long * CHORD_DURATION_RATIO


class VoiceSeparator:
    """Assign voice numbers: chords share a voice, held overlaps get a new one."""

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        by_hand: dict[Hand, list[MusicalEvent]] = {}
        for ev in events:
            by_hand.setdefault(ev.hand, []).append(ev)

        result: list[MusicalEvent] = []
        for hand, group in by_hand.items():
            group.sort(key=lambda e: (e.start_beat, e.pitch))
            active: list[MusicalEvent] = []
            for ev in group:
                active = [
                    a
                    for a in active
                    if a.start_beat + a.duration_beats > ev.start_beat + 1e-6
                ]
                used = {a.voice for a in active}
                chord_voice = next(
                    (a.voice for a in active if _is_chord_mate(a, ev)),
                    None,
                )
                if chord_voice is not None:
                    voice = chord_voice
                else:
                    voice = 0
                    while voice in used:
                        voice += 1
                assigned = replace(ev, hand=hand, voice=voice)
                active.append(assigned)
                result.append(assigned)
        return sorted(result, key=lambda e: (e.hand.value, e.start_beat, e.pitch))
