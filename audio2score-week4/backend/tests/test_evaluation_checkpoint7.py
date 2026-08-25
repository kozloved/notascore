"""Checkpoint 7 evaluation package tests."""

from __future__ import annotations

import json
from pathlib import Path

import pretty_midi
import pytest

from evaluation.baselines import (
    classify_case,
    compare_to_baseline,
    save_baseline,
)
from evaluation.corpus import check_split_leakage, discover_cases
from evaluation.defaults import BASELINE_F1_EPSILON
from evaluation.execute import evaluate_case
from evaluation.fixture import prepare_fixture
from evaluation.matching import match_notes
from evaluation.normalize import normalize_reference_midi
from evaluation.report import build_report, render_markdown, write_reports
from evaluation.schema import parse_case_dir
from evaluation.stages import _first_degradation, StageSnapshot
from mir.types import Hand, NoteEvent


def _write_midi(path: Path, notes: list[tuple[int, float, float]], *, hand_tracks: bool = False) -> Path:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    if hand_tracks:
        rh = pretty_midi.Instrument(program=0, name="RH")
        lh = pretty_midi.Instrument(program=0, name="LH")
        for pitch, start, end in notes:
            n = pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=end)
            (rh if pitch >= 60 else lh).notes.append(n)
        if rh.notes:
            midi.instruments.append(rh)
        if lh.notes:
            midi.instruments.append(lh)
    else:
        inst = pretty_midi.Instrument(program=0, name="Piano")
        for pitch, start, end in notes:
            inst.notes.append(
                pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=end)
            )
        midi.instruments.append(inst)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))
    return path


def test_case_discovery_and_split_selection(tmp_path: Path):
    for split, name in (("development", "dev_a"), ("holdout", "hold_a")):
        d = tmp_path / split / name
        d.mkdir(parents=True)
        (d / "case.yaml").write_text(f"id: {name}\ntitle: {name}\n", encoding="utf-8")
        (d / "input.wav").write_bytes(b"RIFF")
        _write_midi(d / "reference.mid", [(60, 0.0, 0.5)])

    all_cases = discover_cases(root=tmp_path)
    assert {c.case_id for c in all_cases} == {"dev_a", "hold_a"}
    dev = discover_cases(split="development", root=tmp_path)
    assert len(dev) == 1 and dev[0].split == "development"
    one = discover_cases(case_id="hold_a", root=tmp_path)
    assert len(one) == 1 and one[0].case_id == "hold_a"


def test_manifest_parsing_optional_metadata(tmp_path: Path):
    d = tmp_path / "development" / "piano_x"
    d.mkdir(parents=True)
    (d / "case.yaml").write_text(
        "\n".join(
            [
                "id: piano_x",
                "title: Example",
                "instrument: piano",
                "reference:",
                "  midi: reference.mid",
                "expected:",
                '  meter: "3/4"',
                "  tempo_bpm: 90",
                "tags: [piano, meter]",
                "performance_id: shared_perf",
            ]
        ),
        encoding="utf-8",
    )
    (d / "input.wav").write_bytes(b"RIFF")
    _write_midi(d / "reference.mid", [(60, 0.0, 0.4)])
    spec = parse_case_dir(d, "development")
    assert spec.case_id == "piano_x"
    assert spec.expected_meter == "3/4"
    assert spec.expected_tempo_bpm == 90.0
    assert spec.performance_id == "shared_perf"
    assert "piano" in spec.tags
    assert not spec.missing_audio()
    assert not spec.missing_reference()


def test_missing_input_and_reference_detection(tmp_path: Path):
    d = tmp_path / "development" / "empty_case"
    d.mkdir(parents=True)
    (d / "case.yaml").write_text("id: empty_case\n", encoding="utf-8")
    spec = parse_case_dir(d, "development")
    assert spec.missing_audio()
    assert spec.missing_reference()

    from evaluation.execute import evaluate_case

    row = evaluate_case(spec, case_out_dir=tmp_path / "out")
    assert row.status == "skipped"
    assert "audio" in (row.skip_reason or "")


def test_missing_reference_skipped(tmp_path: Path):
    d = tmp_path / "development" / "no_ref"
    d.mkdir(parents=True)
    (d / "input.wav").write_bytes(b"RIFF")
    (d / "case.yaml").write_text("id: no_ref\n", encoding="utf-8")
    spec = parse_case_dir(d, "development")
    row = evaluate_case(spec, case_out_dir=tmp_path / "out2")
    assert row.status == "skipped"
    assert "reference" in (row.skip_reason or "")


