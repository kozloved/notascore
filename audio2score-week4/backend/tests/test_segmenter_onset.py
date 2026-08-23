"""Tests for AudioSegmenter and OnsetDetector."""

import numpy as np

from audio_engine.onset_detector import OnsetDetector
from audio_engine.segmenter import AudioSegmenter
from benchmark.metrics import onset_f_measure


def test_segmenter_finds_non_silent_region(normalized_audio_factory, sample_rate):
    y = np.zeros(sample_rate * 2, dtype=np.float32)
    y[sample_rate // 2 : sample_rate] = 0.3 * np.sin(
        2 * np.pi * 440 * np.linspace(0, 1, sample_rate // 2)
    )
    audio = normalized_audio_factory(y)
    segments = AudioSegmenter().segment(audio)
    assert len(segments) >= 1
    assert segments[0].end_time > segments[0].start_time


def test_onset_detector_finds_attack(normalized_audio_factory, sample_rate):
    y = np.zeros(sample_rate, dtype=np.float32)
    attack_start = sample_rate // 4
    t = np.linspace(0, 0.5, sample_rate // 2)
    y[attack_start : attack_start + len(t)] = 0.5 * np.sin(2 * np.pi * 440 * t)
    audio = normalized_audio_factory(y)
    onsets = OnsetDetector().detect(audio)
    assert len(onsets) >= 1
    assert all(0.0 <= o.confidence <= 1.0 for o in onsets)


def test_onset_f_measure_synthetic():
    ref = [0.5, 1.0, 1.5]
    pred = [0.51, 1.02, 1.48]
    p, r, f1 = onset_f_measure(pred, ref, tolerance_sec=0.05)
    assert f1 == 1.0
    assert p == 1.0
    assert r == 1.0
