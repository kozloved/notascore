"""Fuse competing beat analyses. Beat This! is preferred only when it actually ran."""

from __future__ import annotations

from dataclasses import replace

from engine.flags import beat_this_enabled
from timing.base import BeatAnalysis
from timing.beat_this import BeatThisAnalyzer, BeatThisUnavailable
from timing.existing_tracker import ExistingTrackerAnalyzer


def fuse_beat_analyses(preferred: BeatAnalysis | None, fallback: BeatAnalysis) -> BeatAnalysis:
    """Keep fallback beat times when the preferred analyzer is missing or thin."""
    if preferred is None or len(preferred.beat_times) < 2:
        return replace(
            fallback,
            fallback_used=True,
            fallback_of="" if preferred is None else preferred.model,
            warnings=list(fallback.warnings)
            + (["preferred beat analyzer unavailable or too sparse"] if preferred is None or len(preferred.beat_times) < 2 else []),
        )
    return preferred


def analyze_beats(audio_path: str) -> BeatAnalysis:
    """Concurrent slot: try Beat This! then the production tracker. Never hide fallback."""
    fallback = ExistingTrackerAnalyzer().analyze(audio_path)
    if not beat_this_enabled():
        return replace(
            fallback,
            warnings=list(fallback.warnings) + ["Beat This! disabled; using existing tracker"],
        )
    try:
        preferred = BeatThisAnalyzer().analyze(audio_path)
    except BeatThisUnavailable as exc:
        fused = fuse_beat_analyses(None, fallback)
        fused.warnings.append(str(exc))
        fused.fallback_of = "beat_this"
        return fused
    return fuse_beat_analyses(preferred, fallback)
