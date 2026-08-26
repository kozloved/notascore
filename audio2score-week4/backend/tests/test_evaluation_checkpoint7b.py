"""Checkpoint 7B — two-reference evaluation resolution and mapping tests."""

from __future__ import annotations

from pathlib import Path

import pretty_midi
import pytest

from evaluation.execute import evaluate_case
from evaluation.schema import (
    parse_case_dir,
    resolve_references,
)
from evaluation.stages import capture_transcription_stages
from mir.types import MusicalEvent, NoteEvent, TempoMap, TempoPoint


def _write_midi(
    path: Path,
    notes: list[tuple[int, float, float]],
    *,
    tempo: float = 120.0,
) -> Path:
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    for pitch, start, end in notes:
        inst.notes.append(
            pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=end)
        )
    midi.instruments.append(inst)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))
    return path


def _tiny_wav(path: Path) -> Path:
    # Minimal RIFF placeholder; pipeline tests that need real audio use prepare_fixture.
    path.write_bytes(b"RIFF")
    return path


def test_legacy_reference_mid_compatibility(tmp_path: Path):
    d = tmp_path / "legacy"
    d.mkdir()
    _tiny_wav(d / "input.wav")
    _write_midi(d / "reference.mid", [(60, 0.0, 0.5), (64, 0.5, 1.0)])
    res = resolve_references(d)
    assert res.raw_path is not None and res.raw_path.name == "reference.mid"
    assert res.score_path is not None and res.score_path.name == "reference.mid"
    assert res.raw_legacy_fallback is True
    assert res.score_legacy_fallback is True
    assert res.same_file is True
    spec = parse_case_dir(d, "development")
    assert not spec.missing_reference()
    assert not spec.missing_raw_reference()
    assert not spec.missing_score_reference()


def test_raw_only_case(tmp_path: Path):
    d = tmp_path / "raw_only"
    d.mkdir()
    _tiny_wav(d / "input.wav")
    _write_midi(d / "reference_raw.mid", [(60, 0.0, 0.4)])
    res = resolve_references(d)
    assert res.raw_path is not None and res.raw_path.name == "reference_raw.mid"
    assert res.score_path is None
    assert res.raw_legacy_fallback is False
    assert res.score_legacy_fallback is False
    assert res.same_file is False
    spec = parse_case_dir(d, "development")
    assert not spec.missing_reference()
    assert not spec.missing_raw_reference()
    assert spec.missing_score_reference()


def test_score_only_case(tmp_path: Path):
    d = tmp_path / "score_only"
    d.mkdir()
    _tiny_wav(d / "input.wav")
    _write_midi(d / "reference_score.mid", [(62, 0.0, 0.5), (65, 0.5, 1.0)])
    res = resolve_references(d)
    assert res.raw_path is None
    assert res.score_path is not None and res.score_path.name == "reference_score.mid"
    spec = parse_case_dir(d, "development")
    assert not spec.missing_reference()
    assert spec.missing_raw_reference()
    assert not spec.missing_score_reference()


def test_both_references_preferred_layout(tmp_path: Path):
    d = tmp_path / "both"
    d.mkdir()
    _tiny_wav(d / "input.wav")
    _write_midi(d / "reference_raw.mid", [(60, 0.0, 0.4), (64, 0.4, 0.8)])
    _write_midi(d / "reference_score.mid", [(60, 0.0, 0.5)])
    res = resolve_references(d)
    assert res.raw_path.name == "reference_raw.mid"
    assert res.score_path.name == "reference_score.mid"
    assert res.raw_legacy_fallback is False
    assert res.score_legacy_fallback is False
    assert res.same_file is False
    spec = parse_case_dir(d, "development")
    assert len(spec.reference_raw_midi.read_bytes()) != len(
        spec.reference_score_midi.read_bytes()
    )


