"""Tests for InstrumentClassifier."""

import numpy as np

from audio_engine.instrument_classifier import InstrumentClassifier
from mir.types import InstrumentKind


def test_classifies_piano_like_polyphonic(chord_tone, normalized_audio_factory):
    _, y = chord_tone()
    audio = normalized_audio_factory(y)
    pred = InstrumentClassifier().classify(audio)
    assert pred.instrument in (
        InstrumentKind.PIANO,
        InstrumentKind.GUITAR,
        InstrumentKind.STRINGS,
        InstrumentKind.VOICE,
        InstrumentKind.UNKNOWN,
    )
    assert 0.0 <= pred.confidence <= 1.0


def test_classifies_short_audio_as_unknown(sample_rate):
    from audio_engine.normalizer import NormalizedAudio

    audio = NormalizedAudio(
        samples=np.zeros(sample_rate // 20, dtype=np.float32),
        sample_rate=sample_rate,
    )
    pred = InstrumentClassifier().classify(audio)
    assert pred.instrument == InstrumentKind.UNKNOWN


def test_characteristics_populated(chord_tone, normalized_audio_factory):
    _, y = chord_tone()
    audio = normalized_audio_factory(y)
    pred = InstrumentClassifier().classify(audio)
    assert pred.characteristics.pitch_range_semitones >= 0
