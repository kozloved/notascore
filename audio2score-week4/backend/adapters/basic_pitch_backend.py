"""Basic Pitch backend adapter."""

from __future__ import annotations

from pathlib import Path

from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict

from mir.types import NoteEvent


class BasicPitchBackend:
    name = "basic_pitch"

    def transcribe_notes(self, audio_path: str | Path) -> list[NoteEvent]:
        _, midi_data, _ = predict(
            str(audio_path),
            model_or_model_path=ICASSP_2022_MODEL_PATH,
        )

        notes: list[NoteEvent] = []
        for inst in midi_data.instruments:
            for note in inst.notes:
                vel = getattr(note, "velocity", 64) or 64
                notes.append(
                    NoteEvent(
                        pitch=int(note.pitch),
                        start_time=float(note.start),
                        end_time=float(note.end),
                        velocity=int(vel),
                        confidence=1.0,
                    )
                )
        return notes
