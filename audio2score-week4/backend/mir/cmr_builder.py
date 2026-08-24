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
    melody_keys = set()
    bass_keys = set()
    accomp_keys = set()
    if role:
        melody_keys = {
            (n.pitch, round(n.start_time, 4)) for n in role.melody_notes
        }
        bass_keys = {(n.pitch, round(n.start_time, 4)) for n in role.bass_notes}
        accomp_keys = {
            (n.pitch, round(n.start_time, 4)) for n in role.accompaniment_notes
        }

    events: list[MusicalEvent] = []
    for i, note in enumerate(notes):
        note = note.ensure_ids(i)
        start_beat = tempo_map.seconds_to_beats(note.start_time)
        end_beat = tempo_map.seconds_to_beats(note.end_time)
        duration = max(0.01, end_beat - start_beat)
        key = (note.pitch, round(note.start_time, 4))
        role_name = None
        if key in melody_keys:
            role_name = "melody"
        elif key in bass_keys:
            role_name = "bass"
        elif key in accomp_keys:
            role_name = "accompaniment"

        # Roles stay on `role` only. Never convert melody/bass into a hand.
        # Incoming note.hand is a hint (or a lock if hand_locked is set).
        events.append(
            MusicalEvent(
                pitch=note.pitch,
                start_beat=start_beat,
                duration_beats=duration,
                velocity=note.velocity,
                instrument=instrument,
                hand=note.hand if note.hand is not None else Hand.UNKNOWN,
                hand_locked=bool(getattr(note, "hand_locked", False)),
                confidence=note.confidence,
                source_backend=note.source_backend or source_backend,
                note_id=note.note_id,
                start_time_sec=note.start_time,
                end_time_sec=note.end_time,
                role=role_name,
            )
        )

    return sorted(events, key=lambda e: (e.start_beat, e.pitch))


def build_score_meta(
    tempo_map: TempoMap,
    instrument: InstrumentKind,
    segments,
    display_bpm: int = 120,
    instrument_confidence: float = 0.8,
    time_sig_hint: str | None = None,
    key_hint: str | None = None,
) -> ScoreMeta:
    from mir.types import InstrumentPrediction, InstrumentCharacteristics

    return ScoreMeta(
        display_tempo_bpm=display_bpm,
        segments=list(segments),
        tempo_map=tempo_map,
        time_sig_hint=time_sig_hint,
        key_hint=key_hint,
        instrument_prediction=InstrumentPrediction(
            instrument=instrument,
            confidence=instrument_confidence,
            characteristics=InstrumentCharacteristics(),
        ),
    )
