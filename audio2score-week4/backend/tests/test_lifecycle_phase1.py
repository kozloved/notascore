"""Phase 1: leases, publish manifests, delayed GC, and reset fencing."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

import database as db
import lifecycle
import main as app_main
import tasks
from engine.artifacts import ArtifactKind
from publishing import attempt_keys


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
        "mode": "solo",
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
    url = f"sqlite:///{tmp_path / 'lifecycle.db'}"
    previous_url = db.DATABASE_URL
    previous_engine = db.engine
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("JOB_LEASE_TTL_SECONDS", "120")
    monkeypatch.setenv("JOB_MAX_RETRIES", "2")
    monkeypatch.setenv("JOB_RETRY_BACKOFF_SECONDS", "1")
    monkeypatch.setenv("ARTIFACT_GC_GRACE_SECONDS", "0")
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


def test_heartbeat_keeps_live_worker_from_being_reclaimed(isolated_db):
    job_id = f"live-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id))
    assert db.claim_job_attempt(job_id, "live")
    past = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    session = db.SessionLocal()
    try:
        session.query(db.Job).filter(db.Job.id == job_id).update(
            {"updated_at": past}, synchronize_session=False
        )
        session.commit()
    finally:
        session.close()
    assert db.heartbeat_job_attempt(job_id, "live", progress=40)
    assert db.claim_job_attempt(job_id, "thief", stale_after_seconds=30) is False
    assert db.get_job(job_id)["processing_attempt"] == "live"


def test_expired_lease_recovery_requeues_with_backoff(isolated_db):
    job_id = f"recover-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id))
    assert db.claim_job_attempt(job_id, "dead")
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    session = db.SessionLocal()
    try:
        session.query(db.Job).filter(db.Job.id == job_id).update(
            {"lease_expires_at": past}, synchronize_session=False
        )
        session.commit()
    finally:
        session.close()
    enqueued = []

    def enqueue(job_id, delay_seconds=0):
        enqueued.append((job_id, delay_seconds))

    actions = db.recover_expired_leases(enqueue=enqueue)
    assert actions and actions[0]["action"] == "requeue"
    job = db.get_job(job_id)
    assert job["status"] == "queued"
    assert job["retry_count"] == 1
    assert job["processing_attempt"] is None
    assert enqueued == [(job_id, 1)]


def test_recovery_terminal_fails_after_retry_limit(isolated_db):
    job_id = f"term-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id, retry_count=2))
    assert db.claim_job_attempt(job_id, "dead")
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    session = db.SessionLocal()
    try:
        session.query(db.Job).filter(db.Job.id == job_id).update(
            {"lease_expires_at": past}, synchronize_session=False
        )
        session.commit()
    finally:
        session.close()
    actions = db.recover_expired_leases(enqueue=lambda *a, **k: None)
    assert actions[0]["action"] == "terminal_fail"
    job = db.get_job(job_id)
    assert job["status"] == "failed"
    assert "retry limit" in (job["error"] or "")


def test_publish_rejects_missing_required_artifacts(isolated_db, tmp_path):
    job_id = "pub-missing"
    attempt = "a1"
    musicxml = tmp_path / f"{job_id}.musicxml"
    musicxml.write_text("<score/>", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required"):
        lifecycle.build_publish_manifest(
            job_id,
            attempt,
            {"musicxml": musicxml},
        )


def test_publish_rejects_corrupt_uploaded_hash(isolated_db, tmp_path):
    job_id = "pub-corrupt"
    attempt = "a1"
    folder = tmp_path / "out"
    folder.mkdir()
    files = {}
    for name, kind_name in (
        (f"{job_id}.musicxml", "xml"),
        (f"{job_id}.validated.mid", "mid"),
        (f"{job_id}.score.mid", "mid"),
    ):
        path = folder / name
        if kind_name == "xml":
            path.write_text("<score/>", encoding="utf-8")
        else:
            path.write_bytes(b"MThd-good")
        files[name] = path
    manifest = lifecycle.build_publish_manifest(job_id, attempt, files)
    keys = attempt_keys(job_id, attempt)

    class FakeStorage:
        def __init__(self):
            self.blob = {}

        def read_result_bytes(self, key):
            return self.blob[key]

    storage = FakeStorage()
    for ref in manifest.artifacts:
        if ref.kind == ArtifactKind.MUSICXML:
            storage.blob[ref.storage_key] = b"<tampered/>"
        else:
            storage.blob[ref.storage_key] = path.read_bytes() if False else files[Path(ref.path).name].read_bytes()
    # Ensure validated/score present, musicxml corrupt.
    for ref in manifest.artifacts:
        if ref.kind != ArtifactKind.MUSICXML:
            storage.blob[ref.storage_key] = Path(ref.path).read_bytes()
    with pytest.raises(ValueError, match="corrupt published artifact"):
        lifecycle.verify_uploaded_hashes(storage, manifest)


def test_delayed_gc_waits_for_reader_hold(isolated_db, monkeypatch):
    import storage as storage_mod

    monkeypatch.setenv("RESULTS_DIR", str(isolated_db / "results"))
    storage_mod.LOCAL_RESULTS_DIR = isolated_db / "results"
    storage_mod.LOCAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    backend = storage_mod.LocalStorage()
    job_id = "gc-hold"
    keep = backend.save_text(f"{job_id}.attempts/keep/{job_id}.musicxml", "<keep/>")
    doomed = backend.save_text(f"{job_id}.attempts/old/{job_id}.musicxml", "<old/>")
    lifecycle.hold_job_artifacts(job_id, ttl_seconds=60)
    lifecycle.schedule_attempt_gc(job_id, ["old"], keep_attempt_ids={"keep"}, not_before=time.time() - 1)
    applied = lifecycle.sweep_artifact_gc(backend, now=time.time())
    assert applied == []
    assert Path(doomed).is_file()
    lifecycle.clear_tombstones_for_tests()
    lifecycle.schedule_attempt_gc(job_id, ["old"], keep_attempt_ids={"keep"}, not_before=time.time() - 1)
    applied = lifecycle.sweep_artifact_gc(backend, now=time.time() + 120)
    assert applied
    assert Path(keep).is_file()
    assert not Path(doomed).exists()


def test_paginated_remote_listing_removes_all_eligible_objects(isolated_db):
    class PageBucket:
        def __init__(self, names):
            self.names = list(names)
            self.calls = []

        def list(self, path, options=None):
            options = options or {}
            limit = int(options.get("limit", 100))
            offset = int(options.get("offset", 0))
            self.calls.append((path, limit, offset))
            page = self.names[offset : offset + limit]
            return [{"name": name, "id": name, "metadata": {"size": 1}} for name in page]

        def remove(self, keys):
            self.removed = list(keys)

    import storage as storage_mod

    backend = storage_mod.SupabaseStorage.__new__(storage_mod.SupabaseStorage)
    backend.results_bucket = "results"
    names = [f"f{i}.mid" for i in range(5)]
    bucket = PageBucket(names)
    backend._bucket = lambda name: bucket
    keys = backend._list_keys("results", "job.attempts/old", page_size=2)
    assert keys == [f"job.attempts/old/{name}" for name in names]
    assert len(bucket.calls) >= 3
    backend.gc_unreachable_attempts = storage_mod.SupabaseStorage.gc_unreachable_attempts.__get__(
        backend, storage_mod.SupabaseStorage
    )
    # Direct prefix GC via list+remove
    backend.gc_prefix("job.attempts/old")
    assert set(bucket.removed) == set(keys)


def test_stale_reset_with_expected_revision_is_rejected(isolated_db, monkeypatch):
    job_id = "reset-stale"
    db.create_job(
        _job_row(
            job_id,
            status="completed",
            result_storage_key="orig.xml",
            edited_result_storage_key="edit.xml",
            edit_revision=4,
        )
    )
    monkeypatch.setattr(app_main, "_load_edit_model", lambda job: {"notes": [], "tempo_bpm": 120, "time_signature": "4/4", "tempo_curve": [], "printed_tempo_marks": [], "provenance": "performance"})
    with pytest.raises(HTTPException) as error:
        app_main.score_edits_reset(
            job_id,
            body=app_main.ScoreResetIn(revision=2),
            authorization=None,
        )
    assert error.value.status_code == 409
    assert db.get_job(job_id)["edit_revision"] == 4
    assert db.get_job(job_id)["edited_result_storage_key"] == "edit.xml"


def test_heartbeat_thread_stops_when_fenced_out(isolated_db):
    job_id = f"hb-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id))
    assert db.claim_job_attempt(job_id, "old")
    renewals = []

    def renew(jid, aid):
        ok = db.heartbeat_job_attempt(jid, aid)
        renewals.append(ok)
        return ok

    with lifecycle.AttemptHeartbeat(job_id, "old", renew, interval_seconds=0.05) as hb:
        time.sleep(0.12)
        db.claim_job_attempt(job_id, "new", stale_after_seconds=0)
        # Force lease expiry so reclaim can steal.
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        session = db.SessionLocal()
        try:
            session.query(db.Job).filter(db.Job.id == job_id).update(
                {"lease_expires_at": past, "status": "processing", "processing_attempt": "old"},
                synchronize_session=False,
            )
            session.commit()
        finally:
            session.close()
        assert db.reclaim_stale_job_attempt(job_id, "new")
        time.sleep(0.15)
    assert False in renewals
    assert hb.alive is False


def test_process_job_fails_closed_on_partial_upload(isolated_db, monkeypatch):
    job_id = f"partial-{uuid.uuid4().hex}"
    audio = isolated_db / "clip.wav"
    audio.write_bytes(b"RIFF")
    db.create_job(_job_row(job_id, storage_key=str(audio)))

    class FakeStorage:
        backend = "local"

        def get_local_audio_path(self, storage_key):
            return Path(storage_key)

        def save_text(self, key, text, content_type=None):
            path = isolated_db / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return str(path)

        def save_local_file(self, local_file_path, key, content_type=None):
            return str(isolated_db / key)

        def read_result_bytes(self, key):
            raise FileNotFoundError(key)

        def list_result_keys(self, prefix):
            return []

        def gc_unreachable_attempts(self, *args, **kwargs):
            return

    def runner(source, job_id, **kwargs):
        folder = Path(source).parent / f"bp_{job_id}"
        folder.mkdir(exist_ok=True)
        (folder / f"{job_id}.validated.mid").write_bytes(b"MThd")
        (folder / f"{job_id}.score.mid").write_bytes(b"MThd")
        return "<score/>"

    monkeypatch.setattr(tasks.storage_service, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr("engine.job_runner.run_job", runner)
    monkeypatch.setattr(
        "mir.raw_midi.job_raw_midi_path",
        lambda source, job_id: Path(source).parent / f"bp_{job_id}" / f"{job_id}.raw.mid",
    )
    monkeypatch.setattr(
        "mir.raw_midi.job_validated_midi_path",
        lambda source, job_id: Path(source).parent / f"bp_{job_id}" / f"{job_id}.validated.mid",
    )
    monkeypatch.setattr(
        "mir.raw_midi.job_score_midi_path",
        lambda source, job_id: Path(source).parent / f"bp_{job_id}" / f"{job_id}.score.mid",
    )
    monkeypatch.setattr("engine.sidecars.extra_result_files", lambda *_: [])
    tasks.process_job(job_id)
    job = db.get_job(job_id)
    assert job["status"] == "failed"
    assert job["result_storage_key"] is None
