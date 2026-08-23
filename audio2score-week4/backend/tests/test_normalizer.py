"""Tests for AudioNormalizer."""

import numpy as np

from audio_engine.normalizer import AudioNormalizer, NormalizedAudio


def test_normalize_stereo_to_mono(sample_rate):
    norm = AudioNormalizer(target_sr=sample_rate)
    stereo = np.stack([np.ones(1000), np.ones(1000) * 0.5], axis=0)
    result = norm.normalize(stereo, sr=sample_rate)
    assert isinstance(result, NormalizedAudio)
    assert result.samples.ndim == 1
    assert result.sample_rate == sample_rate


def test_peak_normalization(sine_tone, normalized_audio_factory):
    norm = AudioNormalizer()
    _, y = sine_tone(amplitude=0.1)
    result = norm.normalize(y)
    assert result.peak_after <= 0.96
    assert result.peak_after >= 0.85


def test_dc_removal(sample_rate):
    norm = AudioNormalizer(target_sr=sample_rate)
    biased = np.ones(int(sample_rate * 0.2), dtype=np.float32) * 0.5
    result = norm.normalize(biased, sr=sample_rate)
    assert abs(float(np.mean(result.samples))) < 0.05


def test_resample(sample_rate):
    norm = AudioNormalizer(target_sr=sample_rate)
    y = np.random.randn(44100).astype(np.float32) * 0.1
    result = norm.normalize(y, sr=44100)
    assert result.sample_rate == sample_rate
    assert abs(result.duration_sec - 1.0) < 0.1
