"""Original-upload source preview and job payload fields."""

from __future__ import annotations

import uuid
from pathlib import Path

import pretty_midi
import pytest
from fastapi.testclient import TestClient

import database as db
import main as app_main


def _write_midi(path: Path, pitch: int = 60) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=0.0, end=0.5))
    midi.instruments.append(inst)
    midi.write(str(path))


def _insert_job(tmp_path: Path, filename: str, payload: bytes, suffix: str) -> str:
    db.init_db()
    job_id = f"listen-{uuid.uuid4().hex}"
    source = tmp_path / f"{job_id}{suffix}"
    source.write_bytes(payload)
    result = tmp_path / f"{job_id}.musicxml"
    result.write_text("<score/>", encoding="utf-8")
    now = db.utcnow()
    db.create_job(
        {
            "id": job_id,
            "status": "completed",
            "filename": filename,
            "content_type": "audio/wav" if suffix == ".wav" else "audio/midi",
            "size_bytes": source.stat().st_size,
            "storage_key": str(source),
            "result_storage_key": str(result),
            "progress": 100,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "mode": "fast",
        }
    )
    return job_id


def test_job_source_streams_original_audio(tmp_path):
    pytest.importorskip("httpx")
    payload = b"RIFF-LISTEN-WAV"
    job_id = _insert_job(tmp_path, "clip.wav", payload, ".wav")

    with TestClient(app_main.app) as client:
        detail = client.get(f"/jobs/{job_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["source_kind"] == "audio"

        response = client.get(f"/jobs/{job_id}/source")
        assert response.status_code == 200
        assert response.content == payload
        assert "audio/wav" in response.headers["content-type"]
        disposition = response.headers.get("content-disposition", "").lower()
        assert "inline" in disposition


def test_midi_upload_source_kind(tmp_path):
    pytest.importorskip("httpx")
    midi_path = tmp_path / "seed.mid"
    _write_midi(midi_path)
    job_id = _insert_job(tmp_path, "tune.mid", midi_path.read_bytes(), ".mid")

    with TestClient(app_main.app) as client:
        body = client.get(f"/jobs/{job_id}").json()
        assert body["source_kind"] == "midi"
        response = client.get(f"/jobs/{job_id}/source")
        assert response.status_code == 200
        assert response.content[:4] == b"MThd"
        assert "midi" in response.headers["content-type"]


def test_job_source_404_when_missing():
    pytest.importorskip("httpx")
    with TestClient(app_main.app) as client:
        response = client.get("/jobs/does-not-exist/source")
        assert response.status_code == 404
