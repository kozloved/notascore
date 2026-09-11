"""Canonical pipeline configuration."""

import pytest

from mir.midi_cleaner import MIDICleaner
from mir.pipeline_config import (
    HandSeparatorMode,
    ValidationMode,
    load_pipeline_config,
    parse_hand_separator_mode,
    resolve_validation_mode,
)


def test_mt3_defaults_to_strict_safe(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_VALIDATION_MODE", raising=False)
    assert resolve_validation_mode("mt3") == ValidationMode.STRICT_SAFE
    cfg = load_pipeline_config(backend="mt3")
    assert cfg.validation_mode == ValidationMode.STRICT_SAFE
    assert cfg.enable_piano_analysis is False
    assert cfg.enable_gemini is False


def test_basic_pitch_defaults_to_conservative(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_VALIDATION_MODE", raising=False)
    assert resolve_validation_mode("basic_pitch") == ValidationMode.CONSERVATIVE
    cleaner = MIDICleaner.for_source("basic_pitch")
    assert cleaner.mode == ValidationMode.CONSERVATIVE
    assert cleaner.snap_chords is False
    assert cleaner.stretch_final_note is False
    assert cleaner.drop_octave_ghosts is True
    safe = MIDICleaner.for_source("mt3")
    assert safe.trim_overlaps is False
    assert safe.merge_threshold_sec == 0.001


def test_hand_separator_defaults_to_viterbi(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_HAND_SEPARATOR", raising=False)
    cfg = load_pipeline_config()
    assert cfg.hand_separator == HandSeparatorMode.VITERBI
    assert parse_hand_separator_mode("pm2s") == HandSeparatorMode.PM2S
    assert parse_hand_separator_mode("pm25") == HandSeparatorMode.PM2S
    assert parse_hand_separator_mode("") == HandSeparatorMode.VITERBI


def test_pm2s_required_defaults_off(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_PM2S_REQUIRED", raising=False)
    cfg = load_pipeline_config()
    assert cfg.pm2s_required is False
    monkeypatch.setenv("TRANSCRIPTION_PM2S_REQUIRED", "1")
    assert load_pipeline_config().pm2s_required is True


def test_hand_separator_env_override(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_HAND_SEPARATOR", "pm2s")
    assert load_pipeline_config().hand_separator == HandSeparatorMode.PM2S


def test_unknown_hand_separator_rejected():
    with pytest.raises(ValueError, match="TRANSCRIPTION_HAND_SEPARATOR"):
        parse_hand_separator_mode("piano_svsep")


def test_hand_separator_performance_alias_is_viterbi(monkeypatch):
    from mir.pipeline_config import inspect_hand_separator_env

    assert parse_hand_separator_mode("performance") == HandSeparatorMode.VITERBI
    monkeypatch.setenv("TRANSCRIPTION_HAND_SEPARATOR", "performance")
    snap = inspect_hand_separator_env()
    assert snap["valid"] is True
    assert snap["effective_hand_separator"] == "viterbi"
    assert snap["warning"]
    assert "performance" in (snap["warning"] or "")


def test_unknown_hand_separator_job_fallback_records_error(monkeypatch):
    from mir.pipeline_config import inspect_hand_separator_env

    monkeypatch.setenv("TRANSCRIPTION_HAND_SEPARATOR", "foobar")
    snap = inspect_hand_separator_env()
    assert snap["valid"] is False
    assert "foobar" in (snap["error"] or "")
    assert snap["effective_hand_separator"] == "viterbi"
    cfg = load_pipeline_config()
    assert cfg.hand_separator == HandSeparatorMode.VITERBI
    assert "foobar" in (cfg.extra.get("hand_separator_error") or "")


def test_env_override_validation_mode(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_VALIDATION_MODE", "legacy_aggressive")
    assert resolve_validation_mode("mt3") == ValidationMode.LEGACY_AGGRESSIVE
    # explicit constructor still wins
    assert (
        resolve_validation_mode("mt3", explicit="safe") == ValidationMode.STRICT_SAFE
    )


def test_cleaner_constructor_stays_legacy_for_unit_tests():
    cleaner = MIDICleaner()
    assert cleaner.mode == ValidationMode.LEGACY_AGGRESSIVE
    assert cleaner.snap_chords is True
    assert cleaner.stretch_final_note is True
