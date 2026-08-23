"""Benchmark harness tests."""

from benchmark.harness import BenchmarkHarness
from mir.types import NoteEvent


def test_benchmark_compare():
    legacy = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5),
        NoteEvent(pitch=64, start_time=0.5, end_time=1.0),
    ]
    understanding = [
        NoteEvent(pitch=60, start_time=0.01, end_time=0.5),
        NoteEvent(pitch=64, start_time=0.51, end_time=1.0),
    ]
    result = BenchmarkHarness().compare_note_lists(
        legacy, understanding, fixture_name="test"
    )
    assert result.cross_pipeline_f1 >= 0.5


def test_should_not_promote_low_f1():
    from benchmark.harness import BenchmarkResult

    harness = BenchmarkHarness()
    bad = BenchmarkResult(fixture="x", cross_pipeline_f1=0.3)
    assert harness.should_promote([bad]) is False


def test_should_promote_high_f1():
    from benchmark.harness import BenchmarkResult

    harness = BenchmarkHarness()
    good = BenchmarkResult(fixture="x", cross_pipeline_f1=0.95)
    assert harness.should_promote([good]) is True
