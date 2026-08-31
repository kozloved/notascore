"""Environment-configurable Gemini / analysis-layer settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from mir.pipeline_config import gemini_flag_enabled


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


# USD per 1M tokens. Audio billed at 32 tokens/sec on Gemini.
# Source: https://ai.google.dev/gemini-api/docs/pricing (Aug 2026)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash-lite": {
        "text_input": 0.10,
        "audio_input": 0.30,
        "output": 0.40,
    },
    "gemini-2.5-flash": {
        "text_input": 0.30,
        "audio_input": 1.00,
        "output": 2.50,
    },
    "gemini-3.5-flash-lite": {
        "text_input": 0.30,
        "audio_input": 0.30,
        "output": 2.50,
    },
    "gemini-3.1-flash-lite": {
        "text_input": 0.25,
        "audio_input": 0.50,
        "output": 2.50,
    },
    "gemini-3.6-flash": {
        "text_input": 1.50,
        "audio_input": 1.50,
        "output": 7.50,
    },
}

AUDIO_TOKENS_PER_SECOND = 32.0
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_REASONING_MODEL = "gemini-2.5-flash"


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str
    provider: str
    enabled: bool
    audio_input: bool
    deep_analysis: bool
    midi_validation: bool
    structure_analysis: bool
    default_model: str
    reasoning_model: str
    auto_apply_threshold: float
    deep_analysis_threshold: float
    manual_review_threshold: float
    max_drop_fraction: float
    cache_ttl_seconds: int
    cache_dir: Path
    timeout_seconds: int
    max_audio_seconds: float

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def active(self) -> bool:
        return self.enabled and self.configured


def gemini_config() -> GeminiConfig:
    enabled = gemini_flag_enabled()
    cache_root = Path(os.getenv("TEMP_DIR", ".tmp"))
    return GeminiConfig(
        api_key=_env_str("GEMINI_API_KEY", ""),
        provider=_env_str("MUSIC_ANALYSIS_PROVIDER", "gemini").lower(),
        enabled=enabled,
        audio_input=_env_bool("ENABLE_GEMINI_AUDIO_INPUT", default=True),
        deep_analysis=_env_bool("ENABLE_GEMINI_DEEP_ANALYSIS")
        or _env_bool("GEMINI_DEEP_ANALYSIS_ENABLED"),
        midi_validation=_env_bool("ENABLE_GEMINI_MIDI_VALIDATION", default=True),
        structure_analysis=_env_bool(
            "ENABLE_GEMINI_STRUCTURE_ANALYSIS", default=True
        ),
        default_model=_env_str("GEMINI_DEFAULT_MODEL", DEFAULT_MODEL),
        reasoning_model=_env_str(
            "GEMINI_REASONING_MODEL", DEFAULT_REASONING_MODEL
        ),
        auto_apply_threshold=_env_float("GEMINI_AUTO_APPLY_THRESHOLD", 0.55),
        deep_analysis_threshold=_env_float(
            "GEMINI_DEEP_ANALYSIS_THRESHOLD", 0.60
        ),
        manual_review_threshold=_env_float(
            "GEMINI_MANUAL_REVIEW_THRESHOLD", 0.75
        ),
        max_drop_fraction=_env_float("GEMINI_MAX_DROP_FRACTION", 0.25),
        cache_ttl_seconds=_env_int("GEMINI_CACHE_TTL_SECONDS", 7 * 24 * 3600),
        cache_dir=cache_root / "gemini-cache",
        timeout_seconds=_env_int("GEMINI_TIMEOUT_SECONDS", 180),
        max_audio_seconds=_env_float("GEMINI_MAX_AUDIO_SECONDS", 60.0),
    )


def pricing_for(model: str) -> dict[str, float]:
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    if "flash-lite" in model:
        return MODEL_PRICING["gemini-2.5-flash-lite"]
    if "flash" in model:
        return MODEL_PRICING["gemini-2.5-flash"]
    return MODEL_PRICING[DEFAULT_MODEL]


def gemini_status(cfg: GeminiConfig | None = None) -> dict:
    cfg = cfg or gemini_config()
    return {
        "enabled": cfg.enabled,
        "configured": cfg.configured,
        "active": cfg.active,
        "provider": cfg.provider,
        "default_model": cfg.default_model,
        "reasoning_model": cfg.reasoning_model,
        "audio_input": cfg.audio_input,
        "deep_analysis": cfg.deep_analysis,
        "midi_validation": cfg.midi_validation,
        "structure_analysis": cfg.structure_analysis,
    }
