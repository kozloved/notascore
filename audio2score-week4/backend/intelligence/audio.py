"""Encode a short mono WAV for Gemini inline audio."""

from __future__ import annotations

import io
from typing import Iterable

import numpy as np
import soundfile as sf

from audio_engine.normalizer import NormalizedAudio

GEMINI_AUDIO_SR = 16000


def encode_analysis_wav(
    normalized: NormalizedAudio | None,
    *,
    max_seconds: float,
    windows: Iterable[tuple[float, float]] | None = None,
) -> tuple[bytes | None, float]:
    if normalized is None or normalized.samples.size == 0:
        return None, 0.0
    y = np.asarray(normalized.samples, dtype=np.float32)
    sr = int(normalized.sample_rate)
    if windows:
        chunks = []
        for lo, hi in windows:
            start = max(0, int(lo * sr))
            end = min(len(y), int(hi * sr))
            if end > start:
                chunks.append(y[start:end])
        if chunks:
            y = np.concatenate(chunks)
    max_samples = int(max_seconds * sr)
    if max_samples > 0 and len(y) > max_samples:
        y = y[:max_samples]
    if sr != GEMINI_AUDIO_SR:
        import librosa

        y = librosa.resample(y, orig_sr=sr, target_sr=GEMINI_AUDIO_SR)
        sr = GEMINI_AUDIO_SR
    buf = io.BytesIO()
    sf.write(buf, y, sr, format="WAV", subtype="PCM_16")
    data = buf.getvalue()
    duration = len(y) / float(sr)
    return data, duration
