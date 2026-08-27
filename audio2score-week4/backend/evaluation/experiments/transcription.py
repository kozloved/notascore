"""Experiment-only Basic Pitch transcription adapter (Checkpoint 9A).

Does NOT modify production BasicPitchBackend or env-driven settings.
Parameters are passed explicitly per ExperimentConfig.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evaluation.experiments.config import (
    SUPPORTED_PREDICT_PARAMS,
    TranscriptionParams,
    UnsupportedParameterError,
)
from mir.types import NoteEvent


def basic_pitch_version() -> str | None:
    try:
        import importlib.metadata

        return importlib.metadata.version("basic-pitch")
    except Exception:
        try:
            import basic_pitch

            return getattr(basic_pitch, "__version__", None)
        except Exception:
            return None


def validate_predict_params(params: dict[str, Any]) -> dict[str, Any]:
    """Reject unsupported Basic Pitch parameters (no silent substitution)."""
    unknown = set(params) - SUPPORTED_PREDICT_PARAMS
    if unknown:
        raise UnsupportedParameterError(
            f"Unsupported Basic Pitch parameters: {sorted(unknown)}. "
            f"Supported: {sorted(SUPPORTED_PREDICT_PARAMS)}"
        )
    return params


@dataclass
class TranscriptionResult:
    notes: list[NoteEvent]
    params: dict[str, Any]
    audio_path: str
    basic_pitch_version: str | None
    note_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_count": self.note_count,
            "params": self.params,
            "audio_path": self.audio_path,
            "basic_pitch_version": self.basic_pitch_version,
        }


def _velocity_from_amplitude(amplitude: float) -> int:
    amp = float(amplitude)
    if amp > 1.0:
        return max(1, min(127, int(round(amp))))
    return max(1, min(127, int(round(127.0 * amp))))


def _notes_from_events(note_events: list, *, backend_name: str) -> list[NoteEvent]:
    notes: list[NoteEvent] = []
    for i, item in enumerate(note_events):
        start_time, end_time, pitch, amplitude = item[0], item[1], item[2], item[3]
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
                source_backend=backend_name,
                original_start_time=float(start_time),
                original_end_time=float(end_time),
            )
        )
    return notes


def _notes_from_pretty_midi(midi_data, *, backend_name: str) -> list[NoteEvent]:
    notes: list[NoteEvent] = []
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
                    source_backend=backend_name,
                    original_start_time=float(note.start),
                    original_end_time=float(note.end),
                )
            )
    return notes


class ExperimentBasicPitchAdapter:
    """Diagnostic adapter: explicit params only; never reads BASIC_PITCH_* env."""

    name = "experiment_basic_pitch"

    def transcribe(
        self,
        audio_path: str | Path,
        params: TranscriptionParams | dict[str, Any] | None = None,
    ) -> TranscriptionResult:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import predict

        if params is None:
            tp = TranscriptionParams.production()
            kwargs = tp.to_predict_kwargs()
        elif isinstance(params, TranscriptionParams):
            kwargs = params.to_predict_kwargs()
        else:
            kwargs = validate_predict_params(dict(params))

        path = str(audio_path)
        _, midi_data, note_events = predict(
            path,
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            **kwargs,
        )
        if note_events:
            notes = _notes_from_events(note_events, backend_name=self.name)
        else:
            notes = _notes_from_pretty_midi(midi_data, backend_name=self.name)

        return TranscriptionResult(
            notes=notes,
            params=dict(kwargs),
            audio_path=path,
            basic_pitch_version=basic_pitch_version(),
            note_count=len(notes),
        )


def production_settings_snapshot() -> dict[str, Any]:
    """Read-only snapshot of production settings for isolation tests."""
    from adapters.basic_pitch_backend import (
        DEFAULT_FRAME_THRESHOLD,
        DEFAULT_MAX_FREQ_HZ,
        DEFAULT_MIN_FREQ_HZ,
        DEFAULT_MIN_NOTE_LENGTH_MS,
        DEFAULT_ONSET_THRESHOLD,
        basic_pitch_settings,
    )

    return {
        "module_defaults": {
            "onset_threshold": DEFAULT_ONSET_THRESHOLD,
            "frame_threshold": DEFAULT_FRAME_THRESHOLD,
            "minimum_note_length": DEFAULT_MIN_NOTE_LENGTH_MS,
            "minimum_frequency": DEFAULT_MIN_FREQ_HZ,
            "maximum_frequency": DEFAULT_MAX_FREQ_HZ,
        },
        "env_resolved": basic_pitch_settings(),
    }
