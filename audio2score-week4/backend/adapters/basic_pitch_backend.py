"""Basic Pitch backend adapter."""

from __future__ import annotations

from pathlib import Path

from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict

from mir.types import NoteEvent


class BasicPitchBackend:
    name = "basic_pitch"

    def transcribe_notes(self, audio_path: str | Path) -> list[NoteEvent]:
        _model_output, midi_data, note_events = predict(
            str(audio_path),
            model_or_model_path=ICASSP_2022_MODEL_PATH,
        )

        notes: list[NoteEvent] = []
        if note_events:
            for i, ev in enumerate(note_events):
                start, end, pitch, amp = ev[0], ev[1], ev[2], ev[3]
                amp = float(amp) if amp is not None else 0.5
                vel = int(min(127, max(1, round(amp * 127))))
                notes.append(
                    NoteEvent(
                        pitch=int(pitch),
                        start_time=float(start),
                        end_time=float(end),
                        velocity=vel,
                        confidence=max(0.0, min(1.0, amp)),
                        note_id=f"n{i:04d}",
                        source_backend=self.name,
                        original_start_time=float(start),
                        original_end_time=float(end),
                    )
                )
            return notes

        for inst in midi_data.instruments:
            for i, note in enumerate(inst.notes):
                vel = getattr(note, "velocity", 64) or 64
                notes.append(
                    NoteEvent(
                        pitch=int(note.pitch),
                        start_time=float(note.start),
                        end_time=float(note.end),
                        velocity=int(vel),
                        confidence=1.0,
                        note_id=f"n{len(notes):04d}",
                        source_backend=self.name,
                        original_start_time=float(note.start),
                        original_end_time=float(note.end),
                    )
                )
        return notes
