"""Tests for the canonical benchmark suite."""

from benchmark.suite import passed, run_suite


def test_suite_runs():
    results = run_suite()
    assert results
    names = {r.name for r in results}
    assert "two_hand_scale" in names
    assert "polyphonic_rh" in names


def test_core_cases_pass():
    for result in run_suite():
        assert passed(result), result
