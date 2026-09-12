from dotenv import load_dotenv

load_dotenv()

import uuid
import shutil
import tempfile
from pathlib import Path

import database as db
import storage as storage_service
from lifecycle import (
    AttemptHeartbeat,
    build_publish_manifest,
    discover_unreachable_attempt_ids,
    schedule_attempt_gc,
    sweep_artifact_gc,
    verify_uploaded_hashes,
    write_publish_manifest,
)
from publishing import attempt_keys, attempt_object_key


def _progress(job_id: str, attempt_id: str, progress: int) -> bool:
    return db.heartbeat_job_attempt(job_id, attempt_id, progress=progress)


def _renew_lease(job_id: str, attempt_id: str) -> bool:
    return db.heartbeat_job_attempt(job_id, attempt_id)


def process_job(job_id: str):
    storage_backend = storage_service.get_storage()
    audio_local_path = None
    downloaded_path = None
    workspace = None
    attempt_id = uuid.uuid4().hex
    heartbeat = None

    try:
        job = db.get_job(job_id)

        if not job:
            return

        if not db.claim_job_attempt(job_id, attempt_id):
            return

        job = db.get_job(job_id)
        downloaded_path = storage_backend.get_local_audio_path(
            job["storage_key"]
        )
        # Engines derive their output folder from the input's parent. Each
        # attempt needs its own input and scratch files, including on retries.
        workspace = tempfile.TemporaryDirectory(prefix=f"notascore-{attempt_id}-")
        audio_local_path = Path(workspace.name) / Path(downloaded_path).name
        shutil.copyfile(downloaded_path, audio_local_path)

        heartbeat = AttemptHeartbeat(job_id, attempt_id, _renew_lease).start()

        if not _progress(job_id, attempt_id, 20):
            return

        from engine.job_runner import run_job

        if not heartbeat.alive or not _progress(job_id, attempt_id, 35):
            return

        musicxml_text = run_job(
            audio_local_path,
            job_id,
            mode=job.get("mode") or "solo",
            filename=job.get("filename") or str(audio_local_path),
        )

        if not heartbeat.alive or not _progress(job_id, attempt_id, 75):
            return

        keys = attempt_keys(job_id, attempt_id)
        out_dir = Path(audio_local_path).parent / f"bp_{job_id}"
        musicxml_path = out_dir / f"{job_id}.musicxml"
        musicxml_path.parent.mkdir(parents=True, exist_ok=True)
        musicxml_path.write_text(musicxml_text, encoding="utf-8")

        from mir.raw_midi import (
            job_raw_midi_path,
            job_score_midi_path,
            job_validated_midi_path,
        )

        local_files = {
            "musicxml": musicxml_path,
            "raw": job_raw_midi_path(audio_local_path, job_id),
            "validated": job_validated_midi_path(audio_local_path, job_id),
            "score": job_score_midi_path(audio_local_path, job_id),
        }

        # Upload required + available midis first, then validate hashes.
        stored_result_key = storage_backend.save_text(
            keys["musicxml"],
            musicxml_text,
            content_type="application/vnd.recordare.musicxml+xml",
        )

        for midi_path, key in (
            (local_files["raw"], keys["raw"]),
            (local_files["validated"], keys["validated"]),
            (local_files["score"], keys["score"]),
        ):
            if midi_path.exists():
                storage_backend.save_local_file(
                    midi_path,
                    key,
                    content_type="audio/midi",
                )

        from engine.sidecars import extra_result_files, result_object_key

        uploaded = {
            Path(keys["raw"]).name,
            Path(keys["validated"]).name,
            Path(keys["score"]).name,
            Path(keys["musicxml"]).name,
        }
        for extra in extra_result_files(out_dir, job_id):
            name = result_object_key(extra)
            if name in uploaded:
                continue
            mime = "audio/midi" if extra.suffix.lower() in {".mid", ".midi"} else (
                "audio/wav" if extra.suffix.lower() == ".wav" else "application/json"
            )
            storage_backend.save_local_file(
                extra,
                attempt_object_key(job_id, attempt_id, name),
                content_type=mime,
            )
            local_files[name] = extra

        if not heartbeat.alive:
            return

        manifest = build_publish_manifest(job_id, attempt_id, local_files)
        verify_uploaded_hashes(storage_backend, manifest)
        write_publish_manifest(storage_backend, job_id, attempt_id, manifest)

        published = db.complete_job_attempt(
            job_id,
            attempt_id,
            result_storage_key=stored_result_key,
            progress=100,
            error=None,
        )
        if not published:
            return
        doomed = discover_unreachable_attempt_ids(
            storage_backend, job_id, keep_attempt_ids={attempt_id}
        )
        schedule_attempt_gc(job_id, doomed, keep_attempt_ids={attempt_id})
        try:
            sweep_artifact_gc(storage_backend)
        except Exception:
            pass

    except Exception as exc:
        public_error = str(exc)
        code = getattr(exc, "code", None)
        if code:
            print(f"[Job {job_id}] {code}: {exc}", flush=True)
        if getattr(exc, "public_message", None):
            public_error = exc.public_message
        # Publish/validation failures are attempt failures, not silent success.
        db.fail_job_attempt(job_id, attempt_id, public_error)

    finally:
        if heartbeat is not None:
            heartbeat.stop()
        if workspace is not None:
            workspace.cleanup()
        if downloaded_path and storage_backend.backend != "local":
            Path(downloaded_path).unlink(missing_ok=True)
