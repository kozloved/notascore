"""Account-owned scores: authorization, claim, rename, delete, retry."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

import database as db
import main as app_main
from ownership import hash_claim_token, new_claim_token, title_from_filename

SECRET = "pass4-test-jwt-secret-32chars-min"


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
        "title": title_from_filename("my-piano-idea.wav"),
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


def test_title_from_filename_strips_extension_and_separators():
    assert title_from_filename("my-piano-idea.wav") == "My Piano Idea"
    assert title_from_filename("sketch_01.mp3") == "Sketch 01"
    assert title_from_filename("") == "Untitled score"


def test_unowned_job_is_readable_without_auth(jwt_secret):
    pytest.importorskip("httpx")
    job = _insert_job(status="queued", progress=0)
    with TestClient(app_main.app) as client:
        response = client.get(f"/jobs/{job['id']}")
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "My Piano Idea"
        assert body["owned"] is False
        assert "claim_token" not in body
        assert "user_id" not in body


def test_owner_can_read_and_stranger_cannot(jwt_secret):
    pytest.importorskip("httpx")
    job = _insert_job(user_id="user-a")
    with TestClient(app_main.app) as client:
        mine = client.get(f"/jobs/{job['id']}", headers=_auth("user-a"))
        assert mine.status_code == 200
        assert mine.json()["owned"] is True

        other = client.get(f"/jobs/{job['id']}", headers=_auth("user-b"))
        assert other.status_code == 404
        assert other.json()["detail"] == "Score not found"

        anon = client.get(f"/jobs/{job['id']}")
        assert anon.status_code == 404
        assert anon.json()["detail"] == "Score not found"


def test_list_scores_is_scoped_to_user(jwt_secret):
    pytest.importorskip("httpx")
    _insert_job(user_id="user-a", filename="alpha.wav", title="Alpha")
    _insert_job(user_id="user-b", filename="beta.wav", title="Beta")
    with TestClient(app_main.app) as client:
        listed = client.get("/scores", headers=_auth("user-a"))
        assert listed.status_code == 200
        titles = {row["title"] for row in listed.json()}
        assert "Alpha" in titles
        assert "Beta" not in titles

        denied = client.get("/scores")
        assert denied.status_code == 401


def test_rename_and_delete_require_owner(jwt_secret, tmp_path):
    pytest.importorskip("httpx")
    source = tmp_path / "clip.wav"
    source.write_bytes(b"RIFF-TEST")
    result = tmp_path / "clip.musicxml"
    result.write_text("<score/>", encoding="utf-8")
    job = _insert_job(
        user_id="user-a",
        storage_key=str(source),
        result_storage_key=str(result),
    )
    with TestClient(app_main.app) as client:
        stranger = client.patch(
            f"/scores/{job['id']}",
            json={"title": "Stolen"},
            headers=_auth("user-b"),
        )
        assert stranger.status_code == 404

        renamed = client.patch(
            f"/scores/{job['id']}",
            json={"title": "Evening Study"},
            headers=_auth("user-a"),
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "Evening Study"

        deleted = client.delete(f"/scores/{job['id']}", headers=_auth("user-a"))
        assert deleted.status_code == 200
        assert not source.exists()
        missing = client.get(f"/scores/{job['id']}", headers=_auth("user-a"))
        assert missing.status_code == 404


def test_claim_token_attaches_unowned_job(jwt_secret):
    pytest.importorskip("httpx")
    token = new_claim_token()
    job = _insert_job(
        status="processing",
        progress=20,
        claim_token_hash=hash_claim_token(token),
    )
    with TestClient(app_main.app) as client:
        claimed = client.post(
            "/scores/claim",
            json={"token": token},
            headers=_auth("user-a"),
        )
        assert claimed.status_code == 200
        assert claimed.json()["owned"] is True
        listed = client.get("/scores", headers=_auth("user-a"))
        ids = {row["job_id"] for row in listed.json()}
        assert job["id"] in ids


def test_source_and_result_are_hidden_from_other_users(jwt_secret, tmp_path):
    pytest.importorskip("httpx")
    source = tmp_path / "secret.wav"
    source.write_bytes(b"RIFF-SECRET")
    result = tmp_path / "secret.musicxml"
    result.write_text("<score/>", encoding="utf-8")
    job = _insert_job(
        user_id="user-a",
        storage_key=str(source),
        result_storage_key=str(result),
    )
    with TestClient(app_main.app) as client:
        ok = client.get(f"/jobs/{job['id']}/source", headers=_auth("user-a"))
        assert ok.status_code == 200
        denied = client.get(f"/jobs/{job['id']}/source", headers=_auth("user-b"))
        assert denied.status_code == 404
        denied_xml = client.get(
            f"/jobs/{job['id']}/result?format=musicxml",
            headers=_auth("user-b"),
        )
        assert denied_xml.status_code == 404


def test_retry_requeues_failed_owned_job(jwt_secret, tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    source = tmp_path / "retry.wav"
    source.write_bytes(b"RIFF-RETRY")
    job = _insert_job(
        user_id="user-a",
        status="failed",
        progress=40,
        error="worker died",
        storage_key=str(source),
        result_storage_key=None,
    )
    enqueued = []

    def fake_enqueue(job_id, job_timeout=None):
        enqueued.append((job_id, job_timeout))
        return True

    monkeypatch.setattr(app_main.queue_service, "enqueue_job", fake_enqueue)
    with TestClient(app_main.app) as client:
        response = client.post(
            f"/jobs/{job['id']}/retry",
            headers=_auth("user-a"),
        )
        assert response.status_code == 200
        assert response.json()["status"] == "queued"
        assert enqueued and enqueued[0][0] == job["id"]
