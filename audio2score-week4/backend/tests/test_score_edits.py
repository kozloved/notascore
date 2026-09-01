"""Pass 5: score correction persistence, ownership, and export routing."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

import database as db
import main as app_main
from score_edits import (
    EditError,
    build_musicxml_and_midi,
    extract_from_musicxml,
    pitch_name,
    validate_notes,
)

SECRET = "pass5-test-jwt-secret-32chars-min"


def _token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "aud": "authenticated",
            "role": "authenticated",
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        SECRET,
        algorithm="HS256",
    )


def _auth(user_id: str) -> dict:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _write_fixture_xml(path: Path) -> str:
    from music21 import meter, note, stream, tempo

    part = stream.Part()
    part.insert(0, tempo.MetronomeMark(number=100))
    part.insert(0, meter.TimeSignature("4/4"))
    for pitch, start, dur in (
        ("C4", 0.0, 1.0),
        ("E4", 0.0, 1.0),
        ("G4", 0.0, 1.0),
        ("D4", 1.0, 0.5),
    ):
        event = note.Note(pitch)
        event.quarterLength = dur
        event.volume.velocity = 80
        part.insert(start, event)
    score = stream.Score()
    score.insert(0, part)
    score.write("musicxml", fp=str(path))
    return path.read_text(encoding="utf-8")


def _insert_job(**overrides) -> dict:
    db.init_db()
    job_id = overrides.get("id") or f"score-{uuid.uuid4().hex}"
    now = db.utcnow()
    job = {
        "id": job_id,
        "status": "completed",
        "filename": "my-piano-idea.wav",
        "content_type": "audio/wav",
        "size_bytes": 12,
        "storage_key": None,
        "result_storage_key": None,
        "progress": 100,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "mode": "solo",
        "user_id": None,
        "title": "My Piano Idea",
        "duration_seconds": 42,
        "claim_token_hash": None,
        "deleted_at": None,
    }
    job.update(overrides)
    db.create_job(job)
    return job


@pytest.fixture
def jwt_secret(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    return SECRET


def test_pitch_name_uses_musician_spelling():
    assert pitch_name(60) == "C4"
    assert pitch_name(61) == "C♯4"


def test_validate_notes_rejects_nan_and_overlap_corruption():
    with pytest.raises(EditError):
        validate_notes(
            [{"id": "n-1", "pitch": 60, "start": float("nan"), "duration": 1, "velocity": 64, "track": 0}]
        )
    with pytest.raises(EditError):
        validate_notes(
            [{"id": "n-1", "pitch": 60, "start": -1, "duration": 1, "velocity": 64, "track": 0}]
        )
    with pytest.raises(EditError):
        validate_notes(
            [
                {"id": "dup", "pitch": 60, "start": 0, "duration": 1, "velocity": 64, "track": 0},
                {"id": "dup", "pitch": 64, "start": 0, "duration": 1, "velocity": 64, "track": 0},
            ]
        )


def test_extract_keeps_chord_tones_independent(tmp_path):
    xml_path = tmp_path / "orig.musicxml"
    xml = _write_fixture_xml(xml_path)
    model = extract_from_musicxml(xml)
    assert model["tempo_bpm"] == 100
    assert model["time_signature"] == "4/4"
    pitches = sorted(note["pitch"] for note in model["notes"] if note["start"] == 0)
    assert pitches == [60, 64, 67]
    assert len({note["id"] for note in model["notes"]}) == len(model["notes"])


def test_rebuild_roundtrip_changes_pitch_not_chord_mates(tmp_path):
    xml = _write_fixture_xml(tmp_path / "orig.musicxml")
    model = extract_from_musicxml(xml)
    c4 = next(note for note in model["notes"] if note["pitch"] == 60)
    c4["pitch"] = 61
    xml_text, midi_bytes = build_musicxml_and_midi(model)
    rebuilt = extract_from_musicxml(xml_text)
    at_zero = sorted(note["pitch"] for note in rebuilt["notes"] if note["start"] == 0)
    assert 61 in at_zero
    assert 60 not in at_zero
    assert 64 in at_zero
    assert 67 in at_zero
    assert midi_bytes[:4] == b"MThd"


def test_get_edits_extracts_original(jwt_secret, tmp_path):
    pytest.importorskip("httpx")
    xml_path = tmp_path / "clip.musicxml"
    _write_fixture_xml(xml_path)
    job = _insert_job(user_id="user-a", result_storage_key=str(xml_path))
    with TestClient(app_main.app) as client:
        response = client.get(f"/scores/{job['id']}/edits", headers=_auth("user-a"))
        assert response.status_code == 200
        body = response.json()
        assert body["has_edits"] is False
        assert body["revision"] == 0
        assert len(body["notes"]) >= 4
        stranger = client.get(f"/scores/{job['id']}/edits", headers=_auth("user-b"))
        assert stranger.status_code == 404


def test_put_edits_persists_and_serves_edited_exports(jwt_secret, tmp_path):
    pytest.importorskip("httpx")
    xml_path = tmp_path / "clip.musicxml"
    original = _write_fixture_xml(xml_path)
    job = _insert_job(user_id="user-a", result_storage_key=str(xml_path))
    with TestClient(app_main.app) as client:
        loaded = client.get(f"/scores/{job['id']}/edits", headers=_auth("user-a")).json()
        notes = loaded["notes"]
        notes[0]["pitch"] = notes[0]["pitch"] + 1
        saved = client.put(
            f"/scores/{job['id']}/edits",
            json={
                "revision": 0,
                "notes": notes,
                "tempo_bpm": loaded["tempo_bpm"],
                "time_signature": loaded["time_signature"],
            },
            headers=_auth("user-a"),
        )
        assert saved.status_code == 200
        body = saved.json()
        assert body["has_edits"] is True
        assert body["revision"] == 1
        assert xml_path.read_text(encoding="utf-8") == original

        musicxml = client.get(
            f"/jobs/{job['id']}/result?format=musicxml",
            headers=_auth("user-a"),
        )
        assert musicxml.status_code == 200
        assert musicxml.text != original

        midi = client.get(
            f"/jobs/{job['id']}/result?format=midi_score",
            headers=_auth("user-a"),
        )
        assert midi.status_code == 200
        assert midi.content[:4] == b"MThd"

        conflict = client.put(
            f"/scores/{job['id']}/edits",
            json={
                "revision": 0,
                "notes": notes,
                "tempo_bpm": loaded["tempo_bpm"],
                "time_signature": loaded["time_signature"],
            },
            headers=_auth("user-a"),
        )
        assert conflict.status_code == 409

        stolen = client.put(
            f"/scores/{job['id']}/edits",
            json={
                "revision": 1,
                "notes": notes,
                "tempo_bpm": loaded["tempo_bpm"],
                "time_signature": loaded["time_signature"],
            },
            headers=_auth("user-b"),
        )
        assert stolen.status_code == 404


def test_reset_restores_original_files(jwt_secret, tmp_path):
    pytest.importorskip("httpx")
    xml_path = tmp_path / "clip.musicxml"
    original = _write_fixture_xml(xml_path)
    job = _insert_job(user_id="user-a", result_storage_key=str(xml_path))
    with TestClient(app_main.app) as client:
        loaded = client.get(f"/scores/{job['id']}/edits", headers=_auth("user-a")).json()
        notes = loaded["notes"]
        notes[0]["pitch"] = 72
        client.put(
            f"/scores/{job['id']}/edits",
            json={
                "revision": 0,
                "notes": notes,
                "tempo_bpm": loaded["tempo_bpm"],
                "time_signature": loaded["time_signature"],
            },
            headers=_auth("user-a"),
        )
        reset = client.post(
            f"/scores/{job['id']}/edits/reset",
            headers=_auth("user-a"),
        )
        assert reset.status_code == 200
        body = reset.json()
        assert body["has_edits"] is False
        assert body["revision"] == 2
        assert xml_path.read_text(encoding="utf-8") == original
        served = client.get(
            f"/jobs/{job['id']}/result?format=musicxml",
            headers=_auth("user-a"),
        )
        assert served.text == original


def test_unowned_score_can_be_edited_by_uuid(jwt_secret, tmp_path):
    pytest.importorskip("httpx")
    xml_path = tmp_path / "open.musicxml"
    _write_fixture_xml(xml_path)
    job = _insert_job(result_storage_key=str(xml_path))
    with TestClient(app_main.app) as client:
        loaded = client.get(f"/scores/{job['id']}/edits").json()
        notes = loaded["notes"]
        notes[0]["duration"] = 0.5
        saved = client.put(
            f"/scores/{job['id']}/edits",
            json={
                "revision": 0,
                "notes": notes,
                "tempo_bpm": loaded["tempo_bpm"],
                "time_signature": loaded["time_signature"],
            },
        )
        assert saved.status_code == 200
        assert saved.json()["has_edits"] is True
