"""RunPod Serverless client for the existing MT3 adapter (mocked HTTP)."""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pretty_midi
import pytest

from adapters.mt3_backend import (
    MT3Backend,
    is_runpod_endpoint,
    mt3_status,
    normalize_mt3_endpoint,
)
from transcription import TranscriptionError


def _one_note_midi_bytes(pitch: int = 60) -> bytes:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=0.0, end=0.5))
    midi.instruments.append(inst)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "n.mid"
        midi.write(str(path))
        return path.read_bytes()


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json"):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(url: str, code: int, body: bytes = b"") -> HTTPError:
    return HTTPError(url, code, "error", hdrs={}, fp=io.BytesIO(body))


def test_normalize_runpod_endpoint():
    base = "https://api.runpod.ai/v2/g40wir5ey71e3"
    assert normalize_mt3_endpoint(base) == f"{base}/runsync"
    assert normalize_mt3_endpoint(f"{base}/") == f"{base}/runsync"
    assert normalize_mt3_endpoint(f"{base}/runsync") == f"{base}/runsync"
    assert normalize_mt3_endpoint(f"{base}/runsync/") == f"{base}/runsync"
    assert normalize_mt3_endpoint(f"{base}/run") == f"{base}/runsync"
    assert normalize_mt3_endpoint("http://gpu.example/transcribe") == (
        "http://gpu.example/transcribe"
    )
    assert is_runpod_endpoint(base) is True
    assert is_runpod_endpoint("https://abc-8090.proxy.runpod.net/transcribe") is False


def test_runpod_json_request_and_midi(tmp_path, monkeypatch):
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"RIFF-AUDIO")
    midi_bytes = _one_note_midi_bytes(64)
    monkeypatch.setenv("MT3_ENDPOINT", "https://api.runpod.ai/v2/g40wir5ey71e3")
    monkeypatch.setenv("MT3_API_KEY", "rp-secret")
    monkeypatch.delenv("MT3_TRANSCRIBE_COMMAND", raising=False)

    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["authorization"] = request.get_header("Authorization")
        captured["content_type"] = request.get_header("Content-type")
        captured["accept"] = request.get_header("Accept")
        captured["body"] = json.loads(request.data)
        payload = {
            "status": "COMPLETED",
            "output": {
                "midi_base64": base64.b64encode(midi_bytes).decode(),
                "model": "yourmt3",
                "timing": {"inference_seconds": 1.2, "total_seconds": 2.4},
            },
        }
        return _FakeResponse(json.dumps(payload).encode())

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    notes = MT3Backend().transcribe_notes(audio)

    assert captured["url"] == "https://api.runpod.ai/v2/g40wir5ey71e3/runsync"
    assert captured["url"].count("runsync") == 1
    assert captured["authorization"] == "Bearer rp-secret"
    assert captured["content_type"] == "application/json"
    assert captured["accept"] == "application/json"
    assert captured["timeout"] == 300
    assert captured["body"]["input"]["filename"] == "recording.wav"
    assert base64.b64decode(captured["body"]["input"]["audio_base64"]) == b"RIFF-AUDIO"
    assert "rp-secret" not in json.dumps(captured["body"])
    assert [n.pitch for n in notes] == [64]


