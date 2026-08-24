"""HTTP contract tests for the GPU MT3 worker (no CUDA required)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pretty_midi
import pytest

GPU_WORKER = Path(__file__).resolve().parents[2] / "gpu-worker"
sys.path.insert(0, str(GPU_WORKER))

import mt3_gpu_worker as worker  # noqa: E402


def _one_note_midi():
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=64, start=0.0, end=0.5))
    midi.instruments.append(inst)
    return midi


def test_midi_to_bytes_pretty_midi():
    data = worker.midi_to_bytes(_one_note_midi())
    assert data[:4] == b"MThd"


def test_health_does_not_load_model():
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    with TestClient(worker.app) as client:
        payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["model"] == "mr_mt3"
    assert payload["loaded"] is False


def test_transcribe_returns_midi(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    monkeypatch.setattr(worker, "API_KEY", "")

    def fake_transcribe(_path: str) -> bytes:
        return worker.midi_to_bytes(_one_note_midi())

    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    with patch.object(worker, "transcribe_audio_path", side_effect=fake_transcribe):
        with TestClient(worker.app) as client:
            response = client.post(
                "/transcribe",
                files={"file": ("clip.wav", wav.read_bytes(), "audio/wav")},
            )
    assert response.status_code == 200
    assert response.content[:4] == b"MThd"
    assert response.headers["content-type"].startswith("audio/midi")


def test_transcribe_rejects_bad_key(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    monkeypatch.setattr(worker, "API_KEY", "secret")
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    with TestClient(worker.app) as client:
        response = client.post(
            "/transcribe",
            files={"file": ("clip.wav", wav.read_bytes(), "audio/wav")},
            headers={"Authorization": "Bearer nope"},
        )
    assert response.status_code == 401


def test_transcribe_accepts_bearer(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    monkeypatch.setattr(worker, "API_KEY", "secret")

    def fake_transcribe(_path: str) -> bytes:
        return worker.midi_to_bytes(_one_note_midi())

    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF")
    with patch.object(worker, "transcribe_audio_path", side_effect=fake_transcribe):
        with TestClient(worker.app) as client:
            response = client.post(
                "/transcribe",
                files={"file": ("clip.wav", wav.read_bytes(), "audio/wav")},
                headers={"Authorization": "Bearer secret"},
            )
    assert response.status_code == 200
    assert response.content[:4] == b"MThd"
