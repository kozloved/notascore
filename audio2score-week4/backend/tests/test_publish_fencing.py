"""Phase 1: concurrent publish must be fenced by DB CAS, not process locks."""

from __future__ import annotations

import threading
import uuid
from io import BytesIO
from pathlib import Path

import mido
import pytest
from fastapi import HTTPException

import database as db
import main as app_main
import tasks
from publishing import attempt_keys, sibling_key
from score_edits import extract_from_musicxml, loads_edits


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
    }
    row.update(overrides)
    return row


def _write_fixture_xml(path: Path) -> str:
    from music21 import meter, note, stream, tempo

    part = stream.Part()
    part.insert(0, tempo.MetronomeMark(number=100))
    part.insert(0, meter.TimeSignature("4/4"))
    event = note.Note("C4")
    event.quarterLength = 1.0
    event.volume.velocity = 80
    part.insert(0, event)
    score = stream.Score()
    score.insert(0, part)
    score.write("musicxml", fp=str(path))
    return path.read_text(encoding="utf-8")


def _first_midi_pitch(midi_bytes: bytes) -> int | None:
    midi = mido.MidiFile(file=BytesIO(midi_bytes))
    for track in midi.tracks:
        for msg in track:
            if msg.type == "note_on" and msg.velocity > 0:
                return int(msg.note)
    return None


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'fence.db'}"
    previous_url = db.DATABASE_URL
    previous_engine = db.engine
    monkeypatch.setenv("DATABASE_URL", url)
    db.DATABASE_URL = url
    db.engine = db.create_engine(
        url, connect_args={"check_same_thread": False, "timeout": 30}
    )
    db.SessionLocal.configure(bind=db.engine)
    db.init_db()
    yield tmp_path
    db.engine.dispose()
    db.engine = previous_engine
    db.DATABASE_URL = previous_url
    db.SessionLocal.configure(bind=previous_engine)


def test_cas_edit_revision_allows_only_one_winner(isolated_db):
    job_id = f"edit-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id, status="completed", progress=100, edit_revision=0))
    first = db.cas_update_job(
        job_id,
        expected={"edit_revision": 0},
        edit_revision=1,
        edited_result_storage_key="winner.xml",
    )
    second = db.cas_update_job(
        job_id,
        expected={"edit_revision": 0},
        edit_revision=1,
        edited_result_storage_key="loser.xml",
    )
    job = db.get_job(job_id)
    assert first is True
    assert second is False
    assert job["edit_revision"] == 1
    assert job["edited_result_storage_key"] == "winner.xml"


def test_duplicate_attempt_claim_is_exclusive(isolated_db):
    job_id = f"job-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id))
    assert db.claim_job_attempt(job_id, "attempt-a") is True
    assert db.claim_job_attempt(job_id, "attempt-b") is False
    job = db.get_job(job_id)
    assert job["status"] == "processing"
    assert job["processing_attempt"] == "attempt-a"


def test_late_failure_cannot_replace_successful_attempt(isolated_db):
    job_id = f"job-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id))
    assert db.claim_job_attempt(job_id, "attempt-a")
    assert db.complete_job_attempt(job_id, "attempt-a", result_storage_key="ok.xml")
    assert db.fail_job_attempt(job_id, "attempt-a", "late") is False
    assert db.fail_job_attempt(job_id, "attempt-b", "other") is False
    job = db.get_job(job_id)
    assert job["status"] == "completed"
    assert job["result_storage_key"] == "ok.xml"
    assert job["error"] is None
    assert job["published_attempt"] == "attempt-a"


def test_expired_attempt_cannot_publish_after_new_claim(isolated_db):
    job_id = f"job-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id, status="failed", error="retry"))
    assert db.claim_job_attempt(job_id, "old")
    db.update_job(job_id, status="failed", error="retry")
    assert db.claim_job_attempt(job_id, "new")
    assert db.complete_job_attempt(job_id, "old", result_storage_key="stale.xml") is False
    assert db.complete_job_attempt(job_id, "new", result_storage_key="fresh.xml") is True
    job = db.get_job(job_id)
    assert job["result_storage_key"] == "fresh.xml"
    assert job["published_attempt"] == "new"


