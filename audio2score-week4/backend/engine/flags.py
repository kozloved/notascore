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


def separation_configured() -> bool:
    """True when a separator endpoint is set. Never returns the URL."""
    return bool(separation_endpoint().strip())


def nextgen_status() -> dict:
    """Safe, non-secret cutover snapshot for /health and startup logs."""
    mode = pipeline_mode()
    return {
        "pipeline_mode": mode,
        "orchestrator_active": mode == PIPELINE_MODE_LIVE,
        "separation_enabled": separation_enabled(),
        "separation_backend": separation_backend(),
        "separation_configured": separation_configured(),
        "stem_transcription_enabled": stem_transcription_enabled(),
        "fusion_enabled": fusion_enabled(),
        "transkun_enabled": transkun_enabled(),
        "beat_this_enabled": beat_this_enabled(),
        "ensemble_render_enabled": ensemble_render_enabled(),
        "write_manifest": write_manifest_enabled(),
    }


def runtime_identification() -> dict:
    """Provenance fields proving which pipeline produced a job."""
    mode = pipeline_mode()
    if mode == PIPELINE_MODE_LIVE:
        owner = "nextgen"
    elif mode == PIPELINE_MODE_SHADOW:
        owner = "shadow-observer"
    else:
        owner = "legacy"
    return {
        "pipeline_mode": mode,
        "orchestrator": owner,
        "separation_enabled": separation_enabled(),
        "fusion_enabled": fusion_enabled(),
        "stem_transcription_enabled": stem_transcription_enabled(),
        "ensemble_render_enabled": ensemble_render_enabled(),
    }


def format_pipeline_banner(*, mt3_configured: bool) -> str:
    ng = nextgen_status()

    def _on(flag: bool) -> str:
        return "on" if flag else "off"

    return (
        "NotaScore pipeline configuration:\n"
        f"  nextgen_mode={ng['pipeline_mode']}\n"
        f"  separation={_on(ng['separation_enabled'])}\n"
        f"  stem_transcription={_on(ng['stem_transcription_enabled'])}\n"
        f"  fusion={_on(ng['fusion_enabled'])}\n"
        f"  ensemble_render={_on(ng['ensemble_render_enabled'])}\n"
        f"  MT3 configured = {str(bool(mt3_configured)).lower()}"
    )


def log_pipeline_configuration(*, mt3_configured: bool) -> None:
    print(format_pipeline_banner(mt3_configured=mt3_configured), flush=True)
