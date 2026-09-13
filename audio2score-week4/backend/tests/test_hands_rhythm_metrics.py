"""Smoke tests for the hands/rhythm Phase 3 metrics harness."""

from fractions import Fraction
from pathlib import Path

from evaluation.hands_rhythm_metrics import (
    musicxml_complexity,
    run_synthetic_case,
    synthetic_cases,
)
from mir.performance_score import _duration


def test_synthetic_cases_preserve_identity_and_simple_boundaries():
    cases = synthetic_cases()
    pedal = run_synthetic_case("pedal_quarters", cases["pedal_quarters"])
    assert pedal["plan"]["source_identity_preserved"] is True
    assert pedal["layout"]["distinct_voices"] == 1
    assert pedal["written_durations"]["pedal0"] == "1"

    boundary = run_synthetic_case(
        "near_boundary_releases", cases["near_boundary_releases"]
    )
    assert boundary["written_durations"]["b0.94"] == "1"
    assert boundary["written_durations"]["b1.17"] == "1"

    independent = run_synthetic_case(
        "independent_rh_voices", cases["independent_rh_voices"]
    )
    assert independent["layout"]["distinct_voices"] >= 2


def test_duration_probe_matches_handoff_table():
    assert _duration(0.94, Fraction(0), None, False, "binary") == 1
    assert _duration(1.17, Fraction(0), None, False, "binary") == 1


def test_musicxml_complexity_counts_each_tie_start_once(tmp_path):
    xml = """<?xml version='1.0'?>
    <score-partwise>
      <part id='P1'>
        <measure number='1'>
          <note>
            <pitch><step>C</step><octave>4</octave></pitch>
            <duration>1</duration>
            <type>quarter</type>
            <tie type='start'/>
            <notations><tied type='start'/></notations>
          </note>
        </measure>
      </part>
    </score-partwise>
    """
    path = tmp_path / "tie.xml"
    path.write_text(xml, encoding="utf-8")
    metrics = musicxml_complexity(path)
    assert metrics["pitched_symbols"] == 1
    assert metrics["tie_starts"] == 1


def test_musicxml_complexity_reads_autumn_fixture_when_present():
    path = (
        Path(__file__).resolve().parents[1]
        / ".tmp"
        / "autumn-walks-review"
        / "current-main.musicxml"
    )
    if not path.is_file():
        return
    metrics = musicxml_complexity(path)
    assert metrics["pitched_symbols"] == 155
    assert metrics["tiny_total"] >= 1
    # Single-count ties (<tie> and <tied> are one musical start).
    assert metrics["tie_starts"] == 55