def test_missing_both_references(tmp_path: Path):
    d = tmp_path / "none"
    d.mkdir()
    _tiny_wav(d / "input.wav")
    (d / "case.yaml").write_text("id: none\n", encoding="utf-8")
    spec = parse_case_dir(d, "development")
    assert spec.missing_reference()
    row = evaluate_case(spec, case_out_dir=tmp_path / "out_none")
    assert row.status == "skipped"
    assert "reference" in (row.skip_reason or "")


def test_different_note_counts_do_not_break_resolution(tmp_path: Path):
    d = tmp_path / "diff_counts"
    d.mkdir()
    _write_midi(
        d / "reference_raw.mid",
        [(60, 0.0, 0.2), (62, 0.2, 0.4), (64, 0.4, 0.6)],
    )
    _write_midi(d / "reference_score.mid", [(60, 0.0, 0.5)])
    res = resolve_references(d)
    assert res.same_file is False
    assert res.raw_path != res.score_path


def test_legacy_fallback_reporting(tmp_path: Path):
    d = tmp_path / "legacy_report"
    d.mkdir()
    _write_midi(d / "reference.mid", [(60, 0.0, 0.3)])
    res = resolve_references(d)
    payload = res.to_dict()
    assert payload["raw_legacy_fallback"] is True
    assert payload["score_legacy_fallback"] is True
    assert payload["same_file"] is True
    assert payload["raw_source"] == "reference.mid"
    assert payload["score_source"] == "reference.mid"


def test_stage_reference_mapping_raw_vs_score(tmp_path: Path):
    raw_ref = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5),
        NoteEvent(pitch=64, start_time=0.5, end_time=1.0),
    ]
    score_ref = [NoteEvent(pitch=60, start_time=0.0, end_time=1.0)]
    predicted = [
        NoteEvent(pitch=60, start_time=0.01, end_time=0.49),
        NoteEvent(pitch=64, start_time=0.51, end_time=0.99),
    ]
    events = [
        MusicalEvent(
            pitch=60,
            start_beat=0.0,
            duration_beats=2.0,
            velocity=80,
            confidence=1.0,
            start_time_sec=0.0,
            end_time_sec=1.0,
        )
    ]
    diag = capture_transcription_stages(
        out_dir=tmp_path / "stages",
        reference_notes=raw_ref,
        reference_score_notes=score_ref,
        has_raw_reference=True,
        has_score_reference=True,
        raw_notes=predicted,
        cleaned_notes=predicted,
        post_piano_notes=predicted,
        structured_events=events,
        tempo_map=TempoMap(points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0)]),
        tempo_bpm=120.0,
    )
    by_name = {s.name: s for s in diag.stages}
    assert by_name["transcription"].reference_role == "raw"
    assert by_name["post_cleaner"].reference_role == "raw"
    assert by_name["structured"].reference_role == "score"
    assert by_name["transcription"].metrics.get("reference_count") == 2
    assert by_name["structured"].metrics.get("reference_count") == 1
    assert diag.score_evaluation.get("status") == "evaluated"


def test_raw_only_marks_score_unavailable(tmp_path: Path):
    raw_ref = [NoteEvent(pitch=60, start_time=0.0, end_time=0.5)]
    predicted = [NoteEvent(pitch=60, start_time=0.0, end_time=0.5)]
    events = [
        MusicalEvent(
            pitch=60,
            start_beat=0.0,
            duration_beats=1.0,
            velocity=80,
            confidence=1.0,
            start_time_sec=0.0,
            end_time_sec=0.5,
        )
    ]
    diag = capture_transcription_stages(
        out_dir=tmp_path / "raw_only_stages",
        reference_notes=raw_ref,
        reference_score_notes=None,
        has_raw_reference=True,
        has_score_reference=False,
        raw_notes=predicted,
        cleaned_notes=predicted,
        post_piano_notes=predicted,
        structured_events=events,
        tempo_map=None,
        tempo_bpm=120.0,
    )
    assert diag.score_evaluation.get("status") == "unavailable"
    structured = next(s for s in diag.stages if s.name == "structured")
    assert structured.metrics == {}
    assert structured.reference_role is None


