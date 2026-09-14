"""Named Basic Pitch profiles and comparison summaries."""

from __future__ import annotations

from adapters.basic_pitch_backend import (
    BASIC_PITCH_PROFILES,
    DEFAULT_MAX_FREQ_HZ,
    DEFAULT_MIN_NOTE_LENGTH_MS,
    basic_pitch_settings,
    profile_for_stem,
)
from adapters.classical_dsp_backend import ClassicalDspBackend, ClassicalDspUnavailable
from evaluation.basic_pitch_profiles import (
    MUSICAL_CHALLENGES,
    precision_recall,
    settings_delta,
    summarize_profile_runs,
)
from mir.types import NoteEvent


def test_named_profiles_do_not_change_production_defaults(monkeypatch):
    monkeypatch.delenv("BASIC_PITCH_PROFILE", raising=False)
    for name in (
        "short_notes",
        "piano_extended",
        "bass",
        "quiet_passages",
        "ornaments",
    ):
        assert name in BASIC_PITCH_PROFILES
    production = BASIC_PITCH_PROFILES["production"]
    assert production["minimum_note_length"] == DEFAULT_MIN_NOTE_LENGTH_MS
    assert production["maximum_frequency"] == DEFAULT_MAX_FREQ_HZ
    assert basic_pitch_settings()["minimum_note_length"] == DEFAULT_MIN_NOTE_LENGTH_MS
    piano = BASIC_PITCH_PROFILES["piano_extended"]
    assert piano["maximum_frequency"] > DEFAULT_MAX_FREQ_HZ
    short = BASIC_PITCH_PROFILES["short_notes"]
    assert short["minimum_note_length"] < 125.0
    bass = BASIC_PITCH_PROFILES["bass"]
    assert bass["maximum_frequency"] < DEFAULT_MAX_FREQ_HZ


def test_profile_env_selects_named_settings_then_env_overlay(monkeypatch):
    monkeypatch.setenv("BASIC_PITCH_PROFILE", "piano_extended")
    monkeypatch.delenv("BASIC_PITCH_MAX_FREQ_HZ", raising=False)
    settings = basic_pitch_settings()
    assert settings["profile"] == "piano_extended"
    assert settings["maximum_frequency"] == 4186.0
    monkeypatch.setenv("BASIC_PITCH_MAX_FREQ_HZ", "3000")
    overlay = basic_pitch_settings()
    assert overlay["profile"] == "piano_extended"
    assert overlay["maximum_frequency"] == 3000.0
    assert overlay["env_overrides"]["BASIC_PITCH_MAX_FREQ_HZ"] == 3000.0


def test_stem_profile_hints_are_off_by_default(monkeypatch):
    monkeypatch.delenv("BASIC_PITCH_STEM_PROFILES", raising=False)
    assert profile_for_stem("bass") is None
    monkeypatch.setenv("BASIC_PITCH_STEM_PROFILES", "1")
    assert profile_for_stem("bass") == "bass"
    assert profile_for_stem("piano") == "piano_extended"


def test_profile_summary_does_not_name_a_winner_without_inference():
    skipped = [
        {"profile": "short_notes", "challenge": "ornaments", "inferred": False},
        {"profile": "production", "challenge": "bass", "inferred": False},
    ]
    summary = summarize_profile_runs(skipped)
    assert summary["status"] == "not_evaluated"
    assert summary["winner"] is None
    assert set(MUSICAL_CHALLENGES) >= {"short_notes", "high_piano", "quiet_passages"}
    delta = settings_delta("short_notes")
    assert "minimum_note_length" in delta["changed"]


def test_profile_summary_requires_precision_and_recall():
    rows = [
        {
            "profile": "short_notes",
            "inferred": True,
            "precision": 0.50,
            "recall": 0.95,
            "f1": 0.65,
        },
        {
            "profile": "production",
            "inferred": True,
            "precision": 0.80,
            "recall": 0.80,
            "f1": 0.80,
        },
    ]
    summary = summarize_profile_runs(rows)
    assert summary["status"] == "evaluated"
    assert summary["winner"] == "production"
    assert summary["by_profile"]["short_notes"]["mean_recall"] == 0.95


def test_precision_recall_does_not_optimize_recall_alone():
    reference = [NoteEvent(pitch=60, start_time=0.0, end_time=0.4)]
    greedy = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.4),
        NoteEvent(pitch=64, start_time=0.0, end_time=0.4),
        NoteEvent(pitch=67, start_time=0.0, end_time=0.4),
    ]
    metrics = precision_recall(greedy, reference)
    assert metrics["recall"] == 1.0
    assert metrics["precision"] < 1.0


def test_classical_dsp_is_marked_non_operational():
    backend = ClassicalDspBackend()
    assert backend.operational is False
    try:
        backend.transcribe_notes("unused.wav")
    except ClassicalDspUnavailable as exc:
        assert "not operational" in str(exc)
        return
    raise AssertionError("classical dsp should not transcribe")
