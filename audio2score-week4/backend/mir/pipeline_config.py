"""Canonical production-path configuration.

One obvious path:

    AUDIO → transcription backend → RAW MIDI
          → source-aware validation → VALIDATED MIDI
          → musical interpretation → notation quantization
          → MusicXML / score MIDI

Legacy flags remain readable so existing deploys keep working.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ValidationMode(str, Enum):
    """How aggressively MIDICleaner may mutate transcription notes."""

    STRICT_SAFE = "strict_safe"
    CONSERVATIVE = "conservative"
    LEGACY_AGGRESSIVE = "legacy_aggressive"


class QuantizationMode(str, Enum):
    PERFORMANCE = "performance"
    ADAPTIVE = "adaptive"
    STRICT_GRID = "strict_grid"
    OFF = "off"
    PM2S = "pm2s"


class HandSeparatorMode(str, Enum):
    """How piano notes are assigned to left / right staves."""

    VITERBI = "viterbi"
    PM2S = "pm2s"


VALIDATION_ALIASES = {
    "safe": ValidationMode.STRICT_SAFE,
    "strict": ValidationMode.STRICT_SAFE,
    "strict_safe": ValidationMode.STRICT_SAFE,
    "mvp": ValidationMode.STRICT_SAFE,
    "conservative": ValidationMode.CONSERVATIVE,
    "legacy": ValidationMode.LEGACY_AGGRESSIVE,
    "legacy_aggressive": ValidationMode.LEGACY_AGGRESSIVE,
    "aggressive": ValidationMode.LEGACY_AGGRESSIVE,
}

HAND_SEPARATOR_ALIASES = {
    "viterbi": HandSeparatorMode.VITERBI,
    "default": HandSeparatorMode.VITERBI,
    "context": HandSeparatorMode.VITERBI,
    "dp": HandSeparatorMode.VITERBI,
    # Known production mix-up with TRANSCRIPTION_QUANTIZATION_MODE=performance.
    "performance": HandSeparatorMode.VITERBI,
    "pm2s": HandSeparatorMode.PM2S,
    "pm25": HandSeparatorMode.PM2S,
    "pm2s_hands": HandSeparatorMode.PM2S,
}

QUANTIZATION_ALIASES = {
    "performance": QuantizationMode.PERFORMANCE,
    "adaptive": QuantizationMode.ADAPTIVE,
    "notation": QuantizationMode.ADAPTIVE,
    "strict": QuantizationMode.STRICT_GRID,
    "strict_grid": QuantizationMode.STRICT_GRID,
    "grid": QuantizationMode.STRICT_GRID,
    "off": QuantizationMode.OFF,
    "none": QuantizationMode.OFF,
    "identity": QuantizationMode.OFF,
    "raw": QuantizationMode.OFF,
    "disabled": QuantizationMode.OFF,
    "0": QuantizationMode.OFF,
    "false": QuantizationMode.OFF,
    "pm2s": QuantizationMode.PM2S,
    "pm25": QuantizationMode.PM2S,
    "pm2s_quant": QuantizationMode.PM2S,
    "neural": QuantizationMode.PM2S,
}

# Source-aware MVP defaults. MT3 is treated as the pitch/timing source of truth.
DEFAULT_VALIDATION_BY_BACKEND = {
    "mt3": ValidationMode.STRICT_SAFE,
    "basic_pitch": ValidationMode.CONSERVATIVE,
    "classical_dsp": ValidationMode.CONSERVATIVE,
    "midi": ValidationMode.STRICT_SAFE,
}


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def env_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip()


def _flag_with_alias(canonical: str, legacy: str, *, default: bool) -> bool:
    """Prefer the new name when set; otherwise the legacy name."""
    raw = os.getenv(canonical)
    if raw is not None and str(raw).strip() != "":
        return env_bool(canonical, default=default)
    return env_bool(legacy, default=default)


def parse_validation_mode(value: str | ValidationMode | None) -> ValidationMode | None:
    if value is None:
        return None
    if isinstance(value, ValidationMode):
        return value
    key = str(value).strip().lower()
    if not key:
        return None
    if key not in VALIDATION_ALIASES:
        raise ValueError(
            f"Unknown TRANSCRIPTION_VALIDATION_MODE={value!r}. "
            "Use safe | conservative | legacy_aggressive."
        )
    return VALIDATION_ALIASES[key]


def parse_quantization_mode(value: str | QuantizationMode | None) -> QuantizationMode:
    if value is None or str(value).strip() == "":
        return QuantizationMode.PERFORMANCE
    if isinstance(value, QuantizationMode):
        return value
    key = str(value).strip().lower()
    if key not in QUANTIZATION_ALIASES:
        raise ValueError(
            f"Unknown TRANSCRIPTION_QUANTIZATION_MODE={value!r}. "
            "Use performance | adaptive | strict_grid | off | pm2s."
        )
    return QUANTIZATION_ALIASES[key]


def quantization_skips_legacy_grid(mode: QuantizationMode) -> bool:
    """OFF keeps raw beats. PM2S already rewrote beats in MeasureQuantizer."""
    return mode in (QuantizationMode.OFF, QuantizationMode.PM2S, QuantizationMode.PERFORMANCE)


def quantization_spells_writable(mode: QuantizationMode) -> bool:
    """Spell MusicXML with tied 64th-based note types instead of a 16th grid."""
    return mode in (QuantizationMode.OFF, QuantizationMode.PM2S)


def quantization_snaps_display_tempo(mode: QuantizationMode) -> bool:
    return mode in (QuantizationMode.ADAPTIVE, QuantizationMode.STRICT_GRID)


def pm2s_required() -> bool:
    """When true, missing PM2S weights/imports fail the job instead of falling back."""
    return env_bool("TRANSCRIPTION_PM2S_REQUIRED", default=False)


def parse_hand_separator_mode(
    value: str | HandSeparatorMode | None,
) -> HandSeparatorMode:
    """Strict parse. `performance` is a compatibility alias for viterbi.

    Unknown values raise. Health and job loaders must catch that and keep
    HTTP 200 / a documented viterbi fallback with an explicit error string.
    """
    if value is None or str(value).strip() == "":
        return HandSeparatorMode.VITERBI
    if isinstance(value, HandSeparatorMode):
        return value
    key = str(value).strip().lower()
    if key == "performance":
        print(
            "[config] TRANSCRIPTION_HAND_SEPARATOR='performance' is a "
            "quantization mode; using viterbi. Set "
            "TRANSCRIPTION_QUANTIZATION_MODE=performance instead."
        )
        return HandSeparatorMode.VITERBI
    if key not in HAND_SEPARATOR_ALIASES:
        raise ValueError(
            f"Unknown TRANSCRIPTION_HAND_SEPARATOR={value!r}. "
            "Use viterbi | pm2s."
        )
    return HAND_SEPARATOR_ALIASES[key]


def inspect_hand_separator_env() -> dict[str, Any]:
    """Health-safe snapshot. Never raises."""
    raw = env_str("TRANSCRIPTION_HAND_SEPARATOR", "viterbi")
    warning = None
    error = None
    try:
        mode = parse_hand_separator_mode(raw)
        if (raw or "").strip().lower() == "performance":
            warning = (
                "TRANSCRIPTION_HAND_SEPARATOR='performance' aliased to viterbi"
            )
    except ValueError as exc:
        mode = HandSeparatorMode.VITERBI
        error = str(exc)
    return {
        "valid": error is None,
        "error": error,
        "warning": warning,
        "raw": raw or "viterbi",
        "effective_hand_separator": mode.value,
    }


def resolve_validation_mode(
    source_backend: str | None = None,
    explicit: str | ValidationMode | None = None,
) -> ValidationMode:
    """Caller override, then env, then source-aware default."""
    parsed = parse_validation_mode(explicit)
    if parsed is not None:
        return parsed
    env_mode = parse_validation_mode(env_str("TRANSCRIPTION_VALIDATION_MODE", ""))
    if env_mode is not None:
        return env_mode
    backend = (source_backend or "basic_pitch").strip().lower()
    return DEFAULT_VALIDATION_BY_BACKEND.get(backend, ValidationMode.CONSERVATIVE)


def gemini_explicitly_disabled() -> bool:
    raw = os.getenv("TRANSCRIPTION_ENABLE_GEMINI")
    if raw is None or str(raw).strip() == "":
        return False
    return str(raw).strip().lower() in ("0", "false", "no", "off")


def gemini_flag_enabled() -> bool:
    """Canonical Gemini switch. Off unless an enable flag is set."""
    if gemini_explicitly_disabled():
        return False
    return (
        env_bool("TRANSCRIPTION_ENABLE_GEMINI")
        or env_bool("ENABLE_GEMINI_MUSIC_ANALYSIS")
        or env_bool("GEMINI_ENABLED")
    )


def piano_analysis_enabled(source_backend: str | None) -> bool:
    """MT3 velocities are model output; do not overwrite them by default."""
    if not env_bool("TRANSCRIPTION_USE_PIANO_ANALYZER", default=True):
        return False
    backend = (source_backend or "").strip().lower()
    explicit = os.getenv("TRANSCRIPTION_ENABLE_PIANO_ANALYSIS")
    if explicit is not None and str(explicit).strip() != "":
        return env_bool("TRANSCRIPTION_ENABLE_PIANO_ANALYSIS")
    if backend == "mt3":
        return False
    return True


@dataclass(frozen=True)
class PipelineConfig:
    """Resolved production path for one job."""

    pipeline: str = "understanding"
    backend: str = "basic_pitch"
    mode: str = "solo"
    validation_mode: ValidationMode = ValidationMode.CONSERVATIVE
    quantization_mode: QuantizationMode = QuantizationMode.PERFORMANCE
    hand_separator: HandSeparatorMode = HandSeparatorMode.VITERBI
    pm2s_required: bool = False
    enable_gemini: bool = False
    enable_piano_analysis: bool = True
    enable_mir_layers: bool = True
    enable_normalizer: bool = True
    enable_beat_tracker: bool = True
    pipeline_fallback: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline": self.pipeline,
            "backend": self.backend,
            "mode": self.mode,
            "validation_mode": self.validation_mode.value,
            "quantization_mode": self.quantization_mode.value,
            "hand_separator": self.hand_separator.value,
            "pm2s_required": self.pm2s_required,
            "enable_gemini": self.enable_gemini,
            "enable_piano_analysis": self.enable_piano_analysis,
            "enable_mir_layers": self.enable_mir_layers,
            "enable_normalizer": self.enable_normalizer,
            "enable_beat_tracker": self.enable_beat_tracker,
            "pipeline_fallback": self.pipeline_fallback,
        }


def load_pipeline_config(
    *,
    backend: str | None = None,
    mode: str = "solo",
    validation_mode: str | ValidationMode | None = None,
) -> PipelineConfig:
    resolved_backend = (backend or env_str("TRANSCRIPTION_BACKEND", "basic_pitch")).lower()
    hands = inspect_hand_separator_env()
    extra: dict[str, Any] = {}
    if hands["error"]:
        extra["hand_separator_error"] = hands["error"]
        extra["hand_separator_fallback"] = "viterbi"
        print(f"[config] {hands['error']}; using viterbi for this process.")
    if hands["warning"]:
        extra["hand_separator_warning"] = hands["warning"]
    return PipelineConfig(
        pipeline=env_str("TRANSCRIPTION_PIPELINE", "understanding").lower(),
        backend=resolved_backend,
        mode=mode,
        validation_mode=resolve_validation_mode(resolved_backend, validation_mode),
        quantization_mode=parse_quantization_mode(
            env_str("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
        ),
        hand_separator=HandSeparatorMode(hands["effective_hand_separator"]),
        pm2s_required=pm2s_required(),
        enable_gemini=gemini_flag_enabled(),
        enable_piano_analysis=piano_analysis_enabled(resolved_backend),
        enable_mir_layers=_flag_with_alias(
            "TRANSCRIPTION_ENABLE_MIR_LAYERS",
            "TRANSCRIPTION_USE_MIR_LAYERS",
            default=True,
        ),
        enable_normalizer=env_bool("TRANSCRIPTION_USE_NORMALIZER", default=True),
        enable_beat_tracker=env_bool("TRANSCRIPTION_USE_BEAT_TRACKER", default=True),
        pipeline_fallback=env_bool("TRANSCRIPTION_PIPELINE_FALLBACK", default=True),
        extra=extra,
    )
