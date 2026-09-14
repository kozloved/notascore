"""Basic Pitch backend adapter."""

from __future__ import annotations

import os
from pathlib import Path

from mir.types import NoteEvent


def predict(*args, **kwargs):
    """Load the audio model only for audio work, never for MIDI interpretation."""
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict as run_predict

    kwargs.setdefault("model_or_model_path", ICASSP_2022_MODEL_PATH)
    return run_predict(*args, **kwargs)

# Piano-oriented Fast defaults: fewer ghost onsets, drop twitter octaves above C7.
# A sixteenth at 120 BPM is 125 ms, so production min-length (127.70 ms) can
# drop short notes. Named profiles exist for comparison; production stays put
# until a measured inference run justifies a change.
DEFAULT_ONSET_THRESHOLD = 0.6
DEFAULT_FRAME_THRESHOLD = 0.4
DEFAULT_MIN_NOTE_LENGTH_MS = 127.70
DEFAULT_MIN_FREQ_HZ = 27.5  # A0
DEFAULT_MAX_FREQ_HZ = 2093.0  # C7
PRODUCTION_PROFILE = "production"
INFERENCE_SETTING_KEYS = (
    "onset_threshold",
    "frame_threshold",
    "minimum_note_length",
    "minimum_frequency",
    "maximum_frequency",
    "melodia_trick",
    "multiple_pitch_bends",
)

BASIC_PITCH_PROFILES: dict[str, dict] = {
    "production": {
        "onset_threshold": DEFAULT_ONSET_THRESHOLD,
        "frame_threshold": DEFAULT_FRAME_THRESHOLD,
        "minimum_note_length": DEFAULT_MIN_NOTE_LENGTH_MS,
        "minimum_frequency": DEFAULT_MIN_FREQ_HZ,
        "maximum_frequency": DEFAULT_MAX_FREQ_HZ,
        "melodia_trick": True,
        "multiple_pitch_bends": False,
    },
    # Comparison-only. Not used in production unless BASIC_PITCH_PROFILE is set.
    "short_notes": {
        "onset_threshold": DEFAULT_ONSET_THRESHOLD,
        "frame_threshold": DEFAULT_FRAME_THRESHOLD,
        "minimum_note_length": 40.0,
        "minimum_frequency": DEFAULT_MIN_FREQ_HZ,
        "maximum_frequency": DEFAULT_MAX_FREQ_HZ,
        "melodia_trick": True,
        "multiple_pitch_bends": False,
    },
    "piano_extended": {
        "onset_threshold": DEFAULT_ONSET_THRESHOLD,
        "frame_threshold": DEFAULT_FRAME_THRESHOLD,
        "minimum_note_length": DEFAULT_MIN_NOTE_LENGTH_MS,
        "minimum_frequency": DEFAULT_MIN_FREQ_HZ,
        "maximum_frequency": 4186.0,  # C8
        "melodia_trick": True,
        "multiple_pitch_bends": False,
    },
    "bass": {
        "onset_threshold": DEFAULT_ONSET_THRESHOLD,
        "frame_threshold": DEFAULT_FRAME_THRESHOLD,
        "minimum_note_length": DEFAULT_MIN_NOTE_LENGTH_MS,
        "minimum_frequency": 27.5,  # A0
        "maximum_frequency": 392.0,  # G4
        "melodia_trick": True,
        "multiple_pitch_bends": False,
    },
    "quiet_passages": {
        "onset_threshold": 0.4,
        "frame_threshold": 0.25,
        "minimum_note_length": DEFAULT_MIN_NOTE_LENGTH_MS,
        "minimum_frequency": DEFAULT_MIN_FREQ_HZ,
        "maximum_frequency": DEFAULT_MAX_FREQ_HZ,
        "melodia_trick": True,
        "multiple_pitch_bends": False,
    },
    "ornaments": {
        "onset_threshold": 0.45,
        "frame_threshold": 0.3,
        "minimum_note_length": 30.0,
        "minimum_frequency": DEFAULT_MIN_FREQ_HZ,
        "maximum_frequency": DEFAULT_MAX_FREQ_HZ,
        "melodia_trick": True,
        "multiple_pitch_bends": False,
    },
}

# Optional per-stem hints. Off unless BASIC_PITCH_STEM_PROFILES=1.
STEM_PROFILE_HINTS = {
    "bass": "bass",
    "piano": "piano_extended",
    "vocals": "short_notes",
    "guitar": "short_notes",
    "other": "production",
}

_ENV_OVERLAYS = (
    ("BASIC_PITCH_ONSET_THRESHOLD", "onset_threshold", float),
    ("BASIC_PITCH_FRAME_THRESHOLD", "frame_threshold", float),
    ("BASIC_PITCH_MIN_NOTE_LENGTH_MS", "minimum_note_length", float),
    ("BASIC_PITCH_MIN_FREQ_HZ", "minimum_frequency", float),
    ("BASIC_PITCH_MAX_FREQ_HZ", "maximum_frequency", float),
    ("BASIC_PITCH_MELODIA_TRICK", "melodia_trick", bool),
    ("BASIC_PITCH_MULTIPLE_PITCH_BENDS", "multiple_pitch_bends", bool),
)


