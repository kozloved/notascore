"""Shared pytest fixtures."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def sample_rate():
    return 22050


@pytest.fixture
def sine_tone(sample_rate):
    def _make(freq_hz: float = 440.0, duration_sec: float = 1.0, amplitude: float = 0.5):
        t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
        return t, (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)

    return _make


@pytest.fixture
def chord_tone(sample_rate):
    def _make(
        freqs=(261.63, 329.63, 392.0),
        duration_sec: float = 1.0,
        amplitude: float = 0.3,
    ):
        t = np.linspace(0, duration_sec, int(sample_rate * duration_sec), endpoint=False)
        y = sum(amplitude * np.sin(2 * np.pi * f * t) for f in freqs)
        return t, y.astype(np.float32)

    return _make


@pytest.fixture
def normalized_audio_factory(sample_rate):
    from audio_engine.normalizer import AudioNormalizer, NormalizedAudio

    def _make(samples: np.ndarray, sr: int | None = None):
        norm = AudioNormalizer(target_sr=sample_rate)
        return norm.normalize(samples, sr=sr or sample_rate)

    return _make
