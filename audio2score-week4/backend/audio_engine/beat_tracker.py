"""Beat tracking and tempo map construction."""

from __future__ import annotations

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import TempoMap, TempoPoint


class BeatTracker:
    """Build TempoMap from audio (supports local tempo via beat intervals)."""

    def __init__(self, default_bpm: float = 120.0):
        self.default_bpm = default_bpm

    def track(self, audio: NormalizedAudio) -> TempoMap:
        import librosa

        y = audio.samples
        sr = audio.sample_rate
        if y.size < sr // 4:
            return TempoMap(
                points=[
                    TempoPoint(time_sec=0.0, beat=0.0, bpm=self.default_bpm, confidence=0.5)
                ]
            )

        tempo_global = self.default_bpm
        try:
            estimate = librosa.feature.rhythm.tempo(y=y, sr=sr)
            if len(estimate):
                tempo_global = float(estimate[0])
        except Exception:
            try:
                estimate = librosa.beat.tempo(y=y, sr=sr)
                if len(estimate):
                    tempo_global = float(estimate[0])
            except Exception:
                pass

        while tempo_global < 50:
            tempo_global *= 2
        while tempo_global > 200:
            tempo_global /= 2

        try:
            tempo_dynamic, beats = librosa.beat.beat_track(
                y=y, sr=sr, units="time", bpm=tempo_global
            )
            beat_times = np.atleast_1d(beats)
        except Exception:
            beat_times = np.array([])

        points: list[TempoPoint] = [
            TempoPoint(
                time_sec=0.0,
                beat=0.0,
                bpm=tempo_global,
                confidence=0.7,
            )
        ]

        if beat_times.size >= 2:
            for i in range(len(beat_times) - 1):
                dt = float(beat_times[i + 1] - beat_times[i])
                if dt <= 0:
                    continue
                local_bpm = 60.0 / dt
                if 40 <= local_bpm <= 220:
                    points.append(
                        TempoPoint(
                            time_sec=float(beat_times[i]),
                            beat=float(i),
                            bpm=local_bpm,
                            confidence=0.8,
                        )
                    )

        return TempoMap(points=points)
