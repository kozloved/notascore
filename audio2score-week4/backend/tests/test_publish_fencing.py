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

        def gc_unreachable_attempts(self, job_id, keep_attempt_ids=()):
            return

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


def test_fresh_processing_claim_is_not_stolen(isolated_db):
    job_id = f"job-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id))
    assert db.claim_job_attempt(job_id, "live") is True
    assert db.claim_job_attempt(job_id, "thief") is False
    job = db.get_job(job_id)
    assert job["processing_attempt"] == "live"


def test_stale_processing_claim_can_be_reclaimed(isolated_db):
    from datetime import datetime, timedelta, timezone

    job_id = f"job-{uuid.uuid4().hex}"
    db.create_job(_job_row(job_id))
    assert db.claim_job_attempt(job_id, "stuck") is True
    past = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    session = db.SessionLocal()
    try:
        session.query(db.Job).filter(db.Job.id == job_id).update(
            {"updated_at": past}, synchronize_session=False
        )
        session.commit()
    finally:
        session.close()
    assert db.claim_job_attempt(job_id, "rescue", stale_after_seconds=30) is True
    job = db.get_job(job_id)
    assert job["processing_attempt"] == "rescue"
    assert db.complete_job_attempt(job_id, "stuck", result_storage_key="stale.xml") is False
    assert db.complete_job_attempt(job_id, "rescue", result_storage_key="fresh.xml") is True
    assert db.get_job(job_id)["result_storage_key"] == "fresh.xml"


def test_local_gc_lists_and_deletes_orphaned_attempt_prefix(isolated_db, monkeypatch):
    from storage import LocalStorage

    monkeypatch.setenv("RESULTS_DIR", str(isolated_db / "results"))
    import storage as storage_mod

    storage_mod.LOCAL_RESULTS_DIR = isolated_db / "results"
    storage_mod.LOCAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    backend = LocalStorage()
    job_id = "job-gc"
    keep = isolated_db / "results" / f"{job_id}.attempts" / "keep" / f"{job_id}.musicxml"
    drop = isolated_db / "results" / f"{job_id}.attempts" / "drop" / f"{job_id}.extra.json"
    keep.parent.mkdir(parents=True)
    drop.parent.mkdir(parents=True)
    keep.write_text("<score/>", encoding="utf-8")
    drop.write_text("{}", encoding="utf-8")
    listed = backend.list_result_keys(f"{job_id}.attempts")
    assert any(path.endswith("extra.json") for path in listed)
    backend.gc_unreachable_attempts(job_id, keep_attempt_ids={"keep"})
    assert keep.is_file()
    assert not drop.exists()


def test_supabase_gc_lists_prefix_instead_of_known_keys_only():
    from storage import SupabaseStorage

    removed = []

    class FakeBucket:
        def list(self, path):
            if path == "job-gc.attempts":
                return [{"name": "old", "id": None, "metadata": None}]
            if path == "job-gc.attempts/old":
                return [
                    {"name": "job-gc.musicxml", "id": "1", "metadata": {"size": 4}},
                    {"name": "job-gc.extra.json", "id": "2", "metadata": {"size": 2}},
                ]
            return []

        def remove(self, keys):
            removed.extend(keys)

    backend = SupabaseStorage.__new__(SupabaseStorage)
    backend.results_bucket = "results"
    backend._bucket = lambda name: FakeBucket()
    backend.gc_unreachable_attempts("job-gc", keep_attempt_ids={"keep"})
    assert "job-gc.attempts/old/job-gc.extra.json" in removed
    assert "job-gc.attempts/old/job-gc.musicxml" in removed


def test_save_response_uses_its_own_committed_revision(isolated_db, monkeypatch):
    xml = isolated_db / 'original.musicxml'
    model = extract_from_musicxml(_write_fixture_xml(xml))
    job_id = 'response-race'
    db.create_job(_job_row(job_id, status='completed', result_storage_key=str(xml), edit_revision=0))
    original_cas = db.cas_update_job

    def publish_then_another_save(*args, **kwargs):
        published = original_cas(*args, **kwargs)
        if published:
            db.update_job(job_id, edit_revision=2, edited_result_storage_key='later.xml')
        return published

    monkeypatch.setattr(db, 'cas_update_job', publish_then_another_save)
    response = app_main.score_edits_put(
        job_id, app_main.ScoreEditsIn(revision=0, **model), authorization=None
    )
    assert response['revision'] == 1
    assert db.get_job(job_id)['edit_revision'] == 2


