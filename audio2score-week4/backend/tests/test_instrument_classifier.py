"""Tests for InstrumentClassifier."""

from __future__ import annotations

import numpy as np

from audio_engine.instrument_classifier import InstrumentClassifier
from mir.types import InstrumentKind


def _audio(y, normalized_audio_factory):
    return normalized_audio_factory(y.astype(np.float32))


def test_classifies_short_audio_as_unknown(sample_rate):
    from audio_engine.normalizer import NormalizedAudio

    audio = NormalizedAudio(
        samples=np.zeros(sample_rate // 20, dtype=np.float32),
        sample_rate=sample_rate,
    )
    pred = InstrumentClassifier().classify(audio)
    assert pred.instrument == InstrumentKind.UNKNOWN


def test_sine_tone_is_not_voice_or_guitar(sine_tone, normalized_audio_factory):
    _, y = sine_tone(freq_hz=440, duration_sec=2.0)
    pred = InstrumentClassifier().classify(_audio(y, normalized_audio_factory))
    assert pred.instrument == InstrumentKind.UNKNOWN


def test_classifies_piano_like_polyphonic(normalized_audio_factory, sample_rate):
    t = np.linspace(0, 2.0, sample_rate * 2, endpoint=False)
    env = np.exp(-t * 1.8)
    hammer = 0.15 * np.random.default_rng(0).standard_normal(t.size) * np.exp(-t * 40)
    freqs = (65.41, 130.81, 164.81, 261.63, 329.63, 392.0)
    y = sum(0.18 * np.sin(2 * np.pi * f * t) for f in freqs) * env + hammer
    pred = InstrumentClassifier().classify(_audio(y, normalized_audio_factory))
    assert pred.instrument == InstrumentKind.PIANO
    assert pred.confidence > 0.35


def test_classifies_bright_plucked_clip_as_guitar(normalized_audio_factory, sample_rate):
    t = np.linspace(0, 2.0, sample_rate * 2, endpoint=False)
    env = np.exp(-t * 6.0)
    pluck = 0.35 * np.random.default_rng(1).standard_normal(t.size) * np.exp(-t * 60)
    freqs = (196.0, 246.94, 293.66, 329.63)
    y = sum(
        0.15 * np.sin(2 * np.pi * f * t)
        + 0.12 * np.sin(2 * np.pi * f * 2 * t)
        + 0.10 * np.sin(2 * np.pi * f * 4 * t)
        + 0.08 * np.sin(2 * np.pi * f * 8 * t)
        for f in freqs
    )
    pred = InstrumentClassifier().classify(_audio(y * env + pluck, normalized_audio_factory))
    assert pred.instrument == InstrumentKind.GUITAR


def test_classifies_vibrato_as_voice(normalized_audio_factory, sample_rate):
    t = np.linspace(0, 2.0, sample_rate * 2, endpoint=False)
    vib = 440.0 * (1.0 + 0.012 * np.sin(2 * np.pi * 5.5 * t))
    phase = np.cumsum(2 * np.pi * vib / sample_rate)
    y = 0.35 * np.sin(phase) + 0.12 * np.sin(2 * phase)
    pred = InstrumentClassifier().classify(_audio(y, normalized_audio_factory))
    assert pred.instrument == InstrumentKind.VOICE


def test_classifies_noise_bursts_as_drums(normalized_audio_factory, sample_rate):
    t = np.linspace(0, 2.0, sample_rate * 2, endpoint=False)
    y = np.zeros_like(t)
    rng = np.random.default_rng(2)
    for start in (0.0, 0.5, 1.0, 1.5):
        i = int(start * sample_rate)
        n = int(0.08 * sample_rate)
        y[i : i + n] += rng.standard_normal(n) * np.exp(-np.linspace(0, 8, n))
    pred = InstrumentClassifier().classify(_audio(y, normalized_audio_factory))
    assert pred.instrument == InstrumentKind.DRUMS


def test_characteristics_populated(chord_tone, normalized_audio_factory):
    _, y = chord_tone()
    pred = InstrumentClassifier().classify(_audio(y, normalized_audio_factory))
    assert pred.characteristics.pitch_range_semitones >= 0
    assert 0.0 <= pred.confidence <= 1.0
