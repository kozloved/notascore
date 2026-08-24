"""Quality / MT3 backend and Fast vs Quality routing."""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pretty_midi
import pytest
import soundfile as sf

from adapters.mt3_backend import MT3Backend, mt3_available, mt3_status
from mir.pipeline import UnderstandingPipeline
from mir.types import NoteEvent
from transcription import (
    FallbackEngine,
    TranscriptionError,
    get_engine,
    parse_transcription_mode,
    queue_timeout_for_mode,
)


def _one_note_midi_bytes(pitch: int = 60) -> bytes:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=0.0, end=0.5))
    midi.instruments.append(inst)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "n.mid"
        midi.write(str(path))
        return path.read_bytes()


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_parse_mode():
    assert parse_transcription_mode(None) == "fast"
    assert parse_transcription_mode("Quality") == "quality"
    with pytest.raises(ValueError, match="fast"):
        parse_transcription_mode("ultra")


def test_mt3_unconfigured_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MT3_ENDPOINT", "")
    monkeypatch.setenv("MT3_TRANSCRIBE_COMMAND", "")
    monkeypatch.setenv("MT3_API_KEY", "")
    assert mt3_available() is False
    assert mt3_status()["available"] is False
    with pytest.raises(TranscriptionError, match="not configured"):
        MT3Backend().transcribe_notes(tmp_path / "clip.wav")


def test_mt3_http_midi_bytes(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    midi_bytes = _one_note_midi_bytes(64)
    monkeypatch.setenv("MT3_ENDPOINT", "http://gpu.example/transcribe")
    monkeypatch.delenv("MT3_TRANSCRIBE_COMMAND", raising=False)

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        assert b"clip.wav" in request.data
        return _FakeResponse(midi_bytes, "audio/midi")

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    notes = MT3Backend().transcribe_notes(audio)
    assert captured["url"] == "http://gpu.example/transcribe"
    assert [n.pitch for n in notes] == [64]


def test_mt3_http_json_base64(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    midi_bytes = _one_note_midi_bytes(67)
    monkeypatch.setenv("MT3_ENDPOINT", "http://gpu.example/transcribe")
    monkeypatch.setenv("MT3_API_KEY", "secret-token")
    body = json.dumps({"midi_base64": base64.b64encode(midi_bytes).decode()}).encode()

    def fake_urlopen(request, timeout=None):
        assert request.get_header("Authorization") == "Bearer secret-token"
        return _FakeResponse(body, "application/json")

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    notes = MT3Backend().transcribe_notes(audio)
    assert notes[0].pitch == 67


def test_mt3_command_writes_midi(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    script = Path(__file__).resolve().parents[1] / "scripts" / "example_mt3.py"
    monkeypatch.delenv("MT3_ENDPOINT", raising=False)
    monkeypatch.setenv(
        "MT3_TRANSCRIBE_COMMAND",
        f"{sys.executable} {script} {{input}} {{output}}",
    )
    notes = MT3Backend().transcribe_notes(audio)
    assert notes[0].pitch == 60
    assert mt3_available() is True
    assert mt3_status()["command_configured"] is True


def test_get_engine_quality_no_fallback(monkeypatch):
    monkeypatch.setenv("MT3_ENDPOINT", "http://gpu.example/transcribe")
    monkeypatch.setenv("TRANSCRIPTION_PIPELINE_FALLBACK", "1")
    engine = get_engine(mode="quality")
    assert isinstance(engine, UnderstandingPipeline)
    assert not isinstance(engine, FallbackEngine)
    assert engine.backend_name == "mt3"


def test_get_engine_quality_unconfigured(monkeypatch):
    monkeypatch.setenv("MT3_ENDPOINT", "")
    monkeypatch.setenv("MT3_TRANSCRIBE_COMMAND", "")
    with pytest.raises(TranscriptionError, match="not configured"):
        get_engine(mode="quality")


def test_get_engine_fast_still_fallback(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_PIPELINE", raising=False)
    engine = get_engine(mode="fast")
    assert isinstance(engine, FallbackEngine)


def test_midi_ignores_quality_and_skips_mt3(tmp_path, monkeypatch):
    monkeypatch.setenv("MT3_ENDPOINT", "")
    monkeypatch.setenv("MT3_TRANSCRIBE_COMMAND", "")
    midi = pretty_midi.PrettyMIDI(initial_tempo=100)
    inst = pretty_midi.Instrument(program=0, name="RH")
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=72, start=0.0, end=0.5))
    midi.instruments.append(inst)
    path = tmp_path / "piano.mid"
    midi.write(str(path))

    engine = get_engine(mode="quality", filename=str(path))
    assert isinstance(engine, UnderstandingPipeline)
    assert engine.backend_name is None

    with patch.object(MT3Backend, "transcribe_notes") as mock_mt3:
        xml = engine.transcribe(path, "midi-quality")
        mock_mt3.assert_not_called()
    assert "score-partwise" in xml.lower()


@patch("adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes")
@patch("adapters.mt3_backend.MT3Backend.transcribe_notes")
def test_quality_pipeline_uses_mt3_not_basic_pitch(
    mock_mt3, mock_bp, tmp_path, monkeypatch
):
    monkeypatch.setenv("MT3_ENDPOINT", "http://gpu.example/transcribe")
    mock_mt3.return_value = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=80, confidence=1.0),
        NoteEvent(pitch=64, start_time=0.5, end_time=1.0, velocity=80, confidence=1.0),
        NoteEvent(pitch=48, start_time=0.0, end_time=1.0, velocity=70, confidence=1.0),
    ]
    audio = tmp_path / "q.wav"
    sr = 22050
    t = np.linspace(0, 1, sr, endpoint=False)
    sf.write(str(audio), 0.2 * np.sin(2 * np.pi * 440 * t), sr)

    xml = UnderstandingPipeline(backend_name="mt3").transcribe(audio, "quality-job")
    mock_mt3.assert_called_once()
    mock_bp.assert_not_called()
    assert "score-partwise" in xml.lower()
    assert "<staves>2</staves>" in xml.lower()


