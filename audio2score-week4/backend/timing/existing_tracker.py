"""Production beat tracker (madmom / librosa) as a BeatAnalyzer adapter."""

from __future__ import annotations

from timing.base import BeatAnalysis
from timing.tempo_map import MusicalTimeMap


class ExistingTrackerAnalyzer:
    """Wraps audio_engine.BeatTracker. Fallback and current production path."""

    name = "existing_tracker"

    def analyze(self, audio_path: str) -> BeatAnalysis:
        from audio_engine.beat_tracker import BeatTracker
        from audio_engine.normalizer import AudioNormalizer

        audio = AudioNormalizer().normalize(audio_path)
        tracker = BeatTracker()
        tempo_map = tracker.track(audio)
        result = tracker.last_beat_result
        if result is not None and getattr(result, "beat_times", None):
            beat_times = [float(t) for t in result.beat_times]
            downbeats = [float(t) for t in (result.downbeat_times or [])]
        else:
            duration = max(audio.duration_sec, 1.0)
            beat_times = list(
                MusicalTimeMap.from_tempo_map(tempo_map, duration_sec=duration).beat_times
            )
            downbeats = beat_times[::4]
        if len(beat_times) < 2:
            beat_times = list(
                MusicalTimeMap.from_bpm(120.0, duration_sec=max(audio.duration_sec, 1.0)).beat_times
            )
        time_map = MusicalTimeMap(tuple(beat_times), source=tracker.last_source)
        return BeatAnalysis(
            beat_times=beat_times,
            downbeat_times=downbeats,
            time_map=time_map,
            model=tracker.last_source,
            warnings=[] if result is not None else ["beat times reconstructed from TempoMap"],
        )


def analysis_from_beat_times(
    beat_times: list[float],
    *,
    downbeat_times: list[float] | None = None,
    model: str = "explicit",
) -> BeatAnalysis:
    times = [float(t) for t in beat_times]
    time_map = MusicalTimeMap(tuple(times), source=model)
    downs = [float(t) for t in (downbeat_times or times[::4])]
    return BeatAnalysis(beat_times=times, downbeat_times=downs, time_map=time_map, model=model)
