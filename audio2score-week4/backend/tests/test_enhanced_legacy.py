"""Tests for Phase 2 enhanced legacy transcription path."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent
from transcription import (
    BasicPitchEngine,
    _estimate_tempo,
    _use_beat_tracker,
    _use_normalizer,
    _use_piano_analyzer,
)


def test_env_enabled_defaults():
    assert _use_normalizer() is True
    assert _use_beat_tracker() is True
    assert _use_piano_analyzer() is True


def test_env_enabled_can_disable(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_USE_NORMALIZER", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_BEAT_TRACKER", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_PIANO_ANALYZER", "0")
    assert _use_normalizer() is False
    assert _use_beat_tracker() is False
    assert _use_piano_analyzer() is False


def test_estimate_tempo_uses_refine(monkeypatch, tmp_path):
    monkeypatch.setenv("TRANSCRIPTION_USE_BEAT_TRACKER", "0")
    audio = tmp_path / "t.wav"
    sr = 22050
    t = np.linspace(0, 2, sr * 2)
    sf.write(str(audio), 0.2 * np.sin(2 * np.pi * 440 * t), sr)
    bpm = _estimate_tempo(audio, [0.0, 0.5, 1.0, 1.5])
    assert 50 <= bpm <= 200


@patch("adapters.basic_pitch_backend.predict")
@patch("audio_engine.instrument_classifier.InstrumentClassifier.classify")
@patch("audio_engine.piano_analyzer.PianoAudioAnalyzer.analyze")
def test_enhanced_legacy_piano_velocity_refine(
    mock_piano_analyze,
    mock_classify,
    mock_predict,
    tmp_path,
    monkeypatch,
):
    import pretty_midi

    monkeypatch.setenv("TRANSCRIPTION_USE_CLEANER", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_NORMALIZER", "1")
    monkeypatch.setenv("TRANSCRIPTION_USE_BEAT_TRACKER", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_PIANO_ANALYZER", "1")

    midi = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    for start, pitch in [(0.0, 60), (0.5, 64), (1.0, 67)]:
        inst.notes.append(
            pretty_midi.Note(velocity=64, pitch=pitch, start=start, end=start + 0.4)
        )
    mock_predict.return_value = (None, midi, None)

    mock_classify.return_value = InstrumentPrediction(
        instrument=InstrumentKind.PIANO,
        confidence=0.9,
    )
    refined = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.4, velocity=95, confidence=1.0),
        NoteEvent(pitch=64, start_time=0.5, end_time=0.9, velocity=80, confidence=1.0),
        NoteEvent(pitch=67, start_time=1.0, end_time=1.4, velocity=70, confidence=1.0),
    ]
    mock_piano_analyze.return_value = MagicMock(notes=refined)

    audio = tmp_path / "piano.wav"
    sr = 22050
    t = np.linspace(0, 2, sr * 2)
    sf.write(str(audio), 0.3 * np.sin(2 * np.pi * 440 * t), sr)

    xml = BasicPitchEngine().transcribe(audio, "enhanced-test")
    assert "score-partwise" in xml.lower() or "<?xml" in xml
    mock_piano_analyze.assert_called_once()


@patch("adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes")
def test_enhanced_legacy_writes_normalized_wav(mock_transcribe, tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_USE_CLEANER", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_NORMALIZER", "1")
    monkeypatch.setenv("TRANSCRIPTION_USE_BEAT_TRACKER", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_PIANO_ANALYZER", "0")

    mock_transcribe.return_value = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=80, confidence=1.0),
        NoteEvent(pitch=64, start_time=0.5, end_time=1.0, velocity=80, confidence=1.0),
        NoteEvent(pitch=67, start_time=1.0, end_time=1.5, velocity=80, confidence=1.0),
    ]

    audio = tmp_path / "in.wav"
    sr = 22050
    t = np.linspace(0, 2, sr * 2)
    sf.write(str(audio), 0.1 * np.sin(2 * np.pi * 440 * t), sr)

    BasicPitchEngine().transcribe(audio, "norm-test")
    norm_path = tmp_path / "bp_norm-test" / "norm-test_norm.wav"
    assert norm_path.exists()
    assert mock_transcribe.call_args[0][0] == norm_path
