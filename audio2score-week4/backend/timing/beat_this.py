"""Disabled Beat This! adapter. madmom/BeatTracker remains the production fallback."""

from __future__ import annotations

from engine.flags import beat_this_checkpoint, beat_this_enabled


class BeatThisAnalyzer:
    name = "beat_this"

    def analyze(self, audio_path: str):
        raise BeatThisUnavailable(
            "Beat This! is disabled until code and checkpoint licenses "
            "are documented as SaaS-compatible and NEXTGEN_BEAT_THIS=1 "
            f"with a checkpoint (configured={beat_this_enabled()}, "
            f"path={beat_this_checkpoint() or 'unset'})."
        )


class BeatThisUnavailable(RuntimeError):
    pass
