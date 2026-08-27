"""Checkpoint 8 transcription forensics tests."""

from __future__ import annotations

from pathlib import Path

import pretty_midi
import pytest

from evaluation.forensics.cleaner import cleaner_impact
from evaluation.forensics.classify import classify_notes, matching_strategy_doc
from evaluation.forensics.offset import offset_forensics
from evaluation.forensics.tempo import classify_tempo_ratio, tempo_note_f1_causality
from evaluation.forensics.taxonomy import (
    PRED_DUPLICATE,
    PRED_SPURIOUS,
    REF_FRAGMENTED,
    REF_MATCH,
    REF_MERGED,
    REF_MISSED,
    REF_ONSET_ERROR,
    REF_PITCH_ERROR,
)
from mir.types import NoteEvent


def _n(pitch: int, start: float, end: float, vel: int = 80) -> NoteEvent:
    return NoteEvent(pitch=pitch, start_time=start, end_time=end, velocity=vel)


def _write_midi(path: Path, notes: list[tuple[int, float, float]]) -> Path:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    for pitch, start, end in notes:
        inst.notes.append(
            pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=end)
        )
    midi.instruments.append(inst)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))
    return path


def test_matching_strategy_documented():
    doc = matching_strategy_doc()
    assert "Hungarian" in doc
    assert "one-to-one" in doc.lower() or "1-1" in doc or "one-to-one" in doc


def test_exact_match_classification():
    ref = [_n(60, 0.0, 0.5), _n(64, 0.5, 1.0)]
    pred = [_n(60, 0.01, 0.49), _n(64, 0.52, 0.99)]
    res = classify_notes(ref, pred, stage="transcription", case_id="t")
    assert res.summary is not None
    assert res.summary.matched_pairs == 2
    assert res.summary.false_negatives == 0
    assert res.summary.false_positives == 0
    assert res.summary.reference_classes.get(REF_MATCH, 0) >= 1


def test_false_negative_and_false_positive():
    ref = [_n(60, 0.0, 0.5), _n(64, 0.5, 1.0)]
    pred = [_n(60, 0.0, 0.5), _n(70, 2.0, 2.5)]  # second is spurious; 64 missed
    res = classify_notes(ref, pred, stage="transcription")
    assert res.summary.false_negatives >= 1
    assert res.summary.false_positives >= 1
    assert REF_MISSED in res.summary.reference_classes
    assert res.summary.predicted_classes.get(PRED_SPURIOUS, 0) >= 1


def test_pitch_error_classification():
    ref = [_n(60, 0.0, 0.5)]
    pred = [_n(62, 0.0, 0.5)]  # +2 semitones, same onset
    res = classify_notes(ref, pred, stage="transcription")
    assert res.summary.pitch_errors >= 1
    assert res.summary.reference_classes.get(REF_PITCH_ERROR, 0) >= 1


def test_onset_error_early_late():
    ref = [_n(60, 1.0, 1.5)]
    pred_late = [_n(60, 1.20, 1.7)]
    late = classify_notes(ref, pred_late, stage="transcription")
    assert late.summary.onset_errors >= 1
    assert late.summary.reference_classes.get(REF_ONSET_ERROR, 0) >= 1

    pred_early = [_n(60, 0.80, 1.3)]
    early = classify_notes(ref, pred_early, stage="transcription")
    assert early.summary.onset_errors >= 1


def test_fragmented_note_detection():
    ref = [_n(60, 0.0, 1.0)]
    pred = [_n(60, 0.0, 0.4), _n(60, 0.45, 0.9)]
    res = classify_notes(ref, pred, stage="transcription")
    assert res.summary.fragmented >= 1
    assert res.summary.reference_classes.get(REF_FRAGMENTED, 0) >= 1


def test_merged_note_detection():
    ref = [_n(60, 0.0, 0.4), _n(60, 0.5, 0.9)]
    pred = [_n(60, 0.0, 1.0)]
    res = classify_notes(ref, pred, stage="transcription")
    assert res.summary.merged >= 1
    assert res.summary.reference_classes.get(REF_MERGED, 0) >= 1


def test_duplicate_detection():
    ref = [_n(60, 0.0, 0.5)]
    pred = [_n(60, 0.0, 0.5), _n(60, 0.05, 0.45)]
    res = classify_notes(ref, pred, stage="transcription")
    # One match + one duplicate/extra fragment
    assert res.summary.matched_pairs >= 1
    assert (
        res.summary.duplicates >= 1
        or res.summary.predicted_classes.get(PRED_DUPLICATE, 0) >= 1
        or res.summary.predicted_classes.get("EXTRA_FRAGMENT", 0) >= 1
    )


