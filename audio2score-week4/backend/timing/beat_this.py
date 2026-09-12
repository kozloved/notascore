"""Disabled Beat This! adapter. madmom/BeatTracker remains the production fallback."""

from __future__ import annotations

from engine.flags import beat_this_checkpoint, beat_this_configured, beat_this_enabled, beat_this_operational


class BeatThisAnalyzer:
    name = "beat_this"

    def analyze(self, audio_path: str):
        raise BeatThisUnavailable(
            "Beat This! is disabled until code and checkpoint licenses "
            "are documented as SaaS-compatible and NEXTGEN_BEAT_THIS=1 "
            f"with a checkpoint (configured={beat_this_configured()}, "
            f"operational={beat_this_operational()}, "
            f"enabled={beat_this_enabled()}, "
            f"path={beat_this_checkpoint() or 'unset'})."
        )


def beat_this_status() -> dict:
    return {
        "configured": beat_this_configured(),
        "operational": beat_this_operational(),
        "enabled": beat_this_enabled(),
    }


class BeatThisUnavailable(RuntimeError):
    pass


BeatThisAdapter = BeatThisAnalyzer
