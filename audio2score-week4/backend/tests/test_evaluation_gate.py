"""Evaluation gate, CLI exit codes, and isolated/production policy parity."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pretty_midi
import pytest

from evaluation.execute import evaluate_case
from evaluation.gate import gate_decision
from evaluation.runner import main as evaluation_main
from evaluation.schema import parse_case_dir


def _write_midi(path: Path) -> Path:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5))
    midi.instruments.append(inst)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))
    return path


def _case_dir(tmp_path: Path, name: str = "c1", *, audio: bool = True, reference: bool = True) -> Path:
    d = tmp_path / "development" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "case.yaml").write_text(f"id: {name}\ntitle: {name}\n", encoding="utf-8")
    if audio:
        (d / "input.wav").write_bytes(b"RIFF")
    if reference:
        _write_midi(d / "reference.mid")
    return d


def test_gate_fails_on_execution_errors():
    decision = gate_decision({"ran": 1, "skipped": 0, "errors": 1, "case_count": 2})
    assert decision["passed"] is False
    assert "execution_errors" in decision["reasons"]
    assert decision["exit_code"] == 1


def test_gate_fails_when_all_cases_are_skipped():
    decision = gate_decision({"ran": 0, "skipped": 3, "errors": 0, "case_count": 3})
    assert decision["passed"] is False
    assert "all_skipped" in decision["reasons"]


def test_gate_fails_when_no_cases_ran():
    decision = gate_decision({"ran": 0, "skipped": 0, "errors": 0, "case_count": 0})
    assert decision["passed"] is False
    assert "no_cases_ran" in decision["reasons"]


def test_gate_fails_on_baseline_regression_and_missing_cases():
    comparison = {
        "counts": {"REGRESSED": 1, "IMPROVED": 0, "UNCHANGED": 0, "NEW": 0},
        "regressions": [
            {"id": "a", "status": "REGRESSED", "detail": "missing_from_current_run"},
            {"id": "b", "status": "REGRESSED"},
        ],
    }
    decision = gate_decision(
        {"ran": 1, "skipped": 0, "errors": 0},
        comparison,
        fail_on_regression=True,
    )
    assert decision["passed"] is False
    assert "baseline_regression" in decision["reasons"]
    assert "missing_required_cases" in decision["reasons"]


def test_gate_passes_clean_run():
    decision = gate_decision({"ran": 2, "skipped": 0, "errors": 0})
    assert decision["passed"] is True
    assert decision["exit_code"] == 0


def test_cli_all_skipped_exits_nonzero(tmp_path, monkeypatch):
    _case_dir(tmp_path, "skip_me", audio=False, reference=False)
    code = evaluation_main(
        [
            "--corpus-root",
            str(tmp_path),
            "--split",
            "development",
            "--results-dir",
            str(tmp_path / "results"),
            "--run-id",
            "gate-skip",
            "--execution-path",
            "isolated",
        ]
    )
    assert code == 1
    gate = json.loads((tmp_path / "results" / "gate-skip" / "gate.json").read_text())
    assert "all_skipped" in gate["reasons"]


def test_cli_compare_baseline_regression_exits_nonzero(tmp_path, monkeypatch):
    _case_dir(tmp_path, "reg")

    fake = SimpleNamespace(
        to_dict=lambda: {
            "id": "reg",
            "split": "development",
            "status": "ran",
            "notes": {"onset_pitch_f1": 0.40},
            "skip_reason": None,
            "error": None,
        },
        status="ran",
        skip_reason=None,
        error=None,
        notes={"onset_pitch_f1": 0.40},
    )
    monkeypatch.setattr("evaluation.runner.evaluate_case", lambda *a, **k: fake)

    baseline_dir = tmp_path / "baselines"
    baseline_dir.mkdir()
    (baseline_dir / "old.json").write_text(
        json.dumps(
            {
                "name": "old",
                "cases": [
                    {
                        "id": "reg",
                        "status": "ran",
                        "notes": {"onset_pitch_f1": 0.90},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    code = evaluation_main(
        [
            "--corpus-root",
            str(tmp_path),
            "--split",
            "development",
            "--results-dir",
            str(tmp_path / "results"),
            "--run-id",
            "gate-reg",
            "--baselines-dir",
            str(baseline_dir),
            "--compare-baseline",
            "old",
            "--execution-path",
            "isolated",
        ]
    )
    assert code == 1
    gate = json.loads((tmp_path / "results" / "gate-reg" / "gate.json").read_text())
    assert "baseline_regression" in gate["reasons"]


def test_cli_execution_error_exits_nonzero(tmp_path, monkeypatch):
    _case_dir(tmp_path, "boom")
    fake = SimpleNamespace(
        to_dict=lambda: {
            "id": "boom",
            "split": "development",
            "status": "error",
            "error": "RuntimeError: failed",
            "notes": {},
            "skip_reason": None,
        },
        status="error",
        skip_reason=None,
        error="RuntimeError: failed",
        notes={},
    )
    monkeypatch.setattr("evaluation.runner.evaluate_case", lambda *a, **k: fake)
    code = evaluation_main(
        [
            "--corpus-root",
            str(tmp_path),
            "--split",
            "development",
            "--results-dir",
            str(tmp_path / "results"),
            "--run-id",
            "gate-err",
            "--execution-path",
            "isolated",
        ]
    )
    assert code == 1


def test_isolated_and_production_share_skip_policy(tmp_path, monkeypatch):
    missing = parse_case_dir(_case_dir(tmp_path, "empty", audio=False, reference=False), "development")
    isolated = evaluate_case(missing, case_out_dir=tmp_path / "i", execution_path="isolated")
    production = evaluate_case(missing, case_out_dir=tmp_path / "p", execution_path="production")
    assert isolated.status == production.status == "skipped"
    assert isolated.skip_reason == production.skip_reason

    poly = parse_case_dir(_case_dir(tmp_path, "poly"), "development")
    monkeypatch.delenv("MT3_ENDPOINT", raising=False)
    monkeypatch.delenv("MT3_TRANSCRIBE_COMMAND", raising=False)
    monkeypatch.setenv("MT3_ENDPOINT", "")
    monkeypatch.setenv("MT3_TRANSCRIBE_COMMAND", "")
    iso_poly = evaluate_case(
        poly,
        case_out_dir=tmp_path / "ip",
        execution_path="isolated",
        mode="polyphonic",
    )
    prod_poly = evaluate_case(
        poly,
        case_out_dir=tmp_path / "pp",
        execution_path="production",
        mode="polyphonic",
    )
    assert iso_poly.status == prod_poly.status == "skipped"
    assert iso_poly.execution.get("missing_infrastructure") == "mt3"
    assert prod_poly.execution.get("missing_infrastructure") == "mt3"
    assert "MT3" in (iso_poly.skip_reason or "")


def test_production_path_uses_job_runner_and_records_hashes(tmp_path, monkeypatch):
    spec = parse_case_dir(_case_dir(tmp_path, "prod"), "development")
    called = {}

    def fake_run_job(audio_path, job_id, *, mode=None, filename=None):
        called["mode"] = mode
        called["job_id"] = job_id
        job_dir = Path(audio_path).parent / f"bp_{job_id}"
        job_dir.mkdir(parents=True, exist_ok=True)
        _write_midi(job_dir / f"{job_id}.raw.mid")
        xml = "<score-partwise version='3.1'></score-partwise>"
        (job_dir / f"{job_id}.musicxml").write_text(xml, encoding="utf-8")
        (job_dir / f"{job_id}.debug.json").write_text(
            json.dumps({"selected_meter": "4/4", "extra": {"backend": "basic_pitch"}}),
            encoding="utf-8",
        )
        (job_dir / f"{job_id}.transcription.json").write_text(
            json.dumps(
                {
                    "requested_backend": "basic_pitch",
                    "actual_backend": "basic_pitch",
                    "settings": {"profile": "production"},
                }
            ),
            encoding="utf-8",
        )
        return xml

    monkeypatch.setattr("engine.job_runner.run_job", fake_run_job)
    row = evaluate_case(
        spec,
        case_out_dir=tmp_path / "out",
        execution_path="production",
        mode="solo",
    )
    assert called["mode"] == "solo"
    assert called["job_id"] == "prod"
    assert row.status == "ran"
    assert row.execution["path"] == "production"
    assert row.execution["independent_instance"] is True
    assert row.hashes.get("input_audio_sha256")
    assert row.hashes.get("raw_midi_sha256")
    assert row.pipeline.get("actual_backend") == "basic_pitch"
    assert (row.validation_delta or {}).get("raw_note_count") == 1


def test_runner_creates_independent_pipeline_instances(tmp_path, monkeypatch):
    _case_dir(tmp_path, "a")
    _case_dir(tmp_path, "b")
    seen = []

    class FakeResult:
        def __init__(self, case_id):
            self.case_id = case_id
            self.status = "ran"
            self.skip_reason = None
            self.error = None
            self.notes = {"onset_pitch_f1": 0.9}

        def to_dict(self):
            return {
                "id": self.case_id,
                "split": "development",
                "status": "ran",
                "notes": self.notes,
            }

    def fake_evaluate(case, **kwargs):
        seen.append(
            {
                "pipeline": kwargs.get("pipeline"),
                "path": kwargs.get("execution_path"),
                "mode": kwargs.get("mode"),
            }
        )
        return FakeResult(case.case_id)

    monkeypatch.setattr("evaluation.runner.evaluate_case", fake_evaluate)
    code = evaluation_main(
        [
            "--corpus-root",
            str(tmp_path),
            "--split",
            "development",
            "--results-dir",
            str(tmp_path / "results"),
            "--run-id",
            "indep",
            "--execution-path",
            "isolated",
            "--mode",
            "solo",
        ]
    )
    assert code == 0
    assert len(seen) == 2
    assert all(item["pipeline"] is None for item in seen)
    assert all(item["path"] == "isolated" for item in seen)
    report = json.loads((tmp_path / "results" / "indep" / "results.json").read_text())
    assert report["pipeline_configuration"]["independent_pipeline_per_case"] is True
    assert report["pipeline_configuration"]["canonical_mode"] == "solo"
    assert report["git_full"]
