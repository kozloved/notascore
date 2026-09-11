"""Feature flags for next-gen stages. Defaults keep production on the current path."""

from __future__ import annotations

from mir.pipeline_config import _flag_with_alias, env_bool, env_str

PIPELINE_MODE_LEGACY = "legacy"
PIPELINE_MODE_SHADOW = "shadow"
PIPELINE_MODE_LIVE = "live"
PIPELINE_MODES = (PIPELINE_MODE_LEGACY, PIPELINE_MODE_SHADOW, PIPELINE_MODE_LIVE)


def pipeline_mode() -> str:
    """Production cutover: legacy (default), shadow, or live."""
    raw = env_str("NEXTGEN_PIPELINE_MODE", PIPELINE_MODE_LEGACY).strip().lower()
    if raw in PIPELINE_MODES:
        return raw
    return PIPELINE_MODE_LEGACY


def separation_enabled() -> bool:
    return _flag_with_alias("NEXTGEN_SEPARATION_ENABLED", "NEXTGEN_SEPARATION", default=False)


def stem_transcription_enabled() -> bool:
    return env_bool("NEXTGEN_STEM_TRANSCRIPTION_ENABLED", default=False)


def fusion_enabled() -> bool:
    return env_bool("NEXTGEN_FUSION_ENABLED", default=False)


def transkun_enabled() -> bool:
    return env_bool("NEXTGEN_TRANSKUN", default=False)


def beat_this_enabled() -> bool:
    return env_bool("NEXTGEN_BEAT_THIS", default=False)


def ensemble_render_enabled() -> bool:
    return env_bool("NEXTGEN_ENSEMBLE_RENDER", default=False)


def write_manifest_enabled() -> bool:
    return env_bool("NEXTGEN_WRITE_MANIFEST", default=True)


def transkun_checkpoint() -> str:
    return env_str("NEXTGEN_TRANSKUN_CHECKPOINT", "")


def separation_checkpoint() -> str:
    return env_str("NEXTGEN_SEPARATION_CHECKPOINT", "")


def beat_this_checkpoint() -> str:
    return env_str("NEXTGEN_BEAT_THIS_CHECKPOINT", "")


def separation_backend() -> str:
    """http | roformer | skip | auto (default)."""
    return env_str("NEXTGEN_SEPARATION_BACKEND", "auto").strip().lower() or "auto"


def separation_endpoint() -> str:
    return env_str("SEPARATION_ENDPOINT", "")


def fusion_stem_only_min_confidence() -> float:
    raw = env_str("NEXTGEN_FUSION_STEM_ONLY_MIN_CONFIDENCE", "0.6")
    try:
        return float(raw)
    except ValueError:
        return 0.6


def fusion_ghost_confidence() -> float:
    raw = env_str("NEXTGEN_FUSION_GHOST_CONFIDENCE", "0.35")
    try:
        return float(raw)
    except ValueError:
        return 0.35