def test_midi_normalization_does_not_mutate_source(tmp_path: Path):
    path = tmp_path / "ref.mid"
    _write_midi(
        path,
        [(48, 0.0, 0.5), (72, 0.0, 0.5), (60, 0.5, 1.0)],
        hand_tracks=True,
    )
    before = path.read_bytes()
    ref = normalize_reference_midi(path)
    after = path.read_bytes()
    assert before == after
    assert len(ref.notes) == 3
    assert ref.has_hand_labels is True
    assert sum(1 for n in ref.notes if n.hand == Hand.LEFT) >= 1
    assert sum(1 for n in ref.notes if n.hand == Hand.RIGHT) >= 1


def test_note_matching_and_tolerance_behavior():
    reference = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5),
        NoteEvent(pitch=64, start_time=0.5, end_time=1.0),
    ]
    # Within 50ms onset tolerance, same pitch
    predicted_ok = [
        NoteEvent(pitch=60, start_time=0.04, end_time=0.55),
        NoteEvent(pitch=64, start_time=0.52, end_time=1.05),
    ]
    ok = match_notes(predicted_ok, reference, onset_tolerance_sec=0.05)
    assert ok.matched == 2
    assert ok.onset_pitch_f1 == pytest.approx(1.0)
    assert ok.false_positives == 0
    assert ok.false_negatives == 0

    # Outside tolerance → miss
    predicted_late = [
        NoteEvent(pitch=60, start_time=0.20, end_time=0.7),
        NoteEvent(pitch=64, start_time=0.70, end_time=1.2),
    ]
    late = match_notes(predicted_late, reference, onset_tolerance_sec=0.05)
    assert late.matched == 0
    assert late.false_negatives == 2

    # Wrong pitch within onset window
    wrong_pitch = [
        NoteEvent(pitch=61, start_time=0.0, end_time=0.5),
        NoteEvent(pitch=65, start_time=0.5, end_time=1.0),
    ]
    pitch_miss = match_notes(wrong_pitch, reference, onset_tolerance_sec=0.05)
    assert pitch_miss.onset_f1 == pytest.approx(1.0)
    assert pitch_miss.onset_pitch_f1 == pytest.approx(0.0)


def test_stage_metric_first_degradation():
    stages = [
        StageSnapshot(
            name="transcription",
            notes=[],
            metrics={"onset_pitch_f1": 0.91, "predicted_count": 115},
        ),
        StageSnapshot(
            name="post_cleaner",
            notes=[],
            metrics={"onset_pitch_f1": 0.85, "predicted_count": 103},
        ),
        StageSnapshot(
            name="structured",
            notes=[],
            metrics={"onset_pitch_f1": 0.84, "predicted_count": 103},
        ),
    ]
    first, conclusion = _first_degradation(stages, reference_count=120)
    assert first == "post_cleaner"
    assert "cleaner" in conclusion.lower()
    assert "TRANSCRIPTION" in conclusion.upper() or "transcription" in conclusion.lower()


def test_baseline_comparison_and_regression_thresholds(tmp_path: Path):
    assert classify_case(0.88, 0.82, epsilon=0.01) == "IMPROVED"
    assert classify_case(0.80, 0.82, epsilon=0.01) == "REGRESSED"
    assert classify_case(0.825, 0.82, epsilon=0.01) == "UNCHANGED"
    assert classify_case(0.90, None, epsilon=0.01) == "NEW"

    current = [
        {
            "id": "a",
            "status": "ran",
            "split": "development",
            "notes": {"onset_pitch_f1": 0.88},
        },
        {
            "id": "b",
            "status": "ran",
            "split": "development",
            "notes": {"onset_pitch_f1": 0.70},
        },
        {
            "id": "c",
            "status": "ran",
            "split": "development",
            "notes": {"onset_pitch_f1": 0.90},
        },
    ]
    baseline = {
        "name": "t",
        "cases": [
            {"id": "a", "status": "ran", "notes": {"onset_pitch_f1": 0.82}},
            {"id": "b", "status": "ran", "notes": {"onset_pitch_f1": 0.80}},
        ],
    }
    cmp = compare_to_baseline(current, baseline, epsilon=BASELINE_F1_EPSILON)
    assert cmp["counts"]["IMPROVED"] == 1
    assert cmp["counts"]["REGRESSED"] == 1
    assert cmp["counts"]["NEW"] == 1
    assert cmp["aggregate"]["delta"] == pytest.approx(
        ((0.88 + 0.70 + 0.90) / 3) - ((0.82 + 0.80) / 2)
    )

    report = {
        "timestamp": "now",
        "git": "abc",
        "branch": "x",
        "split": "development",
        "aggregate": {},
        "cases": current,
    }
    path = save_baseline(report, "unit-baseline", root=tmp_path)
    assert path.is_file()


