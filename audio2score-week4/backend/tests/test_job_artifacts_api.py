"""Artifact listing and download without breaking existing result routes."""

from __future__ import annotations

import uuid
from pathlib import Path

import pretty_midi
import pytest

import database as db
import main as app_main


def _write_midi(path: Path) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5))
    midi.instruments.append(inst)
    midi.write(str(path))


def test_job_artifacts_list_and_download(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    db.init_db()
    job_id = f"arts-{uuid.uuid4().hex}"
    source = tmp_path / f"{job_id}.wav"
    source.write_bytes(b"RIFF-ART")
    result = tmp_path / f"{job_id}.musicxml"
    result.write_text("<score-partwise/>", encoding="utf-8")
    raw = tmp_path / f"{job_id}.raw.mid"
    _write_midi(raw)
    fused = tmp_path / f"{job_id}.fused.mid"
    _write_midi(fused)
    stem = tmp_path / f"{job_id}.stem.piano.wav"
    stem.write_bytes(b"PIANO")
    (tmp_path / f"{job_id}.manifest.json").write_text("{\"job_id\": \"%s\"}\n" % job_id)
    now = db.utcnow()
    db.create_job(
        {
            "id": job_id,
            "status": "completed",
            "filename": "clip.wav",
            "content_type": "audio/wav",
            "size_bytes": source.stat().st_size,
            "storage_key": str(source),
            "result_storage_key": str(result),
            "progress": 100,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "mode": "polyphonic",
        }
    )
    with TestClient(app_main.app) as client:
        listed = client.get(f"/jobs/{job_id}/artifacts")
        assert listed.status_code == 200
        names = {row["name"] for row in listed.json()["artifacts"]}
        assert f"{job_id}.raw.mid" in names
        assert f"{job_id}.fused.mid" in names
        assert f"{job_id}.stem.piano.wav" in names
        midi = client.get(f"/jobs/{job_id}/result?format=midi")
        assert midi.status_code == 200
        fused_dl = client.get(f"/jobs/{job_id}/result?format=fused_midi")
        assert fused_dl.status_code == 200
        assert fused_dl.content == fused.read_bytes()
        file_dl = client.get(f"/jobs/{job_id}/artifacts/{job_id}.stem.piano.wav")
        assert file_dl.status_code == 200
        assert file_dl.content == b"PIANO"
        # Old routes still work.
        xml = client.get(f"/jobs/{job_id}/result?format=musicxml")
        assert xml.status_code == 200
        assert b"score-partwise" in xml.content
