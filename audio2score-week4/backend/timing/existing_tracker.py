"""Production beat tracker (madmom / librosa) as a BeatAnalyzer adapter."""

from __future__ import annotations

from timing.base import BeatAnalysis
from timing.tempo_map import MusicalTimeMap, sanitize_beat_times


class ExistingTrackerAnalyzer:
    """Wraps audio_engine.BeatTracker. Fallback and current production path."""

    name = "existing_tracker"

    def analyze(self, audio_path: str) -> BeatAnalysis:
        from audio_engine.beat_tracker import BeatTracker
        from audio_engine.normalizer import AudioNormalizer

        audio = AudioNormalizer().normalize(audio_path)
        tracker = BeatTracker()
        tempo_map = tracker.track(audio)
        return analyze_from_tracker(
            tracker, tempo_map=tempo_map, duration_sec=max(audio.duration_sec, 1.0)
        )


def analyze_from_tracker(tracker, *, tempo_map=None, duration_sec: float = 1.0) -> BeatAnalysis:
    """Build BeatAnalysis from a tracker that has already run. No second pass."""
    result = getattr(tracker, "last_beat_result", None)
    source = getattr(tracker, "last_source", None) or "existing_tracker"
    warnings: list[str] = []
    beat_times: list[float] = []
    downbeats: list[float] = []
    fallback_used = False
    if result is not None and getattr(result, "beat_times", None):
        beat_times = sanitize_beat_times(result.beat_times)
        downbeats = sanitize_beat_times(getattr(result, "downbeat_times", None) or [])
    elif getattr(tracker, "last_beat_times", None):
        beat_times = sanitize_beat_times(tracker.last_beat_times)
    if len(beat_times) < 2 and tempo_map is not None:
        try:
            sampled = MusicalTimeMap.from_tempo_map(tempo_map, duration_sec=duration_sec)
            beat_times = list(sampled.beat_times)
            warnings.append("beat times reconstructed from TempoMap")
            fallback_used = True
        except ValueError:
            pass
    if len(beat_times) < 2:
        beat_times = list(
            MusicalTimeMap.from_bpm(120.0, duration_sec=max(duration_sec, 1.0)).beat_times
        )
        warnings.append("constant 120 BPM last-resort beat grid")
        source = "constant_bpm:120"
        fallback_used = True
    time_map = MusicalTimeMap.from_beat_times(beat_times, source=source)
    return BeatAnalysis(
        beat_times=list(time_map.beat_times),
        downbeat_times=downbeats,
        time_map=time_map,
        model=source,
        warnings=warnings,
        fallback_used=fallback_used,
    )


def analysis_from_beat_times(
    beat_times: list[float],
    *,
    downbeat_times: list[float] | None = None,
    model: str = "explicit",
) -> BeatAnalysis:
    times = sanitize_beat_times(beat_times)
    time_map = MusicalTimeMap.from_beat_times(times, source=model)
    downs = sanitize_beat_times(downbeat_times or [])
    return BeatAnalysis(
        beat_times=list(time_map.beat_times),
        downbeat_times=downs,
        time_map=time_map,
        model=model,
    )


ExistingBeatTrackerAdapter = ExistingTrackerAnalyzer
