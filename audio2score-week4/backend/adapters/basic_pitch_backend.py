"""Basic Pitch backend adapter."""

from __future__ import annotations

import os
from pathlib import Path

from basic_pitch import ICASSP_2022_MODEL_PATH
from basic_pitch.inference import predict

from mir.types import NoteEvent

# Piano-oriented Fast defaults: fewer ghost onsets, drop twitter octaves above C7.
DEFAULT_ONSET_THRESHOLD = 0.6
DEFAULT_FRAME_THRESHOLD = 0.4
DEFAULT_MIN_NOTE_LENGTH_MS = 127.70
DEFAULT_MIN_FREQ_HZ = 27.5  # A0
DEFAULT_MAX_FREQ_HZ = 2093.0  # C7


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes")


def basic_pitch_settings() -> dict:
    return {
        "onset_threshold": _env_float(
            "BASIC_PITCH_ONSET_THRESHOLD", DEFAULT_ONSET_THRESHOLD
        ),
        "frame_threshold": _env_float(
            "BASIC_PITCH_FRAME_THRESHOLD", DEFAULT_FRAME_THRESHOLD
        ),
        "minimum_note_length": _env_float(
            "BASIC_PITCH_MIN_NOTE_LENGTH_MS", DEFAULT_MIN_NOTE_LENGTH_MS
        ),
        "minimum_frequency": _env_float(
            "BASIC_PITCH_MIN_FREQ_HZ", DEFAULT_MIN_FREQ_HZ
        ),
        "maximum_frequency": _env_float(
            "BASIC_PITCH_MAX_FREQ_HZ", DEFAULT_MAX_FREQ_HZ
        ),
        "melodia_trick": _env_bool("BASIC_PITCH_MELODIA_TRICK", True),
        "multiple_pitch_bends": _env_bool("BASIC_PITCH_MULTIPLE_PITCH_BENDS", False),
    }


def _velocity_from_amplitude(amplitude: float) -> int:
    amp = float(amplitude)
    if amp > 1.0:
        # Already a MIDI velocity (tests / alternate backends).
        return max(1, min(127, int(round(amp))))
    return max(1, min(127, int(round(127.0 * amp))))


class BasicPitchBackend:
    name = "basic_pitch"

    def transcribe_notes(self, audio_path: str | Path) -> list[NoteEvent]:
        settings = basic_pitch_settings()
        print(
            "[BasicPitch] "
            f"onset={settings['onset_threshold']:.2f} "
            f"frame={settings['frame_threshold']:.2f} "
            f"min_ms={settings['minimum_note_length']:.1f} "
            f"band={settings['minimum_frequency']:.1f}-{settings['maximum_frequency']:.1f}Hz "
            f"melodia={settings['melodia_trick']}"
        )

        _, midi_data, note_events = predict(
            str(audio_path),
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=settings["onset_threshold"],
            frame_threshold=settings["frame_threshold"],
            minimum_note_length=settings["minimum_note_length"],
            minimum_frequency=settings["minimum_frequency"],
            maximum_frequency=settings["maximum_frequency"],
            multiple_pitch_bends=settings["multiple_pitch_bends"],
            melodia_trick=settings["melodia_trick"],
        )

        if note_events:
            notes: list[NoteEvent] = []
            for i, item in enumerate(note_events):
                start_time, end_time, pitch, amplitude = (
                    item[0],
                    item[1],
                    item[2],
                    item[3],
                )
                amp = 0.5 if amplitude is None else float(amplitude)
                vel = _velocity_from_amplitude(amp)
                confidence = amp if 0.0 <= amp <= 1.0 else vel / 127.0
                notes.append(
                    NoteEvent(
                        pitch=int(pitch),
                        start_time=float(start_time),
                        end_time=float(end_time),
                        velocity=vel,
                        confidence=float(confidence),
                        note_id=f"n{i:04d}",
                        source_backend=self.name,
                        original_start_time=float(start_time),
                        original_end_time=float(end_time),
                    )
                )
            return notes

        notes = []
        if midi_data is None:
            return notes
        for inst in midi_data.instruments:
            for note in inst.notes:
                vel = getattr(note, "velocity", 64) or 64
                vel = max(1, min(127, int(vel)))
                notes.append(
                    NoteEvent(
                        pitch=int(note.pitch),
                        start_time=float(note.start),
                        end_time=float(note.end),
                        velocity=vel,
                        confidence=vel / 127.0,
                        note_id=f"n{len(notes):04d}",
                        source_backend=self.name,
                        original_start_time=float(note.start),
                        original_end_time=float(note.end),
                    )
                )
        return notes
