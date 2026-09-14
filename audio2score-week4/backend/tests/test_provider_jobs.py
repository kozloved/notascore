"""Persist provider job IDs with attempt fencing."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

import database as db
import lifecycle
from adapters.provider_jobs import (
    bind_app_job,
    config_fingerprint,
    persist_provider_job,
)


def _job_row(job_id: str, **overrides) -> dict:
    now = db.utcnow()
    row = {
        "id": job_id,
        "status": "queued",
        "filename": "clip.wav",
        "content_type": "audio/wav",
        "size_bytes": 8,
        "storage_key": None,
        "result_storage_key": None,
        "progress": 0,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "mode": "polyphonic",
        "user_id": None,
        "title": "Clip",
        "duration_seconds": 1,
        "claim_token_hash": None,
        "deleted_at": None,
        "retry_count": 0,
    }
    row.update(overrides)
    return row


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'provider.db'}"
    previous_url = db.DATABASE_URL
    previous_engine = db.engine
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("JOB_LEASE_TTL_SECONDS", "120")
    db.DATABASE_URL = url
    db.engine = db.create_engine(
        url, connect_args={"check_same_thread": False, "timeout": 30}
    )
    db.SessionLocal.configure(bind=db.engine)
    db.init_db()
    lifecycle.clear_tombstones_for_tests()
    yield tmp_path
    lifecycle.clear_tombstones_for_tests()
    db.engine.dispose()
    db.engine = previous_engine
    db.DATABASE_URL = previous_url
    db.SessionLocal.configure(bind=previous_engine)


def test_provider_job_persists_under_live_attempt(isolated_db):
    job_id = f"prov-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id))
    assert db.claim_job_attempt(job_id, "live")
    fingerprint = config_fingerprint(
        {
            "model": "yourmt3",
            "provider": "runpod",
            "toolkit": "mt3-infer",
            "toolkit_version": "0.2.0",
            "endpoint_root": "https://api.runpod.ai/v2/abc",
        }
    )
    with bind_app_job(job_id, "live"):
        assert persist_provider_job(
            provider_job_id="rp-1",
            input_sha256="abc",
            config_sha256=fingerprint,
        )
    row = db.get_job(job_id)
    assert row["provider_job_id"] == "rp-1"
    assert row["provider_input_sha256"] == "abc"
    assert row["provider_config_sha256"] == fingerprint


def test_stale_attempt_cannot_persist_provider_job(isolated_db):
    job_id = f"prov-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id))
    assert db.claim_job_attempt(job_id, "old")
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    session = db.SessionLocal()
    try:
        session.query(db.Job).filter(db.Job.id == job_id).update(
            {"lease_expires_at": past},
            synchronize_session=False,
        )
        session.commit()
    finally:
        session.close()
    assert db.claim_job_attempt(job_id, "new")
    with bind_app_job(job_id, "old"):
        assert (
            persist_provider_job(
                provider_job_id="stale-rp",
                input_sha256="abc",
                config_sha256="cfg",
            )
            is False
        )
    with bind_app_job(job_id, "new"):
        assert persist_provider_job(
            provider_job_id="fresh-rp",
            input_sha256="abc",
            config_sha256="cfg",
        )
    row = db.get_job(job_id)
    assert row["provider_job_id"] == "fresh-rp"
    assert db.complete_job_attempt(job_id, "old", result_storage_key="stale.xml") is False
    assert db.complete_job_attempt(job_id, "new", result_storage_key="fresh.xml") is True
