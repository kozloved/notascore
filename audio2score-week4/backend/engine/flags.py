"""Feature flags for next-gen stages. Defaults keep production on the current path."""

from __future__ import annotations

from mir.pipeline_config import env_bool, env_str


def separation_enabled() -> bool:
    return env_bool("NEXTGEN_SEPARATION", default=False)


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
