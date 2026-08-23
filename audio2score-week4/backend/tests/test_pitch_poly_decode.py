"""Tests for PitchExtractor and PolyphonicDecoder."""

import numpy as np

from audio_engine.polyphonic_decoder import PolyphonicDecoder
from audio_engine.pitch_extractor import PitchExtractor
from mir.types import OnsetCandidate, PitchMatrix


def test_pitch_matrix_shape(chord_tone, normalized_audio_factory):
    _, y = chord_tone()
    audio = normalized_audio_factory(y)
    matrix = PitchExtractor().extract(audio)
    assert len(matrix.times) > 0
    assert len(matrix.pitch_bins) == 84
    assert len(matrix.probabilities) == len(matrix.times)


def test_decoder_from_synthetic_matrix():
    matrix = PitchMatrix(
        times=[0.0, 0.05, 0.10, 0.15],
        pitch_bins=[60, 61, 62],
        probabilities=[
            [0.0, 0.0, 0.0],
            [0.9, 0.0, 0.0],
            [0.85, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ],
        confidence=0.9,
    )
    notes = PolyphonicDecoder(threshold=0.5, min_duration_sec=0.04).decode(matrix)
    assert len(notes) >= 1
    assert notes[0].pitch == 60


def test_decoder_aligns_to_onsets():
    matrix = PitchMatrix(
        times=[0.48, 0.53],
        pitch_bins=[64],
        probabilities=[[0.9], [0.9]],
        confidence=1.0,
    )
    onsets = [OnsetCandidate(timestamp=0.502, strength=0.8, confidence=0.8)]
    notes = PolyphonicDecoder(threshold=0.5, min_duration_sec=0.01).decode(matrix, onsets)
    assert abs(notes[0].start_time - 0.502) < 0.01
