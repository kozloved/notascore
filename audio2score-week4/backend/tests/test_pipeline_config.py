"""Canonical pipeline configuration."""

from mir.midi_cleaner import MIDICleaner
from mir.pipeline_config import (
    ValidationMode,
    load_pipeline_config,
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
