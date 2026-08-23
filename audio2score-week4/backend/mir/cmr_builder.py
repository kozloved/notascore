"""Build MusicalEvent stream from notes + tempo map + roles."""

from __future__ import annotations

from mir.types import (
    Hand,
    InstrumentKind,
    MusicalEvent,
    MusicalRole,
    NoteEvent,
    ScoreMeta,
    TempoMap,
)


def notes_to_events(
    notes: list[NoteEvent],
    tempo_map: TempoMap,
    role: MusicalRole | None = None,
    instrument: InstrumentKind = InstrumentKind.PIANO,
    source_backend: str = "unknown",
) -> list[MusicalEvent]:
    melody_pitches = {n.pitch for n in role.melody_notes} if role else set()
    bass_pitches = {n.pitch for n in role.bass_notes} if role else set()

    events: list[MusicalEvent] = []
    for note in notes:
        start_beat = tempo_map.seconds_to_beats(note.start_time)
        end_beat = tempo_map.seconds_to_beats(note.end_time)
        duration = max(0.01, end_beat - start_beat)

        hand = Hand.UNKNOWN
        if note.pitch in melody_pitches:
            hand = Hand.RIGHT
        elif note.pitch in bass_pitches:
            hand = Hand.LEFT

        events.append(
            MusicalEvent(
                pitch=note.pitch,
                start_beat=start_beat,
                duration_beats=duration,
                velocity=note.velocity,
                instrument=instrument,
                hand=hand,
                confidence=note.confidence,
                source_backend=source_backend,
            )
        )

    return sorted(events, key=lambda e: (e.start_beat, e.pitch))


def build_score_meta(
    tempo_map: TempoMap,
    instrument: InstrumentKind,
    segments,
    display_bpm: int = 120,
) -> ScoreMeta:
    from mir.types import InstrumentPrediction, InstrumentCharacteristics

    return ScoreMeta(
        display_tempo_bpm=display_bpm,
        segments=list(segments),
        instrument_prediction=InstrumentPrediction(
            instrument=instrument,
            confidence=0.8,
            characteristics=InstrumentCharacteristics(),
        ),
    )
