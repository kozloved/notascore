"""Tests for Basic Pitch adapter settings and note-event amplitude."""

from __future__ import annotations

from unittest.mock import patch

import pretty_midi

from adapters.basic_pitch_backend import (
    DEFAULT_FRAME_THRESHOLD,
    DEFAULT_ONSET_THRESHOLD,
    BasicPitchBackend,
    basic_pitch_settings,
)


def test_basic_pitch_settings_defaults(monkeypatch):
    for key in (
        "BASIC_PITCH_ONSET_THRESHOLD",
        "BASIC_PITCH_FRAME_THRESHOLD",
        "BASIC_PITCH_MIN_NOTE_LENGTH_MS",
        "BASIC_PITCH_MIN_FREQ_HZ",
        "BASIC_PITCH_MAX_FREQ_HZ",
        "BASIC_PITCH_MELODIA_TRICK",
        "BASIC_PITCH_MULTIPLE_PITCH_BENDS",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = basic_pitch_settings()
    assert settings["onset_threshold"] == DEFAULT_ONSET_THRESHOLD
    assert settings["frame_threshold"] == DEFAULT_FRAME_THRESHOLD
    assert settings["minimum_frequency"] == 27.5
    assert settings["maximum_frequency"] == 2093.0
    assert settings["melodia_trick"] is True
    assert settings["multiple_pitch_bends"] is False


def test_basic_pitch_settings_from_env(monkeypatch):
    monkeypatch.setenv("BASIC_PITCH_ONSET_THRESHOLD", "0.7")
    monkeypatch.setenv("BASIC_PITCH_MELODIA_TRICK", "0")
    settings = basic_pitch_settings()
    assert settings["onset_threshold"] == 0.7
    assert settings["melodia_trick"] is False


@patch("adapters.basic_pitch_backend.predict")
def test_transcribe_notes_keeps_amplitude(mock_predict, tmp_path, monkeypatch):
    monkeypatch.delenv("BASIC_PITCH_ONSET_THRESHOLD", raising=False)
    mock_predict.return_value = (
        None,
        None,
        [
            (0.0, 0.5, 60, 0.8, None),
            (0.0, 0.4, 72, 0.2, None),
        ],
    )
    notes = BasicPitchBackend().transcribe_notes(tmp_path / "x.wav")
    assert len(notes) == 2
    loud = next(n for n in notes if n.pitch == 60)
    quiet = next(n for n in notes if n.pitch == 72)
    assert loud.confidence == 0.8
    assert quiet.confidence == 0.2
    assert loud.velocity == round(127 * 0.8)
    assert mock_predict.call_args.kwargs["onset_threshold"] == DEFAULT_ONSET_THRESHOLD
    assert mock_predict.call_args.kwargs["minimum_frequency"] == 27.5


@patch("adapters.basic_pitch_backend.predict")
def test_transcribe_notes_falls_back_to_pretty_midi(mock_predict, tmp_path):
    midi = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=64, start=0.0, end=0.5))
    midi.instruments.append(inst)
    mock_predict.return_value = (None, midi, None)

    notes = BasicPitchBackend().transcribe_notes(tmp_path / "x.wav")
    assert len(notes) == 1
    assert notes[0].pitch == 64
    assert notes[0].velocity == 80
    assert abs(notes[0].confidence - 80 / 127) < 1e-6