def test_report_generation_marks_holdout(tmp_path: Path):
    cases = [
        {
            "id": "h1",
            "split": "holdout",
            "status": "ran",
            "notes": {
                "onset_f1": 0.9,
                "onset_pitch_f1": 0.85,
                "reference_count": 10,
                "predicted_count": 10,
            },
            "meter": {"status": "correct", "predicted": "4/4", "expected": "4/4"},
            "tempo": {"status": "evaluated", "error_bpm": 1.0},
            "hands": {"status": "NOT_EVALUATED"},
            "stages": {"conclusion": "No large stage-to-stage F1 drop detected."},
        }
    ]
    report = build_report(
        cases=cases,
        repo=Path(__file__).resolve().parents[2],
        split="holdout",
        run_id="test-run",
    )
    md = render_markdown(report)
    assert "HOLDOUT EVALUATION" in md
    assert "Do not repeatedly tune" in md
    paths = write_reports(report, tmp_path / "run")
    assert paths["json"].is_file()
    assert paths["markdown"].is_file()
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert payload["run_id"] == "test-run"


def test_split_leakage_warning(tmp_path: Path):
    for split in ("development", "holdout"):
        d = tmp_path / split / f"{split}_render"
        d.mkdir(parents=True)
        (d / "case.yaml").write_text(
            "id: x\nperformance_id: shared_song\n",
            encoding="utf-8",
        )
        (d / "input.wav").write_bytes(b"RIFF")
        _write_midi(d / "reference.mid", [(60, 0.0, 0.3)])
    cases = discover_cases(root=tmp_path)
    warnings = check_split_leakage(cases)
    assert warnings
    assert "development and holdout" in warnings[0]


def test_prepare_fixture_and_end_to_end_evaluation(tmp_path: Path):
    """Minimal repository-safe vertical slice through the production pipeline."""
    case_dir = prepare_fixture(root=tmp_path)
    assert (case_dir / "input.wav").is_file()
    assert (case_dir / "reference.mid").is_file()
    assert (case_dir / "case.yaml").is_file()

    cases = discover_cases(split="development", case_id="piano_quarters_120", root=tmp_path)
    assert len(cases) == 1
    from mir.pipeline import UnderstandingPipeline

    pipeline = UnderstandingPipeline(mode="fast")
    row = evaluate_case(
        cases[0],
        case_out_dir=tmp_path / "results" / "piano_quarters_120",
        pipeline=pipeline,
    )
    assert row.status == "ran"
    assert row.notes.get("onset_pitch_f1") is not None
    assert row.pipeline.get("musicxml_success") is True
    out = tmp_path / "results" / "piano_quarters_120"
    assert (out / "transcription.mid").is_file()
    assert (out / "post_cleaner.mid").is_file()
    assert (out / "post_piano.mid").is_file()
    assert (out / "structured.mid").is_file()
    assert (out / "output.musicxml").is_file()
    assert (out / "metrics.json").is_file()
    assert (out / "diagnostics.json").is_file()
    assert (out / "report.md").is_file()
    report_text = (out / "report.md").read_text(encoding="utf-8")
    assert "TRANSCRIPTION" in report_text or "Stage" in report_text or "F1" in report_text
    assert pipeline.last_raw_notes is not None
    stage_names = [s["name"] for s in (row.stages or {}).get("stages") or []]
    assert "transcription" in stage_names
    assert (row.stages or {}).get("pipeline", {}).get("stage_source") == "pipeline_snapshots"


def test_stage_capture_does_not_reinvoke_basic_pitch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Regression: evaluation must not re-transcribe for stage MIDIs."""
    from adapters.basic_pitch_backend import BasicPitchBackend

    calls = {"n": 0}
    original = BasicPitchBackend.transcribe_notes

    def wrapped(self, audio_path):
        calls["n"] += 1
        return original(self, audio_path)

    monkeypatch.setattr(BasicPitchBackend, "transcribe_notes", wrapped)

    prepare_fixture(root=tmp_path)
    cases = discover_cases(split="development", case_id="piano_quarters_120", root=tmp_path)
    from mir.pipeline import UnderstandingPipeline

    pipeline = UnderstandingPipeline(mode="fast")
    row = evaluate_case(
        cases[0],
        case_out_dir=tmp_path / "results" / "once",
        pipeline=pipeline,
    )
    assert row.status == "ran"
    assert calls["n"] == 1
    assert pipeline.last_raw_notes is not None
    assert pipeline.last_cleaned_notes is not None
    stages = {s["name"]: s for s in (row.stages or {}).get("stages") or []}
    assert stages["transcription"]["note_count"] == len(pipeline.last_raw_notes)
    assert stages["post_cleaner"]["note_count"] == len(pipeline.last_cleaned_notes)
