"""Piano-optimized onset detection."""

from __future__ import annotations

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import AudioSegment, OnsetCandidate


class OnsetDetector:
    """Spectral flux + energy envelope onset candidates."""

    def __init__(
        self,
        pre_max: float = 0.03,
        post_max: float = 0.03,
        pre_avg: float = 0.1,
        post_avg: float = 0.1,
        delta: float = 0.07,
        wait: float = 0.03,
    ):
        self.pre_max = pre_max
        self.post_max = post_max
        self.pre_avg = pre_avg
        self.post_avg = post_avg
        self.delta = delta
        self.wait = wait

    def detect(
        self,
        audio: NormalizedAudio,
        segment: AudioSegment | None = None,
    ) -> list[OnsetCandidate]:
        import librosa

        y = audio.samples
        sr = audio.sample_rate

        if segment:
            s0 = int(segment.start_time * sr)
            s1 = int(segment.end_time * sr)
            y = y[s0:s1]
            offset = segment.start_time
        else:
            offset = 0.0

        if y.size < sr // 20:
            return []

        oenv = librosa.onset.onset_strength(y=y, sr=sr, aggregate=np.median)
        # High-frequency emphasis for piano transients
        y_hf = librosa.effects.preemphasis(y)
        hf_env = librosa.onset.onset_strength(y=y_hf, sr=sr)
        if hf_env.shape != oenv.shape:
            min_len = min(len(oenv), len(hf_env))
            oenv = oenv[:min_len]
            hf_env = hf_env[:min_len]
        combined = 0.65 * oenv + 0.35 * hf_env
        if combined.size == 0:
            return []

        peaks = librosa.util.peak_pick(
            combined,
            pre_max=int(self.pre_max * sr / 512),
            post_max=int(self.post_max * sr / 512),
            pre_avg=int(self.pre_avg * sr / 512),
            post_avg=int(self.post_avg * sr / 512),
            delta=self.delta,
            wait=int(self.wait * sr / 512),
        )

        max_strength = float(np.max(combined)) if combined.size else 1.0
        candidates: list[OnsetCandidate] = []
        for idx in peaks:
            t = librosa.frames_to_time(idx, sr=sr) + offset
            strength = float(combined[idx]) / max(max_strength, 1e-8)
            candidates.append(
                OnsetCandidate(
                    timestamp=t,
                    strength=strength,
                    confidence=min(1.0, strength),
                )
            )

        return candidates