def test_queue_timeout_quality_uses_mt3_budget(monkeypatch):
    monkeypatch.setenv("MT3_TIMEOUT_SECONDS", "300")
    assert queue_timeout_for_mode("fast") == 600
    assert queue_timeout_for_mode("quality") == 900


def test_health_includes_quality(monkeypatch):
    from main import health

    monkeypatch.delenv("MT3_ENDPOINT", raising=False)
    monkeypatch.delenv("MT3_TRANSCRIBE_COMMAND", raising=False)
    monkeypatch.setenv("MT3_ENDPOINT", "")
    monkeypatch.setenv("MT3_TRANSCRIBE_COMMAND", "")
    monkeypatch.setenv("ENABLE_GEMINI_MUSIC_ANALYSIS", "0")
    monkeypatch.setenv("GEMINI_ENABLED", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.delenv("GEMINI_DEFAULT_MODEL", raising=False)

    payload = health()
    assert payload["quality"]["available"] is False
    assert payload["modes"]["fast"] is True
    assert payload["modes"]["quality"] is False
    assert payload["gemini"]["enabled"] is False
    from intelligence.config import DEFAULT_MODEL

    assert payload["gemini"]["default_model"] == DEFAULT_MODEL


def test_quality_upload_rejected_when_unconfigured(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import main as app_main

    monkeypatch.setenv("MT3_ENDPOINT", "")
    monkeypatch.setenv("MT3_TRANSCRIBE_COMMAND", "")
    monkeypatch.setattr(app_main.queue_service, "enqueue_job", lambda *a, **k: None)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    with TestClient(app_main.app) as client:
        response = client.post(
            "/upload",
            files={"file": ("a.wav", wav.read_bytes(), "audio/wav")},
            data={"mode": "quality"},
        )
    assert response.status_code == 503
    assert "Quality mode is not configured" in response.json()["detail"]


def test_invalid_mode_rejected(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    import main as app_main

    monkeypatch.setattr(app_main.queue_service, "enqueue_job", lambda *a, **k: None)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    with TestClient(app_main.app) as client:
        response = client.post(
            "/upload",
            files={"file": ("a.wav", wav.read_bytes(), "audio/wav")},
            data={"mode": "ultra"},
        )
    assert response.status_code == 400
