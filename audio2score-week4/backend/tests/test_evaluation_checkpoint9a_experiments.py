"""Checkpoint 9A transcription experiment matrix tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from adapters.basic_pitch_backend import (
    DEFAULT_FRAME_THRESHOLD,
    DEFAULT_MIN_NOTE_LENGTH_MS,
    DEFAULT_ONSET_THRESHOLD,
)
from evaluation.experiments.config import (
    PRODUCTION_FRAME_THRESHOLD,
    PRODUCTION_MIN_NOTE_LENGTH_MS,
    PRODUCTION_ONSET_THRESHOLD,
    ExperimentConfig,
    PreprocessConfig,
    TranscriptionParams,
    UnsupportedParameterError,
    production_preprocess,
)
from evaluation.experiments.metrics import (
    CaseExperimentMetrics,
    aggregate_experiment,
    compute_case_metrics,
    rank_experiments,
)
from evaluation.experiments.preprocess import apply_preprocess, detect_redundant_preprocess
from evaluation.experiments.registry import (
    all_experiment_names,
    get_experiment,
    list_experiments,
)
from evaluation.experiments.reports import save_case_result, save_run_manifest
from evaluation.experiments.transcription import (
    ExperimentBasicPitchAdapter,
    production_settings_snapshot,
    validate_predict_params,
)
from mir.types import NoteEvent


def _n(pitch: int, start: float, end: float) -> NoteEvent:
    return NoteEvent(pitch=pitch, start_time=start, end_time=end, velocity=80)


def test_experiment_configuration_discovery():
    names = all_experiment_names(include_skipped=True)
    assert "basic_pitch_baseline" in names
    assert "A1_mono_native" in names
    assert "B1_lower_onset" in names
    assert any(n.startswith("C") for n in names)
    configs = list_experiments(include_skipped=False)
    assert all(not c.is_skipped for c in configs)
    baseline = get_experiment("basic_pitch_baseline")
    assert baseline.axis == "baseline"


def test_baseline_adapter_mirrors_production_defaults():
    baseline = get_experiment("basic_pitch_baseline")
    tp = baseline.transcription
    assert tp.onset_threshold == DEFAULT_ONSET_THRESHOLD == PRODUCTION_ONSET_THRESHOLD
    assert tp.frame_threshold == DEFAULT_FRAME_THRESHOLD == PRODUCTION_FRAME_THRESHOLD
    assert tp.minimum_note_length == DEFAULT_MIN_NOTE_LENGTH_MS == PRODUCTION_MIN_NOTE_LENGTH_MS
    assert baseline.preprocess.use_production_normalizer is True


def test_experiment_isolation_from_production_configuration(monkeypatch):
    """Experiment adapter must not pick up BASIC_PITCH_* env overrides."""
    monkeypatch.setenv("BASIC_PITCH_ONSET_THRESHOLD", "0.99")
    monkeypatch.setenv("BASIC_PITCH_FRAME_THRESHOLD", "0.99")
    snap = production_settings_snapshot()
    # Production env-resolved settings change...
    assert snap["env_resolved"]["onset_threshold"] == 0.99
    # ...but experiment production() params stay at module defaults.
    params = TranscriptionParams.production().to_predict_kwargs()
    assert params["onset_threshold"] == PRODUCTION_ONSET_THRESHOLD
    assert params["frame_threshold"] == PRODUCTION_FRAME_THRESHOLD
    # Module defaults themselves unchanged
    assert snap["module_defaults"]["onset_threshold"] == PRODUCTION_ONSET_THRESHOLD


def test_unsupported_parameter_handling():
    with pytest.raises(UnsupportedParameterError):
        validate_predict_params({"onset_threshold": 0.5, "not_a_real_param": 1})
    with pytest.raises(UnsupportedParameterError):
        TranscriptionParams.from_dict({"onset_threshold": 0.5, "magic_knob": 3})


def test_preprocessing_preserves_duration_time_alignment(tmp_path: Path):
    sr = 44100
    duration = 1.5
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    # Leading/trailing quiet + mid tone
    y = 0.01 * np.random.randn(t.size).astype(np.float32)
    mid = slice(int(0.3 * sr), int(1.2 * sr))
    y[mid] = 0.4 * np.sin(2 * np.pi * 440 * t[mid]).astype(np.float32)
    wav = tmp_path / "in.wav"
    sf.write(str(wav), y, sr)

    cfg = PreprocessConfig(
        name="trim_test",
        mono=True,
        target_sr=22050,
        peak_normalize=True,
        remove_dc=True,
        trim_silence=True,
    )
    result = apply_preprocess(wav, cfg, out_path=tmp_path / "out.wav")
    # Duration should stay approximately equal (resample changes sample count,
    # but time length must align within a small tolerance).
    assert abs(result.output_probe.duration_sec - result.input_probe.duration_sec) < 0.02
    assert result.to_dict()["time_alignment_preserved"] is True


def test_production_preprocess_fingerprint_redundancy():
    a = production_preprocess()
    b = PreprocessConfig(
        name="dup",
        use_production_normalizer=True,
        mono=True,
        target_sr=22050,
        peak_normalize=True,
    )
    reason = detect_redundant_preprocess(b, a)
    assert reason is not None


def test_result_serialization(tmp_path: Path):
    metrics = CaseExperimentMetrics(
        case_id="CaseX",
        experiment="basic_pitch_baseline",
        predicted_note_count=3,
        reference_note_count=3,
        onset_precision=1.0,
        onset_recall=1.0,
        onset_f1=1.0,
        onset_pitch_precision=1.0,
        onset_pitch_recall=1.0,
        onset_pitch_f1=1.0,
        false_positives=0,
        false_negatives=0,
        taxonomy_false_positives=0,
        taxonomy_false_negatives=0,
        pitch_errors=0,
        fragmented_notes=0,
        merged_notes=0,
        duplicate_notes=0,
        onset_errors=0,
        median_onset_error_ms=1.0,
        mean_onset_error_ms=1.0,
        p90_onset_error_ms=1.0,
    )
    path = save_case_result(tmp_path, metrics)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["case_id"] == "CaseX"
    assert loaded["onset_pitch_f1"] == 1.0
    manifest_path = save_run_manifest(
        tmp_path,
        {"run_id": "test", "git_commit": "abc", "configurations": []},
    )
    assert manifest_path.is_file()


def test_macro_averaging_and_per_case_regression():
    def _m(case: str, exp: str, f1: float, fn: int = 1, fp: int = 1) -> CaseExperimentMetrics:
        return CaseExperimentMetrics(
            case_id=case,
            experiment=exp,
            predicted_note_count=10,
            reference_note_count=10,
            onset_precision=f1,
            onset_recall=f1,
            onset_f1=f1,
            onset_pitch_precision=f1,
            onset_pitch_recall=f1,
            onset_pitch_f1=f1,
            false_positives=fp,
            false_negatives=fn,
            taxonomy_false_positives=fp,
            taxonomy_false_negatives=fn,
            pitch_errors=0,
            fragmented_notes=0,
            merged_notes=0,
            duplicate_notes=0,
            onset_errors=0,
            median_onset_error_ms=None,
            mean_onset_error_ms=None,
            p90_onset_error_ms=None,
        )

    baseline = {
        "Case1": _m("Case1", "basic_pitch_baseline", 0.10),
        "Case2": _m("Case2", "basic_pitch_baseline", 0.20),
        "Case3": _m("Case3", "basic_pitch_baseline", 0.30),
    }
    # Improves two cases, slight regression on one
    exp_cases = [
        _m("Case1", "B1", 0.20),
        _m("Case2", "B1", 0.28),
        _m("Case3", "B1", 0.29),
    ]
    agg = aggregate_experiment("B1", exp_cases, baseline_by_case=baseline)
    assert abs(agg.experiment_mean_f1 - (0.20 + 0.28 + 0.29) / 3) < 1e-9
    assert agg.per_case_delta["Case1"] == pytest.approx(0.10)
    assert agg.per_case_delta["Case3"] == pytest.approx(-0.01)
    assert agg.regression_count == 1
    assert agg.improved_count == 2
    assert agg.worst_case_delta == pytest.approx(-0.01)
    assert agg.promising is True


def test_aggregate_ranking_primary_key_is_mean_f1():
    def _agg(name: str, f1: float, fn: int = 10) -> CaseExperimentMetrics:
        # Build via aggregate_experiment for realism
        cases = [
            CaseExperimentMetrics(
                case_id="C",
                experiment=name,
                predicted_note_count=5,
                reference_note_count=5,
                onset_precision=f1,
                onset_recall=f1,
                onset_f1=f1,
                onset_pitch_precision=f1,
                onset_pitch_recall=f1,
                onset_pitch_f1=f1,
                false_positives=1,
                false_negatives=fn,
                taxonomy_false_positives=1,
                taxonomy_false_negatives=fn,
                pitch_errors=0,
                fragmented_notes=0,
                merged_notes=0,
                duplicate_notes=0,
                onset_errors=0,
                median_onset_error_ms=None,
                mean_onset_error_ms=None,
                p90_onset_error_ms=None,
            )
        ]
        return aggregate_experiment(name, cases, baseline_by_case=None)

    a = _agg("low", 0.1, fn=1)
    b = _agg("high", 0.5, fn=9)
    ranked = rank_experiments([a, b])
    assert ranked[0].experiment == "high"


def test_compute_case_metrics_absolute_time():
    ref = [_n(60, 0.0, 0.5), _n(64, 1.0, 1.5)]
    pred = [_n(60, 0.01, 0.5), _n(70, 2.0, 2.5)]
    m = compute_case_metrics(
        case_id="t",
        experiment="x",
        reference=ref,
        predicted=pred,
    )
    assert m.reference_note_count == 2
    assert m.predicted_note_count == 2
    assert m.false_negatives >= 1
    assert m.false_positives >= 1
    assert 0.0 <= m.onset_pitch_f1 <= 1.0


def test_reproducible_configuration_metadata():
    cfg = get_experiment("B6_lower_onset_frame")
    d = cfg.to_dict()
    assert d["transcription"]["onset_threshold"] == 0.5
    assert d["transcription"]["frame_threshold"] == 0.3
    assert d["preprocess"]["use_production_normalizer"] is True
    # Round-trip transcription params
    tp = TranscriptionParams.from_dict(d["transcription"])
    assert tp.to_predict_kwargs()["onset_threshold"] == 0.5


def test_cli_list_exits_zero():
    from evaluation.experiments.runner import main

    assert main(["--list"]) == 0
