"""Tests for TempoMap and BeatTracker."""

import numpy as np

from audio_engine.beat_tracker import BeatTracker
from mir.types import TempoMap, TempoPoint


def test_tempo_map_seconds_to_beats_constant():
    tm = TempoMap(points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0)])
    assert abs(tm.seconds_to_beats(1.0) - 2.0) < 0.01


def test_tempo_map_bpm_at():
    tm = TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=100.0),
            TempoPoint(time_sec=2.0, beat=2.0, bpm=140.0),
        ]
    )
    assert tm.bpm_at(0.0) == 100.0
    assert tm.bpm_at(2.5) == 140.0


def test_beat_tracker_returns_map(sine_tone, normalized_audio_factory):
    _, y = sine_tone(freq_hz=440, duration_sec=2.0)
    audio = normalized_audio_factory(y)
    tm = BeatTracker().track(audio)
    assert len(tm.points) >= 1
    assert tm.points[0].bpm > 0