def _env_bool_value(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return _env_bool_value(raw)


def resolve_basic_pitch_profile(profile: str | None = None) -> str:
    raw = (profile or os.getenv("BASIC_PITCH_PROFILE") or PRODUCTION_PROFILE).strip().lower()
    if raw not in BASIC_PITCH_PROFILES:
        return PRODUCTION_PROFILE
    return raw


def stem_profiles_enabled() -> bool:
    return _env_bool("BASIC_PITCH_STEM_PROFILES", False)


def profile_for_stem(stem_id: str | None) -> str | None:
    """Return a comparison profile name for a stem, or None when unused."""
    if not stem_profiles_enabled():
        return None
    return STEM_PROFILE_HINTS.get((stem_id or "").strip().lower())


def basic_pitch_settings(profile: str | None = None) -> dict:
    """Effective Basic Pitch settings. Production defaults are unchanged.

    Named profiles supply comparison baselines. Documented BASIC_PITCH_*
    environment variables overlay the selected profile and are recorded.
    """
    name = resolve_basic_pitch_profile(profile)
    settings = dict(BASIC_PITCH_PROFILES[name])
    env_overrides: dict[str, float | bool] = {}
    for env_name, key, caster in _ENV_OVERLAYS:
        raw = os.getenv(env_name)
        if raw is None or str(raw).strip() == "":
            continue
        value = _env_bool_value(raw) if caster is bool else float(raw)
        settings[key] = value
        env_overrides[env_name] = value
    settings["profile"] = name
    settings["env_overrides"] = env_overrides
    return settings


def inference_settings(settings: dict | None = None) -> dict:
    payload = settings or basic_pitch_settings()
    return {key: payload[key] for key in INFERENCE_SETTING_KEYS}


def _velocity_from_amplitude(amplitude: float) -> int:
    amp = float(amplitude)
    if amp > 1.0:
        # Already a MIDI velocity (tests / alternate backends).
        return max(1, min(127, int(round(amp))))
    return max(1, min(127, int(round(127.0 * amp))))


class BasicPitchBackend:
    name = "basic_pitch"

    def __init__(self):
        self.last_result = None
        self.last_settings = None
        self.last_timing = None
        self.last_midi_bytes = None
        self.last_provider_raw_sha256 = None
        self.last_performance = None
        self.last_provider_job_id = None

    def transcribe_result(self, audio_path: str | Path):
        notes = self.transcribe_notes(audio_path)
        from mir.models import TranscriptionResult

        result = getattr(self, "last_result", None)
        if isinstance(result, TranscriptionResult):
            return result
        from mir.transcription_contract import result_from_backend_state

        return result_from_backend_state(self, notes, audio_path)

    def transcribe_notes(self, audio_path: str | Path, profile: str | None = None) -> list[NoteEvent]:
        from mir.models import TranscriptionResult

        settings = basic_pitch_settings(profile)
        self.last_settings = dict(settings)
        infer = inference_settings(settings)
        print(
            "[BasicPitch] "
            f"profile={settings['profile']} "
            f"onset={infer['onset_threshold']:.2f} "
            f"frame={infer['frame_threshold']:.2f} "
            f"min_ms={infer['minimum_note_length']:.1f} "
            f"band={infer['minimum_frequency']:.1f}-{infer['maximum_frequency']:.1f}Hz "
            f"melodia={infer['melodia_trick']}"
        )

        _, midi_data, note_events = predict(
            str(audio_path),
            onset_threshold=infer["onset_threshold"],
            frame_threshold=infer["frame_threshold"],
            minimum_note_length=infer["minimum_note_length"],
            minimum_frequency=infer["minimum_frequency"],
            maximum_frequency=infer["maximum_frequency"],
            multiple_pitch_bends=infer["multiple_pitch_bends"],
            melodia_trick=infer["melodia_trick"],
        )

        notes: list[NoteEvent] = []
        if note_events:
            for i, item in enumerate(note_events):
                start_time, end_time, pitch, amplitude = (
                    item[0],
                    item[1],
                    item[2],
                    item[3],
                )
                amp = 0.5 if amplitude is None else float(amplitude)
                vel = _velocity_from_amplitude(amp)
                # Amplitude is a model score, not calibrated confidence.
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
                        model_score=float(amp),
                        confidence_source="amplitude",
                    )
                )
        elif midi_data is not None:
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
                            model_score=None,
                            confidence_source="velocity",
                        )
                    )

        self.last_result = TranscriptionResult(
            notes=list(notes),
            backend=self.name,
            requested_backend=self.name,
            actual_backend=self.name,
            original_notes=list(notes),
            audio_path=str(audio_path),
            settings=dict(settings),
        )
        return notes
