"""Integration tests for Phase 3 understanding pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from mir.pipeline import UnderstandingPipeline
from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent
from transcription import FallbackEngine, BasicPitchEngine, get_engine


def test_get_engine_default_is_understanding(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_PIPELINE", raising=False)
    engine = get_engine()
    assert isinstance(engine, FallbackEngine)


def test_get_engine_explicit_legacy(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PIPELINE", "legacy")
    engine = get_engine()
    assert isinstance(engine, BasicPitchEngine)


@patch("adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes")
def test_understanding_pipeline_produces_musicxml(mock_transcribe, tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_USE_MIR_LAYERS", "1")

    mock_transcribe.return_value = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=80, confidence=1.0),
        NoteEvent(pitch=64, start_time=0.5, end_time=1.0, velocity=80, confidence=1.0),
        NoteEvent(pitch=48, start_time=0.0, end_time=1.0, velocity=70, confidence=1.0),
    ]

    audio = tmp_path / "test.wav"
    sr = 22050
    t = np.linspace(0, 2, sr * 2)
    sf.write(str(audio), 0.2 * np.sin(2 * np.pi * 440 * t), sr)

    xml = UnderstandingPipeline().transcribe(audio, "understanding-test")
    lower = xml.lower()
    assert "score-partwise" in lower or "<?xml" in xml
    assert "<rest" in lower
    assert "<staves>2</staves>" in lower
    raw_midi = tmp_path / "bp_understanding-test" / "understanding-test.raw.mid"
    score_midi = tmp_path / "bp_understanding-test" / "understanding-test.score.mid"
    assert raw_midi.exists()
    assert score_midi.exists()


@patch("adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes")
def test_fallback_engine_uses_legacy_on_failure(mock_transcribe, tmp_path, monkeypatch):
    mock_transcribe.return_value = []

    audio = tmp_path / "fail.wav"
    sr = 22050
    t = np.linspace(0, 1, sr)
    sf.write(str(audio), 0.1 * np.sin(2 * np.pi * 440 * t), sr)

    primary = UnderstandingPipeline()
    fallback = BasicPitchEngine()
    engine = FallbackEngine(primary, fallback)

    with patch.object(
        fallback,
        "transcribe",
        return_value='<?xml version="1.0"?><score-partwise></score-partwise>',
    ) as mock_legacy:
        xml = engine.transcribe(audio, "fallback-test")
        mock_legacy.assert_called_once()
        assert "score-partwise" in xml.lower()


@patch("adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes")
@patch("audio_engine.instrument_classifier.InstrumentClassifier.classify")
def test_understanding_respects_mir_layers_flag(
    mock_classify, mock_transcribe, tmp_path, monkeypatch
):
    monkeypatch.setenv("TRANSCRIPTION_USE_MIR_LAYERS", "0")

    mock_classify.return_value = InstrumentPrediction(
        instrument=InstrumentKind.PIANO,
        confidence=0.9,
    )
    mock_transcribe.return_value = [
        NoteEvent(pitch=72, start_time=0.0, end_time=0.5, velocity=80, confidence=1.0),
        NoteEvent(pitch=48, start_time=0.0, end_time=0.5, velocity=70, confidence=1.0),
    ]

    audio = tmp_path / "piano.wav"
    sr = 22050
    t = np.linspace(0, 2, sr * 2)
    sf.write(str(audio), 0.2 * np.sin(2 * np.pi * 440 * t), sr)

    pipeline = UnderstandingPipeline()
    assert pipeline.use_mir_layers is False
    xml = pipeline.transcribe(audio, "no-mir-test")
    assert "score-partwise" in xml.lower() or "<?xml" in xml


@patch("adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes")
def test_understanding_raw_midi_keeps_seconds_and_tempo_track(
    mock_transcribe, tmp_path, monkeypatch
):
    import pretty_midi

    from mir.types import TempoMap, TempoPoint

    monkeypatch.setenv("TRANSCRIPTION_USE_MIR_LAYERS", "1")
    mock_transcribe.return_value = [
        NoteEvent(pitch=60, start_time=0.20, end_time=0.50, velocity=80, confidence=1.0),
        NoteEvent(pitch=48, start_time=0.20, end_time=0.80, velocity=70, confidence=1.0),
        NoteEvent(pitch=64, start_time=1.80, end_time=2.20, velocity=80, confidence=1.0),
    ]

    audio = tmp_path / "tempo.wav"
    sr = 22050
    t = np.linspace(0, 3, sr * 3)
    sf.write(str(audio), 0.2 * np.sin(2 * np.pi * 440 * t), sr)

    pipeline = UnderstandingPipeline()
    pipeline.beat_tracker.track_stable = lambda audio: TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=100.0, confidence=0.9),
            TempoPoint(time_sec=1.5, beat=2.5, bpm=150.0, confidence=0.9),
        ]
    )
    pipeline.transcribe(audio, "tempo-map-test")
    midi = pretty_midi.PrettyMIDI(str(tmp_path / "bp_tempo-map-test" / "tempo-map-test.raw.mid"))
    starts = sorted(n.start for inst in midi.instruments for n in inst.notes)
    assert any(abs(s - 0.20) < 0.03 for s in starts)
    times, tempi = midi.get_tempo_changes()
    assert len(tempi) >= 2
    assert any(abs(float(t) - 150.0) < 3.0 for t in tempi)
