"""Checkpoint 5 corpus + MIDI CI subset."""

from __future__ import annotations

import json

from benchmark.evaluate import evaluate_case
from benchmark.fixtures.catalog import all_cases
from benchmark.fixtures.generate import write_corpus
from benchmark.load import filter_cases, load_cases
from benchmark.metrics import xml_structure_valid
from benchmark.report import build_report, render_markdown
from benchmark.runner import RESULTS_DIR, REPO_ROOT


def test_catalog_has_required_coverage():
    cases = all_cases()
    assert len(cases) >= 15
    categories = {c.category for c in cases}
    for required in (
        "melody_simple",
        "piano_simple",
        "piano_chords",
        "piano_two_hands",
        "rhythm",
        "midi_ingest",
    ):
        assert required in categories
    ids = {c.case_id for c in cases}
    assert "octave_doubling" in ids
    assert "hand_crossing" in ids
    assert "polyphonic_rh" in ids
    assert "triplets" in ids
    assert "syncopation" in ids
    assert "dotted" in ids
    assert "waltz_3_4" in ids
    assert "compound_6_8" in ids
    midi_cases = [c for c in cases if c.category == "midi_ingest"]
    assert len(midi_cases) >= 3


def test_generate_and_load_corpus(tmp_path):
    write_corpus()
    cases = load_cases()
    assert len(cases) >= 15
    for case in cases:
        assert case.input_midi.exists()
        assert case.reference_midi.exists()
        assert case.reference_notes
        assert case.metadata["generation"]["copyrighted"] is False


def test_xml_structure_helper():
    ok, errors = xml_structure_valid("<score-partwise></score-partwise>")
    assert not ok
    assert errors
    sample = """<?xml version="1.0"?>
    <score-partwise version="3.1">
      <part id="P1"><measure number="1">
        <attributes><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
        <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration></note>
      </measure></part>
    </score-partwise>
    """
    ok, errors = xml_structure_valid(sample)
    assert ok, errors


def test_ci_subset_midi_cases_pass(tmp_path):
    write_corpus()
    cases = filter_cases(load_cases(), subset="ci")
    assert len(cases) >= 15
    work = tmp_path / "bench_work"
    rows = []
    # Gate: MIDI ingest + notation + hands + voices + rhythm. No GPU.
    for case in cases:
        row = evaluate_case(case, mode="midi", work_root=work)
        rows.append(row.to_dict())
        assert row.skipped is False
        assert row.passed, (case.case_id, row.flags)
        assert row.notation["fallback_used"] is False
        assert row.notation["plan_success"] is True
        assert row.notation["xml_valid"] is True

    octave = next(r for r in rows if r["id"] == "octave_doubling")
    assert octave["cleaning"]["false_removals"] == 0
    poly = next(r for r in rows if r["id"] == "polyphonic_rh")
    assert poly["voices"]["continuity_ok"] is True
    cross = next(r for r in rows if r["id"] == "hand_crossing")
    assert cross["hands"]["accuracy"] is None or cross["hands"]["accuracy"] >= 0.85

    report = build_report(mode="midi", cases=rows, repo=REPO_ROOT, baseline=None)
    markdown = render_markdown(report)
    assert "**MIDI ingest**" in markdown
    assert report["mode_label"] == "MIDI ingest"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    (RESULTS_DIR / "latest.md").write_text(markdown)
    assert report["ok"] is True
    assert report["fallback_count"] == 0


def test_quality_mode_skips_without_gpu(tmp_path):
    write_corpus()
    case = next(c for c in load_cases() if c.case_id == "c_major_quarters")
    row = evaluate_case(case, mode="quality", work_root=tmp_path / "q")
    assert row.skipped is True
    assert "unavailable" in (row.skip_reason or "").lower()