def test_unrelated_jobs_publish_independently(isolated_db):
    left = f"left-{uuid.uuid4().hex}"
    right = f"right-{uuid.uuid4().hex}"
    db.create_job(_job_row(left))
    db.create_job(_job_row(right))
    assert db.claim_job_attempt(left, "a")
    assert db.claim_job_attempt(right, "b")
    assert db.complete_job_attempt(left, "a", result_storage_key="left.xml")
    assert db.complete_job_attempt(right, "b", result_storage_key="right.xml")
    assert db.get_job(left)["result_storage_key"] == "left.xml"
    assert db.get_job(right)["result_storage_key"] == "right.xml"


def test_duplicate_process_job_runs_a_single_attempt(isolated_db, monkeypatch):
    job_id = f"proc-{uuid.uuid4().hex}"
    audio = isolated_db / "clip.wav"
    audio.write_bytes(b"RIFF")
    db.create_job(_job_row(job_id, storage_key=str(audio)))
    calls = []
    barrier = threading.Barrier(2)

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
            path = isolated_db / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(Path(local_file_path).read_bytes())
            return str(path)

    monkeypatch.setattr(tasks.storage_service, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr(
        "engine.job_runner.run_job",
        lambda *args, **kwargs: calls.append(threading.get_ident()) or "<score/>",
    )
    monkeypatch.setattr(
        "mir.raw_midi.job_raw_midi_path", lambda *_: isolated_db / "missing.raw"
    )
    monkeypatch.setattr(
        "mir.raw_midi.job_validated_midi_path", lambda *_: isolated_db / "missing.val"
    )
    monkeypatch.setattr(
        "mir.raw_midi.job_score_midi_path", lambda *_: isolated_db / "missing.score"
    )
    monkeypatch.setattr("engine.sidecars.extra_result_files", lambda *_: [])

    def run():
        barrier.wait(timeout=5)
        tasks.process_job(job_id)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    job = db.get_job(job_id)
    assert len(calls) == 1
    assert job["status"] == "completed"
    assert job["published_attempt"]
    xml = Path(job["result_storage_key"])
    assert xml.is_file()
    assert job["id"] in str(xml)
    assert "attempts" in str(xml).replace("\\", "/")


def test_interrupted_bundle_keeps_previous_pointer(isolated_db):
    job_id = f"edit-{uuid.uuid4().hex}"
    original = isolated_db / "orig.musicxml"
    original.write_text("<score original='1'/>", encoding="utf-8")
    db.create_job(
        _job_row(
            job_id,
            status="completed",
            progress=100,
            result_storage_key=str(original),
            edit_revision=1,
            edited_result_storage_key=str(original),
        )
    )
    staged = isolated_db / f"{job_id}.edits" / "abandoned" / f"{job_id}.edited.musicxml"
    staged.parent.mkdir(parents=True)
    staged.write_text("<score abandoned='1'/>", encoding="utf-8")
    job = db.get_job(job_id)
    assert Path(job["edited_result_storage_key"]).read_text(encoding="utf-8") == (
        "<score original='1'/>"
    )
    assert staged.is_file()
    assert sibling_key(str(staged), f"{job_id}.edits.json").endswith(f"{job_id}.edits.json")
    keys = attempt_keys(job_id, "a1")
    assert keys["musicxml"].startswith(f"{job_id}.attempts/a1/")


def test_concurrent_saves_one_success_one_conflict(isolated_db, monkeypatch):
    xml_path = isolated_db / "clip.musicxml"
    _write_fixture_xml(xml_path)
    job_id = f"edit-{uuid.uuid4().hex}"
    db.create_job(
        _job_row(
            job_id,
            status="completed",
            progress=100,
            result_storage_key=str(xml_path),
            edit_revision=0,
        )
    )
    model = extract_from_musicxml(xml_path.read_text(encoding="utf-8"))
    barrier = threading.Barrier(2)
    original_write = app_main._write_edited_sidecars

    def delayed(job, json_text, musicxml_text, midi_bytes):
        barrier.wait(timeout=5)
        return original_write(job, json_text, musicxml_text, midi_bytes)

    monkeypatch.setattr(app_main, "_write_edited_sidecars", delayed)
    results: list[tuple] = []

    def worker(pitch: int) -> None:
        notes = [dict(note) for note in model["notes"]]
        notes[0]["pitch"] = pitch
        body = app_main.ScoreEditsIn(
            revision=0,
            notes=notes,
            tempo_bpm=model["tempo_bpm"],
            time_signature=model["time_signature"],
            tempo_curve=model.get("tempo_curve"),
        )
        try:
            payload = app_main.score_edits_put(job_id, body, authorization=None)
            results.append(("ok", pitch, payload))
        except HTTPException as exc:
            results.append(("err", pitch, exc.status_code))

    threads = [
        threading.Thread(target=worker, args=(61,)),
        threading.Thread(target=worker, args=(62,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    successes = [row for row in results if row[0] == "ok"]
    conflicts = [row for row in results if row[0] == "err" and row[2] == 409]
    assert len(results) == 2
    assert len(successes) == 1
    assert len(conflicts) == 1
    winner_pitch = successes[0][1]
    job = db.get_job(job_id)
    assert job["edit_revision"] == 1
    pointer = Path(job["edited_result_storage_key"])
    assert pointer.is_file()
    assert f"{job_id}.edits" in str(pointer).replace("\\", "/")
    json_text = pointer.with_name(f"{job_id}.edits.json").read_text(encoding="utf-8")
    saved = loads_edits(json_text)
    xml_model = extract_from_musicxml(pointer.read_text(encoding="utf-8"))
    midi_pitch = _first_midi_pitch(pointer.with_name(f"{job_id}.edited.mid").read_bytes())
    assert saved["notes"][0]["pitch"] == winner_pitch
    assert xml_model["notes"][0]["pitch"] == winner_pitch
    assert midi_pitch == winner_pitch


def test_save_versus_reset_is_exclusive(isolated_db, monkeypatch):
    xml_path = isolated_db / "clip.musicxml"
    original = _write_fixture_xml(xml_path)
    job_id = f"edit-{uuid.uuid4().hex}"
    db.create_job(
        _job_row(
            job_id,
            status="completed",
            progress=100,
            result_storage_key=str(xml_path),
            edit_revision=0,
        )
    )
    model = extract_from_musicxml(original)
    barrier = threading.Barrier(2)
    original_write = app_main._write_edited_sidecars

    def delayed(job, json_text, musicxml_text, midi_bytes):
        barrier.wait(timeout=5)
        return original_write(job, json_text, musicxml_text, midi_bytes)

    monkeypatch.setattr(app_main, "_write_edited_sidecars", delayed)
    outcomes: list[str] = []

    def save() -> None:
        notes = [dict(note) for note in model["notes"]]
        notes[0]["pitch"] = 72
        body = app_main.ScoreEditsIn(
            revision=0,
            notes=notes,
            tempo_bpm=model["tempo_bpm"],
            time_signature=model["time_signature"],
        )
        try:
            app_main.score_edits_put(job_id, body, authorization=None)
            outcomes.append("save")
        except HTTPException as exc:
            outcomes.append(f"save-{exc.status_code}")

    def reset() -> None:
        barrier.wait(timeout=5)
        try:
            app_main.score_edits_reset(job_id, authorization=None)
            outcomes.append("reset")
        except HTTPException as exc:
            outcomes.append(f"reset-{exc.status_code}")

    threads = [threading.Thread(target=save), threading.Thread(target=reset)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    job = db.get_job(job_id)
    assert job["edit_revision"] == 1
    assert len(outcomes) == 2
    assert sum(item in {"save", "reset"} for item in outcomes) == 1
    assert sum("409" in item for item in outcomes) == 1
    if "save" in outcomes:
        assert job["edited_result_storage_key"]
        assert Path(job["edited_result_storage_key"]).is_file()
    else:
        assert job["edited_result_storage_key"] is None
        assert xml_path.read_text(encoding="utf-8") == original