def test_score_only_does_not_fake_raw_f1(tmp_path: Path):
    score_ref = [NoteEvent(pitch=60, start_time=0.0, end_time=0.5)]
    predicted = [NoteEvent(pitch=60, start_time=0.0, end_time=0.5)]
    events = [
        MusicalEvent(
            pitch=60,
            start_beat=0.0,
            duration_beats=1.0,
            velocity=80,
            confidence=1.0,
            start_time_sec=0.0,
            end_time_sec=0.5,
        )
    ]
    diag = capture_transcription_stages(
        out_dir=tmp_path / "score_only_stages",
        reference_notes=None,
        reference_score_notes=score_ref,
        has_raw_reference=False,
        has_score_reference=True,
        raw_notes=predicted,
        cleaned_notes=predicted,
        post_piano_notes=predicted,
        structured_events=events,
        tempo_map=None,
        tempo_bpm=120.0,
    )
    transcription = next(s for s in diag.stages if s.name == "transcription")
    assert transcription.metrics == {}
    assert transcription.extra.get("raw_evaluation") == "unavailable"
    assert diag.score_evaluation.get("status") == "evaluated"


def test_neither_reference_midi_is_modified(tmp_path: Path):
    d = tmp_path / "immutable"
    d.mkdir()
    raw = _write_midi(d / "reference_raw.mid", [(60, 0.0, 0.4), (67, 0.4, 0.8)])
    score = _write_midi(d / "reference_score.mid", [(60, 0.0, 0.5)])
    before_raw = raw.read_bytes()
    before_score = score.read_bytes()
    from evaluation.normalize import normalize_reference_midi

    normalize_reference_midi(raw)
    normalize_reference_midi(score)
    resolve_references(d)
    assert raw.read_bytes() == before_raw
    assert score.read_bytes() == before_score


def test_checkpoint7_fixture_remains_compatible(tmp_path: Path):
    from evaluation.corpus import discover_cases
    from evaluation.fixture import prepare_fixture
    from mir.pipeline import UnderstandingPipeline

    case_dir = prepare_fixture(root=tmp_path)
    assert (case_dir / "reference.mid").is_file()
    cases = discover_cases(
        split="development", case_id="piano_quarters_120", root=tmp_path
    )
    assert len(cases) == 1
    spec = cases[0]
    assert spec.reference_resolution.raw_legacy_fallback is True
    assert spec.reference_resolution.score_legacy_fallback is True
    assert spec.reference_resolution.same_file is True

    pipeline = UnderstandingPipeline(mode="fast")
    row = evaluate_case(
        spec,
        case_out_dir=tmp_path / "results" / "piano_quarters_120",
        pipeline=pipeline,
    )
    assert row.status == "ran"
    assert row.reference.get("raw_legacy_fallback") is True
    assert (row.metrics.get("raw") or {}).get("onset_pitch_f1") is not None
    # Legacy single file also acts as score reference
    assert (row.metrics.get("score") or {}).get("status") == "evaluated"


def test_manifest_raw_score_paths(tmp_path: Path):
    d = tmp_path / "manifested"
    d.mkdir()
    _tiny_wav(d / "input.wav")
    _write_midi(d / "perf.mid", [(60, 0.0, 0.3)])
    _write_midi(d / "quant.mid", [(60, 0.0, 0.5)])
    (d / "case.yaml").write_text(
        "\n".join(
            [
                "id: manifested",
                "reference:",
                "  raw: perf.mid",
                "  score: quant.mid",
            ]
        ),
        encoding="utf-8",
    )
    spec = parse_case_dir(d, "development")
    assert spec.reference_raw_midi.name == "perf.mid"
    assert spec.reference_score_midi.name == "quant.mid"
    assert "manifest:" in (spec.reference_resolution.raw_source or "")
    assert "manifest:" in (spec.reference_resolution.score_source or "")