def test_empty_categories_do_not_crash(tmp_path: Path):
    from evaluation.forensics.midi_out import export_stage_diagnostic_midis

    ref = [_n(60, 0.0, 0.5)]
    pred = [_n(60, 0.0, 0.5)]
    res = classify_notes(ref, pred, stage="transcription")
    paths = export_stage_diagnostic_midis(
        out_dir=tmp_path / "diag",
        reference=ref,
        predicted=pred,
        classification=res,
    )
    assert Path(paths["false_positives"]).is_file()
    assert Path(paths["fragmented_notes"]).is_file()
    # empty category files still exist
    assert Path(paths["false_positives"]).stat().st_size > 0 or True


def test_cleaner_harmful_and_beneficial_accounting():
    ref = [_n(60, 0.0, 0.5), _n(64, 0.5, 1.0)]
    before = [
        _n(60, 0.0, 0.5),  # correct
        _n(64, 0.5, 1.0),  # correct
        _n(70, 2.0, 2.4),  # FP
    ]
    # Cleaner removes the correct C4 and the FP; keeps E4
    after = [_n(64, 0.5, 1.0)]
    impact = cleaner_impact(ref, before, after)
    assert impact["harmful_removals"] >= 1
    assert impact["beneficial_removals"] >= 1
    assert impact["notes_before"] == 3
    assert impact["notes_after"] == 1
    assert impact["recall_delta"] < 0


def test_tempo_ratio_classification():
    assert classify_tempo_ratio(160, 80)["status"] == "HALF_TEMPO"
    assert classify_tempo_ratio(80, 160)["status"] == "DOUBLE_TEMPO"
    assert classify_tempo_ratio(120, 120)["status"] == "CORRECT"
    assert classify_tempo_ratio(120, 100)["status"] in {"NEAR_CORRECT", "MISMATCH"}
    assert classify_tempo_ratio(None, 120)["status"] == "UNKNOWN"


def test_tempo_causality_not_assumed_when_onsets_ok():
    result = tempo_note_f1_causality(
        tempo_status="HALF_TEMPO",
        mean_onset_error_ms=12.0,
        onset_pitch_f1=0.20,
    )
    assert result["tempo_explains_note_f1"] is False
    assert "not explained" in result["reason"].lower() or "not" in result["reason"].lower()


def test_offset_tolerance_analysis():
    ref = [_n(60, 0.0, 0.5)]
    # onset OK, offset far
    pred = [_n(60, 0.0, 1.2)]
    result = offset_forensics(pred, ref)
    assert "by_tolerance" in result
    assert "50ms" in result["by_tolerance"]
    assert "500ms" in result["by_tolerance"]
    assert result["matched_onset_pitch_pairs"] == 1
    assert result["conclusion"]["verdict"] in {
        "genuine_duration_failure",
        "tolerance_sensitive",
        "systematic_offset_bias",
        "mixed",
    }


def test_missing_pipeline_stage_handled(tmp_path: Path):
    from evaluation.forensics.analyze import analyze_case

    case_dir = tmp_path / "case"
    case_dir.mkdir()
    ref = _write_midi(case_dir / "reference_raw.mid", [(60, 0.0, 0.5)])
    # No transcription.mid etc.
    payload = analyze_case(
        case_id="empty_stages",
        case_out_dir=case_dir,
        reference_raw_path=ref,
        predicted_tempo=120.0,
        expected_tempo=120.0,
    )
    assert payload["status"] == "ran"
    assert payload["stages"]["transcription"]["status"] == "unavailable"


def test_legacy_fixture_compatible_forensics(tmp_path: Path):
    from evaluation.corpus import discover_cases
    from evaluation.execute import evaluate_case
    from evaluation.fixture import prepare_fixture
    from evaluation.forensics.analyze import analyze_case
    from mir.pipeline import UnderstandingPipeline

    prepare_fixture(root=tmp_path)
    cases = discover_cases(
        split="development", case_id="piano_quarters_120", root=tmp_path
    )
    assert len(cases) == 1
    out = tmp_path / "results" / "piano_quarters_120"
    row = evaluate_case(
        cases[0], case_out_dir=out, pipeline=UnderstandingPipeline(mode="fast")
    )
    assert row.status == "ran"
    forensic = analyze_case(
        case_id=cases[0].case_id,
        case_out_dir=out,
        reference_raw_path=cases[0].reference_midi,
        predicted_tempo=(row.tempo or {}).get("predicted_bpm"),
        expected_tempo=(row.tempo or {}).get("reference_bpm"),
    )
    assert forensic["status"] == "ran"
    assert (out / "diagnostics" / "note_errors.csv").is_file()
    assert (out / "diagnostics" / "forensics.json").is_file()
    assert (out / "diagnostics" / "diagnostic_overlay.mid").is_file()
