"""Per-stem transcription through the trusted Basic Pitch adapter.

Drums are never turned into pitched piano notes. Transkun remains a slot for
piano later; it is not enabled in this increment.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from mir.raw_midi import job_raw_stem_midi_path, write_notes_to_midi
from mir.types import InstrumentKind, NoteEvent
from transcription_fed.base import TranscriptionContext
from transcription_fed.router import BasicPitchTranscriber, select_transcriber

PITCHED_STEMS = ("vocals", "piano", "guitar", "bass", "other")
DRUM_STEMS = ("drums",)

STEM_INSTRUMENTS = {
    "piano": InstrumentKind.PIANO,
    "guitar": InstrumentKind.GUITAR,
    "bass": InstrumentKind.BASS,
    "vocals": InstrumentKind.VOICE,
    "drums": InstrumentKind.DRUMS,
    "other": InstrumentKind.UNKNOWN,
}

STEM_PROGRAMS = {
    "piano": 0,
    "guitar": 24,
    "bass": 32,
    "vocals": 52,
    "other": 48,
}


@dataclass
class StemTranscription:
    stem_id: str
    notes: list[NoteEvent]
    midi_path: str = ""
    backend: str = ""
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""
    duration_ms: float = 0.0
    warnings: list[str] = field(default_factory=list)


def stem_is_pitched(stem_id: str) -> bool:
    return stem_id in PITCHED_STEMS


def instrument_for_stem(stem_id: str) -> InstrumentKind:
    return STEM_INSTRUMENTS.get(stem_id, InstrumentKind.UNKNOWN)


def tag_stem_notes(notes: list[NoteEvent], *, stem_id: str, backend: str) -> list[NoteEvent]:
    instrument = instrument_for_stem(stem_id)
    program = STEM_PROGRAMS.get(stem_id)
    tagged = []
    for i, note in enumerate(notes):
        tagged.append(
            replace(
                note.ensure_ids(i),
                source_track_id=stem_id,
                source_backend=backend,
                instrument=instrument if note.instrument == InstrumentKind.UNKNOWN else note.instrument,
                source_program=note.source_program if note.source_program is not None else program,
            )
        )
    return tagged


def transcribe_stem(
    audio_path: str | Path,
    *,
    stem_id: str,
    job_id: str,
    source_path: str | Path,
) -> StemTranscription:
    import time

    started = time.perf_counter()
    if stem_id in DRUM_STEMS:
        return StemTranscription(
            stem_id=stem_id,
            notes=[],
            skipped=True,
            skip_reason="drums are not pitched-transcribed",
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )
    if not stem_is_pitched(stem_id):
        return StemTranscription(
            stem_id=stem_id,
            notes=[],
            skipped=True,
            skip_reason=f"stem {stem_id} is not a pitched transcription target",
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    transcriber = select_transcriber(mode="stem", instrument_hint=stem_id)
    context = TranscriptionContext(instrument_hint=stem_id, stem_id=stem_id)
    try:
        result = transcriber.transcribe(str(audio_path), context)
    except Exception as exc:
        return StemTranscription(
            stem_id=stem_id,
            notes=[],
            backend=getattr(transcriber, "name", "basic_pitch"),
            error=str(exc),
            duration_ms=(time.perf_counter() - started) * 1000.0,
            warnings=[str(exc)],
        )

    notes = tag_stem_notes(list(result.notes), stem_id=stem_id, backend=result.backend)
    midi_path = job_raw_stem_midi_path(source_path, job_id, stem_id)
    write_notes_to_midi(notes, midi_path, split_hands=False)
    return StemTranscription(
        stem_id=stem_id,
        notes=notes,
        midi_path=str(midi_path),
        backend=result.backend,
        duration_ms=(time.perf_counter() - started) * 1000.0,
    )


def default_stem_transcriber():
    return BasicPitchTranscriber()