def test_runpod_top_level_midi_base64(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    midi_bytes = _one_note_midi_bytes(67)
    monkeypatch.setenv(
        "MT3_ENDPOINT", "https://api.runpod.ai/v2/g40wir5ey71e3/runsync"
    )
    monkeypatch.setenv("MT3_API_KEY", "rp-secret")

    def fake_urlopen(request, timeout=None):
        assert request.full_url.endswith("/runsync")
        assert request.full_url.count("runsync") == 1
        body = {
            "midi_base64": base64.b64encode(midi_bytes).decode(),
            "model": "yourmt3",
        }
        return _FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    notes = MT3Backend().transcribe_notes(audio)
    assert notes[0].pitch == 67


def test_runpod_invalid_json(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setenv("MT3_ENDPOINT", "https://api.runpod.ai/v2/g40wir5ey71e3/runsync")
    monkeypatch.setenv("MT3_API_KEY", "rp-secret")

    def fake_urlopen(request, timeout=None):
        return _FakeResponse(b"not-json")

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(TranscriptionError, match="invalid JSON"):
        MT3Backend().transcribe_notes(audio)


def test_runpod_missing_midi_base64(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setenv("MT3_ENDPOINT", "https://api.runpod.ai/v2/g40wir5ey71e3/runsync")
    monkeypatch.setenv("MT3_API_KEY", "rp-secret")

    def fake_urlopen(request, timeout=None):
        return _FakeResponse(json.dumps({"status": "COMPLETED", "output": {}}).encode())

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(TranscriptionError, match="did not contain midi_base64"):
        MT3Backend().transcribe_notes(audio)


def test_runpod_invalid_midi(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setenv("MT3_ENDPOINT", "https://api.runpod.ai/v2/g40wir5ey71e3/runsync")
    monkeypatch.setenv("MT3_API_KEY", "rp-secret")

    def fake_urlopen(request, timeout=None):
        return _FakeResponse(
            json.dumps({"midi_base64": base64.b64encode(b"not-midi").decode()}).encode()
        )

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(TranscriptionError, match="invalid MIDI"):
        MT3Backend().transcribe_notes(audio)


@pytest.mark.parametrize(
    ("code", "match"),
    [
        (401, "authentication failed"),
        (403, "authentication failed"),
        (404, "endpoint not found"),
        (429, "rate limit"),
        (500, "transcription service failed"),
    ],
)
def test_runpod_http_errors(tmp_path, monkeypatch, code, match):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    url = "https://api.runpod.ai/v2/g40wir5ey71e3/runsync"
    monkeypatch.setenv("MT3_ENDPOINT", url)
    monkeypatch.setenv("MT3_API_KEY", "rp-secret")

    def fake_urlopen(request, timeout=None):
        raise _http_error(url, code, b'{"error":"upstream"}')

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(TranscriptionError, match=match):
        MT3Backend().transcribe_notes(audio)


def test_runpod_timeout(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setenv("MT3_ENDPOINT", "https://api.runpod.ai/v2/g40wir5ey71e3/runsync")
    monkeypatch.setenv("MT3_API_KEY", "rp-secret")
    monkeypatch.setenv("MT3_TIMEOUT_SECONDS", "12")

    def fake_urlopen(request, timeout=None):
        assert timeout == 12
        raise URLError(TimeoutError("timed out"))

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(TranscriptionError, match="timed out after 12 seconds"):
        MT3Backend().transcribe_notes(audio)


def test_runpod_missing_api_key(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    monkeypatch.setenv("MT3_ENDPOINT", "https://api.runpod.ai/v2/g40wir5ey71e3/runsync")
    monkeypatch.setenv("MT3_API_KEY", "")

    with patch("adapters.mt3_backend.urllib.request.urlopen") as mock_open:
        with pytest.raises(TranscriptionError, match="authentication failed"):
            MT3Backend().transcribe_notes(audio)
        mock_open.assert_not_called()


def test_runpod_status_does_not_expose_key(monkeypatch):
    monkeypatch.setenv("MT3_ENDPOINT", "https://api.runpod.ai/v2/g40wir5ey71e3/runsync")
    monkeypatch.setenv("MT3_API_KEY", "rp-secret-must-not-leak")
    status = mt3_status()
    assert status["provider"] == "runpod"
    assert status["endpoint_configured"] is True
    assert status["available"] is True
    assert "api_key" not in status
    assert "rp-secret" not in json.dumps(status)


def test_health_runpod_provider(monkeypatch):
    from main import health

    monkeypatch.setenv("MT3_ENDPOINT", "https://api.runpod.ai/v2/g40wir5ey71e3/runsync")
    monkeypatch.setenv("MT3_API_KEY", "rp-secret-must-not-leak")
    monkeypatch.setenv("ENABLE_GEMINI_MUSIC_ANALYSIS", "0")
    monkeypatch.setenv("GEMINI_ENABLED", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    payload = health()
    dumped = json.dumps(payload)
    assert payload["polyphonic"]["provider"] == "runpod"
    assert payload["polyphonic"]["endpoint_configured"] is True
    assert payload["modes"]["polyphonic"] is True
    assert "api_key" not in payload["polyphonic"]
    assert "rp-secret" not in dumped


def test_command_path_still_works(tmp_path, monkeypatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    script = Path(__file__).resolve().parents[1] / "scripts" / "example_mt3.py"
    monkeypatch.delenv("MT3_ENDPOINT", raising=False)
    monkeypatch.setenv("MT3_ENDPOINT", "")
    monkeypatch.setenv(
        "MT3_TRANSCRIBE_COMMAND",
        f"{sys.executable} {script} {{input}} {{output}}",
    )
    notes = MT3Backend().transcribe_notes(audio)
    assert notes[0].pitch == 60
    assert mt3_status()["provider"] == "command"


@pytest.mark.integration
def test_runpod_live_adapter_if_configured(tmp_path):
    """Skipped unless MT3_ENDPOINT + MT3_API_KEY are set for a real worker."""
    import os

    import numpy as np
    import soundfile as sf

    endpoint = (os.getenv("MT3_ENDPOINT") or "").strip()
    api_key = (os.getenv("MT3_API_KEY") or "").strip()
    if not endpoint or not api_key:
        pytest.skip("Set MT3_ENDPOINT and MT3_API_KEY for a live RunPod test")

    sr = 22050
    t = np.linspace(0, 1.5, int(sr * 1.5), endpoint=False)
    audio = tmp_path / "live.wav"
    sf.write(str(audio), 0.2 * np.sin(2 * np.pi * 440 * t), sr)
    notes = MT3Backend().transcribe_notes(audio)
    assert notes, "live RunPod transcription returned no notes"
