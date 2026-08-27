"""Experiment configuration objects (Checkpoint 9A).

These are independent of production settings. Production defaults are copied
into baseline configs for control comparison only — never written back.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Production defaults mirrored for baseline (adapters/basic_pitch_backend.py).
# DO NOT import and mutate production module state.
PRODUCTION_ONSET_THRESHOLD = 0.6
PRODUCTION_FRAME_THRESHOLD = 0.4
PRODUCTION_MIN_NOTE_LENGTH_MS = 127.70
PRODUCTION_MIN_FREQ_HZ = 27.5
PRODUCTION_MAX_FREQ_HZ = 2093.0
PRODUCTION_MELODIA_TRICK = True
PRODUCTION_MULTIPLE_PITCH_BENDS = False
PRODUCTION_SAMPLE_RATE = 22050
PRODUCTION_PEAK_TARGET = 0.95

# Supported Basic Pitch predict() kwargs (basic-pitch 0.4.0).
SUPPORTED_PREDICT_PARAMS = frozenset(
    {
        "onset_threshold",
        "frame_threshold",
        "minimum_note_length",
        "minimum_frequency",
        "maximum_frequency",
        "multiple_pitch_bends",
        "melodia_trick",
        "midi_tempo",
        "debug_file",
        "model_or_model_path",
    }
)


class UnsupportedParameterError(ValueError):
    """Raised when an experiment requests a Basic Pitch parameter that is not supported."""


@dataclass(frozen=True)
class PreprocessConfig:
    """Audio preprocessing for one experiment (opt-in, experiment-only)."""

    name: str
    mono: bool = True
    target_sr: int | None = None  # None = keep native sample rate
    peak_normalize: bool = False
    peak_target: float = PRODUCTION_PEAK_TARGET
    remove_dc: bool = False
    trim_silence: bool = False
    trim_top_db: float = 40.0
    # When True, apply the production AudioNormalizer path (mono+DC+22050+peak).
    use_production_normalizer: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def fingerprint(self) -> str:
        """Stable identity for redundancy detection."""
        if self.use_production_normalizer:
            return "production_normalizer"
        return (
            f"mono={self.mono}|sr={self.target_sr}|peak={self.peak_normalize}:"
            f"{self.peak_target}|dc={self.remove_dc}|trim={self.trim_silence}:"
            f"{self.trim_top_db}"
        )


@dataclass(frozen=True)
class TranscriptionParams:
    """Basic Pitch parameters for one experiment.

    Only parameters supported by basic_pitch.inference.predict are allowed.
    """

    onset_threshold: float = PRODUCTION_ONSET_THRESHOLD
    frame_threshold: float = PRODUCTION_FRAME_THRESHOLD
    minimum_note_length: float = PRODUCTION_MIN_NOTE_LENGTH_MS
    minimum_frequency: float = PRODUCTION_MIN_FREQ_HZ
    maximum_frequency: float = PRODUCTION_MAX_FREQ_HZ
    melodia_trick: bool = PRODUCTION_MELODIA_TRICK
    multiple_pitch_bends: bool = PRODUCTION_MULTIPLE_PITCH_BENDS

    def to_predict_kwargs(self) -> dict[str, Any]:
        kwargs = {
            "onset_threshold": float(self.onset_threshold),
            "frame_threshold": float(self.frame_threshold),
            "minimum_note_length": float(self.minimum_note_length),
            "minimum_frequency": float(self.minimum_frequency),
            "maximum_frequency": float(self.maximum_frequency),
            "melodia_trick": bool(self.melodia_trick),
            "multiple_pitch_bends": bool(self.multiple_pitch_bends),
        }
        unknown = set(kwargs) - SUPPORTED_PREDICT_PARAMS
        if unknown:
            raise UnsupportedParameterError(
                f"Unsupported Basic Pitch parameters: {sorted(unknown)}"
            )
        return kwargs

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptionParams":
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise UnsupportedParameterError(
                f"Unsupported transcription parameter keys: {sorted(unknown)}"
            )
        return cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})

    @classmethod
    def production(cls) -> "TranscriptionParams":
        return cls()


@dataclass(frozen=True)
class ExperimentConfig:
    """Named experiment: preprocessing + transcription parameters."""

    name: str
    axis: str  # baseline | audio | basic_pitch | combined | alternative
    description: str
    preprocess: PreprocessConfig
    transcription: TranscriptionParams = field(default_factory=TranscriptionParams.production)
    skip_reason: str | None = None
    parent_experiments: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "axis": self.axis,
            "description": self.description,
            "preprocess": self.preprocess.to_dict(),
            "transcription": self.transcription.to_dict(),
            "skip_reason": self.skip_reason,
            "parent_experiments": list(self.parent_experiments),
        }

    @property
    def is_skipped(self) -> bool:
        return bool(self.skip_reason)


def production_preprocess() -> PreprocessConfig:
    return PreprocessConfig(
        name="A0_production",
        use_production_normalizer=True,
        mono=True,
        target_sr=PRODUCTION_SAMPLE_RATE,
        peak_normalize=True,
        peak_target=PRODUCTION_PEAK_TARGET,
        remove_dc=True,
        trim_silence=False,
    )
