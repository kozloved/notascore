"""Silence and phrase/section segmentation."""

from __future__ import annotations

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import AudioSegment


class AudioSegmenter:
    """Split audio into non-silent segments with tempo/energy hints."""

    def __init__(self, top_db: float = 35.0, min_duration_sec: float = 0.5):
        self.top_db = top_db
        self.min_duration_sec = min_duration_sec

    def segment(self, audio: NormalizedAudio) -> list[AudioSegment]:
        import librosa

        y = audio.samples
        sr = audio.sample_rate
        if y.size == 0:
            return []

        intervals = librosa.effects.split(y, top_db=self.top_db)
        segments: list[AudioSegment] = []

        for start_idx, end_idx in intervals:
            start = start_idx / sr
            end = end_idx / sr
            if end - start < self.min_duration_sec:
                continue

            chunk = y[start_idx:end_idx]
            rms = float(np.sqrt(np.mean(chunk**2))) if chunk.size else 0.0

            tempo = 120.0
            try:
                estimate = librosa.feature.rhythm.tempo(y=chunk, sr=sr)
                if len(estimate):
                    tempo = float(estimate[0])
            except Exception:
                pass

            while tempo < 50:
                tempo *= 2
            while tempo > 200:
                tempo /= 2

            segments.append(
                AudioSegment(
                    start_time=start,
                    end_time=end,
                    estimated_tempo=tempo,
                    energy_profile=rms,
                )
            )

        if not segments:
            segments.append(
                AudioSegment(
                    start_time=0.0,
                    end_time=len(y) / sr,
                    estimated_tempo=120.0,
                    energy_profile=float(np.sqrt(np.mean(y**2))) if y.size else 0.0,
                )
            )

        return segments