def test_reset_restores_canonical_model_before_publishing(isolated_db, monkeypatch):
    xml = isolated_db / 'original.musicxml'
    model = extract_from_musicxml(_write_fixture_xml(xml))
    model['provenance'] = 'performance'
    model['notes'][0]['source_note_id'] = 'original-attack'
    model['notes'][0]['start_sec'] = 0.125
    job_id = 'reset-performance'
    db.create_job(_job_row(job_id, status='completed', result_storage_key=str(xml),
                           edited_result_storage_key='edited.xml', edit_revision=3))

    def load_original(job):
        assert job['edited_result_storage_key'] is None
        assert db.get_job(job_id)['edit_revision'] == 3
        return model

    monkeypatch.setattr(app_main, '_load_edit_model', load_original)
    response = app_main.score_edits_reset(job_id, authorization=None)
    assert response['provenance'] == 'performance'
    assert response['notes'][0]['source_note_id'] == 'original-attack'
    assert response['notes'][0]['start_sec'] == 0.125
    assert response['revision'] == 4


def test_failed_reset_keeps_existing_edit(isolated_db, monkeypatch):
    job_id = 'reset-failure'
    db.create_job(_job_row(job_id, status='completed', result_storage_key='missing.xml',
                           edited_result_storage_key='edited.xml', edit_revision=3))

    def fail_load(job):
        raise ValueError('unreadable original')

    monkeypatch.setattr(app_main, '_load_edit_model', fail_load)
    with pytest.raises(HTTPException) as error:
        app_main.score_edits_reset(job_id, authorization=None)
    assert error.value.status_code == 500
    assert db.get_job(job_id)['edit_revision'] == 3
    assert db.get_job(job_id)['edited_result_storage_key'] == 'edited.xml'


def test_reclaimed_workers_do_not_share_generated_files(isolated_db, monkeypatch):
    import storage

    monkeypatch.setattr(storage, 'LOCAL_RESULTS_DIR', isolated_db / 'results')
    backend = storage.LocalStorage()
    monkeypatch.setattr(tasks.storage_service, 'get_storage', lambda: backend)
    audio = isolated_db / 'clip.wav'
    audio.write_bytes(b'RIFF')
    job_id = 'scratch-race'
    db.create_job(_job_row(job_id, storage_key=str(audio)))
    old_started = threading.Event()
    new_written = threading.Event()
    old_written = threading.Event()
    paths = []

    def runner(source, job_id, **kwargs):
        source = Path(source)
        paths.append(source)
        folder = source.parent / f'bp_{job_id}'
        folder.mkdir(exist_ok=True)
        midi = folder / f'{job_id}.raw.mid'
        if len(paths) == 1:
            old_started.set()
            assert new_written.wait(5)
            midi.write_bytes(b'old-attempt')
            old_written.set()
            return '<old/>'
        midi.write_bytes(b'new-attempt')
        new_written.set()
        assert old_written.wait(5)
        return '<new/>'

    monkeypatch.setattr('engine.job_runner.run_job', runner)
    old = threading.Thread(target=tasks.process_job, args=(job_id,))
    old.start()
    assert old_started.wait(5)
    db.update_job(job_id, status='failed')
    tasks.process_job(job_id)
    old.join(timeout=5)
    assert not old.is_alive()
    job = db.get_job(job_id)
    assert job['status'] == 'completed'
    published = Path(job['result_storage_key'])
    assert published.read_text() == '<new/>'
    assert published.with_name(f'{job_id}.raw.mid').read_bytes() == b'new-attempt'
    assert paths[0].parent != paths[1].parent
    assert audio.read_bytes() == b'RIFF'
    assert all(not path.parent.exists() for path in paths)


def test_local_delete_result_handles_nested_edit_bundle(isolated_db, monkeypatch):
    import storage

    monkeypatch.setattr(storage, 'LOCAL_RESULTS_DIR', isolated_db / 'results')
    backend = storage.LocalStorage()
    key = backend.save_text('delete-job.attempts/a/delete-job.musicxml', '<score/>')
    nested = Path(key).parent / 'delete-job.edits' / 'edit1'
    nested.mkdir(parents=True)
    (nested / 'delete-job.edits.json').write_text('{}')
    backend.delete_result(key, 'delete-job')
    assert not Path(key).parent.exists()


def test_remote_downloads_have_independent_local_paths(isolated_db, monkeypatch):
    import storage

    monkeypatch.setattr(storage, 'LOCAL_TEMP_DIR', isolated_db)
    backend = storage.SupabaseStorage.__new__(storage.SupabaseStorage)
    backend.audio_bucket = 'audio'

    class Bucket:
        def download(self, key):
            return b'RIFF'

    backend._bucket = lambda name: Bucket()
    first = backend.get_local_audio_path('clip.wav')
    second = backend.get_local_audio_path('clip.wav')
    assert first != second
    first.unlink()
    assert second.read_bytes() == b'RIFF'
