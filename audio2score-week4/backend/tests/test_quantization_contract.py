"""Production quantization execution, diagnostics, and fallback agree."""

import mido
import pytest

from mir.pipeline_config import (
    QuantizationMode,
    inspect_quantization_env,
    load_pipeline_config,
    parse_quantization_mode,
    production_quantization_mode,
    require_production_quantization_mode,
)
from mir.quantizer import MeasureQuantizer
from mir.models import MeterHypothesis
from mir.types import MusicalEvent


def _midi(path):
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend(
        [
            mido.MetaMessage("set_tempo", tempo=500000),
            mido.MetaMessage("time_signature", numerator=4, denominator=4),
            mido.Message("note_on", note=60, velocity=80, time=0),
            mido.Message("note_off", note=60, time=480),
        ]
    )
    midi.save(path)


def test_unknown_quantization_mode_is_rejected():
    with pytest.raises(ValueError, match="Unknown TRANSCRIPTION_QUANTIZATION_MODE"):
        parse_quantization_mode("not-a-mode")
    with pytest.raises(ValueError, match="Unsupported production"):
        require_production_quantization_mode("adaptive")


def test_experimental_env_falls_back_explicitly(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "off")
    snap = inspect_quantization_env()
    assert snap["valid"] is True
    assert snap["requested_quantization_mode"] == "off"
    assert snap["effective_quantization_mode"] == "performance"
    assert snap["quantization_mode_fallback"]
    cfg = load_pipeline_config()
    assert cfg.quantization_mode == QuantizationMode.PERFORMANCE
    assert cfg.extra["requested_quantization_mode"] == "off"
    assert cfg.extra["quantization_mode_fallback"]
    effective, reason = production_quantization_mode("off")
    assert effective == QuantizationMode.PERFORMANCE
    assert reason


def test_unknown_env_is_recorded_and_falls_back(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "foobar")
    snap = inspect_quantization_env()
    assert snap["valid"] is False
    assert "foobar" in (snap["error"] or "")
    assert snap["effective_quantization_mode"] == "performance"
    cfg = load_pipeline_config()
    assert cfg.quantization_mode == QuantizationMode.PERFORMANCE
    assert "foobar" in (cfg.extra.get("quantization_mode_error") or "")


def test_production_entry_point_agrees_with_diagnostics(tmp_path, monkeypatch):
    from engine.job_runner import run_job
    from mir.pipeline import UnderstandingPipeline

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "adaptive")
    monkeypatch.setenv("NEXTGEN_PIPELINE_MODE", "legacy")
    source = tmp_path / "job.mid"
    _midi(source)
    xml = run_job(source, "contract", mode="solo", filename="job.mid")
    assert "score-partwise" in xml.lower()
    pipe = UnderstandingPipeline()
    pipe.transcribe_midi(source, "contract-direct")
    assert pipe.config.quantization_mode == QuantizationMode.PERFORMANCE
    assert pipe.notation.last_quantization_mode == QuantizationMode.PERFORMANCE
    assert pipe.job.quantization.engine == "performance"
    extra = pipe.last_debug.extra
    assert extra["quantization_mode"] == "performance"
    assert extra["requested_quantization_mode"] == "adaptive"
    assert extra["quantization_mode_fallback"]
    settings_path = tmp_path / "bp_contract-direct" / "contract-direct.notation_settings.json"
    assert settings_path.exists()


def test_health_reports_requested_and_effective_quantization(monkeypatch):
    from main import health

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "adaptive")
    payload = health()
    assert payload["status"] == "ok"
    assert payload["quantization_mode"] == "performance"
    assert payload["requested_quantization_mode"] == "adaptive"
    assert payload["quantization_mode_fallback"]
    assert payload["pipeline_config"]["effective_quantization_mode"] == "performance"
    assert payload["pipeline_config"]["requested_quantization_mode"] == "adaptive"


def test_quantize_notation_rejects_experimental_mode():
    from mir.performance_score import quantize_notation

    events = [MusicalEvent(60, 0, 1, note_id="a", velocity=80)]
    meter = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
    with pytest.raises(ValueError, match="Unsupported production"):
        quantize_notation(
            events,
            meter,
            config=type("C", (), {"max_onset_move": 0.18})(),
            mode="off",
        )
    out, _decisions, report = MeasureQuantizer().quantize_production(events, meter)
    assert len(out) == 1
    assert report.summary["engine"] == "performance"
