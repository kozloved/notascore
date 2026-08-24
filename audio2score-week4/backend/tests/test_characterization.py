"""Characterization tests for legacy Basic Pitch pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mir.types import NoteEvent
from transcription import BasicPitchEngine, get_engine, refine_tempo, snap_to_standard_tempo


def test_refine_tempo_grid():
    onsets = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
    bpm = refine_tempo(onsets, 120.0)
    assert 50 <= bpm <= 200


def test_snap_to_standard_tempo():
    assert snap_to_standard_tempo(118.5) == 120
    assert snap_to_standard_tempo(122.0) == 120


def test_get_engine_legacy_default(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PIPELINE", "legacy")
    engine = get_engine()
    assert isinstance(engine, BasicPitchEngine)


def test_get_engine_understanding(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PIPELINE", "understanding")
    monkeypatch.setenv("TRANSCRIPTION_PIPELINE_FALLBACK", "0")
    engine = get_engine()
    from mir.pipeline import UnderstandingPipeline

    assert isinstance(engine, UnderstandingPipeline)


@patch("adapters.basic_pitch_backend.predict")
def test_basic_pitch_engine_produces_musicxml(mock_predict, tmp_path, monkeypatch):
    import pretty_midi

    monkeypatch.delenv("TRANSCRIPTION_USE_CLEANER", raising=False)

    midi = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5))
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=64, start=0.5, end=1.0))
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=67, start=1.0, end=1.5))
    midi.instruments.append(inst)
    mock_predict.return_value = (None, midi, None)

    audio = tmp_path / "test.wav"
    import numpy as np
    import soundfile as sf

    sr = 22050
    t = np.linspace(0, 2, sr * 2)
    sf.write(str(audio), 0.3 * np.sin(2 * np.pi * 440 * t), sr)

    xml = BasicPitchEngine().transcribe(audio, "char-test")
    assert "<?xml" in xml or "<score-partwise" in xml.lower() or "score-partwise" in xml
