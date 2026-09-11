from mir.types import TempoMap, TempoPoint
from timing.base import BeatAnalysis
from timing.existing_tracker import analysis_from_beat_times
from timing.fusion import fuse_beat_analyses
from timing.tempo_map import MusicalTimeMap, ROUNDTRIP_TOLERANCE_SEC, assert_roundtrip


def test_stride_and_subdivision_keep_seconds_invertible():
    time_map = MusicalTimeMap.from_bpm(120, duration_sec=4.0)
    half = time_map.with_stride(2)
    double = time_map.with_subdivisions(2)
    samples = [0.0, 0.37, 1.0, 2.5]
    assert_roundtrip(half, samples)
    assert_roundtrip(double, samples)
    assert abs(time_map.seconds_to_beats(1.0) - 2.0) < 1e-9
    assert abs(half.seconds_to_beats(1.0) - 1.0) < 1e-9
    assert abs(double.seconds_to_beats(1.0) - 4.0) < 1e-9


def test_rubato_beat_times_are_invertible():
    times = (0.4, 1.1, 1.7, 2.55, 3.0, 4.2)
    time_map = MusicalTimeMap(times, source="fixture")
    samples = [0.4, 0.9, 1.7, 2.9, 4.2, 5.0]
    assert_roundtrip(time_map, samples, tol=ROUNDTRIP_TOLERANCE_SEC)
    assert abs(time_map.beats_to_seconds(time_map.seconds_to_beats(18.351)) - 18.351) < 1e-4


def test_rejects_non_increasing_beats():
    import pytest

    with pytest.raises(ValueError):
        MusicalTimeMap((0.0, 0.5, 0.5))


def test_extrapolates_with_local_interval():
    time_map = MusicalTimeMap((0.5, 1.5, 2.0))
    assert abs(time_map.seconds_to_beats(0.0) - (-0.5)) < 1e-9
    assert abs(time_map.beats_to_seconds(-0.5) - 0.0) < 1e-9
    assert abs(time_map.seconds_to_beats(2.5) - 3.0) < 1e-9
    assert_roundtrip(time_map, [-0.25, 0.5, 1.75, 3.0])


def test_from_tempo_map_preserves_rubato_beat_times():
    tempo_map = TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0),
            TempoPoint(time_sec=2.0, beat=4.0, bpm=60.0),
        ]
    )
    time_map = MusicalTimeMap.from_tempo_map(tempo_map, duration_sec=4.0)
    assert abs(time_map.beats_to_seconds(4.0) - 2.0) < 1e-3
    assert abs(time_map.beats_to_seconds(5.0) - 3.0) < 1e-3
    assert_roundtrip(time_map, [0.0, 1.0, 2.0, 3.5])


def test_fuse_falls_back_when_preferred_is_sparse():
    fallback = analysis_from_beat_times([0.4, 1.1, 1.8])
    fused = fuse_beat_analyses(None, fallback)
    assert fused.fallback_used
    assert fused.beat_times == fallback.beat_times
    preferred = BeatAnalysis(
        beat_times=[0.0],
        downbeat_times=[],
        time_map=fallback.time_map,
        model="thin",
    )
    fused2 = fuse_beat_analyses(preferred, fallback)
    assert fused2.fallback_used
    assert fused2.beat_times == fallback.beat_times
