from dotenv import load_dotenv

load_dotenv()

import uuid
from pathlib import Path

import database as db
import storage as storage_service
from publishing import attempt_keys, attempt_object_key


def _progress(job_id: str, attempt_id: str, progress: int) -> bool:
    return db.cas_update_job(
        job_id,
        expected={"status": "processing", "processing_attempt": attempt_id},
        progress=progress,
    )


def process_job(job_id: str):
    storage_backend = storage_service.get_storage()
    audio_local_path = None
    attempt_id = uuid.uuid4().hex

    try:
        job = db.get_job(job_id)

        if not job:
            return

        if not db.claim_job_attempt(job_id, attempt_id):
            return

        job = db.get_job(job_id)
        audio_local_path = storage_backend.get_local_audio_path(
            job["storage_key"]
        )

        if not _progress(job_id, attempt_id, 20):
            return

        from engine.job_runner import run_job

        if not _progress(job_id, attempt_id, 35):
            return

        musicxml_text = run_job(
            audio_local_path,
            job_id,
            mode=job.get("mode") or "solo",
            filename=job.get("filename") or str(audio_local_path),
        )

        if not _progress(job_id, attempt_id, 75):
            return

        keys = attempt_keys(job_id, attempt_id)
        stored_result_key = storage_backend.save_text(
            keys["musicxml"],
            musicxml_text,
            content_type="application/vnd.recordare.musicxml+xml",
        )

        from mir.raw_midi import (
            job_raw_midi_path,
            job_score_midi_path,
            job_validated_midi_path,
        )

        for midi_path, key in (
            (job_raw_midi_path(audio_local_path, job_id), keys["raw"]),
            (job_validated_midi_path(audio_local_path, job_id), keys["validated"]),
            (job_score_midi_path(audio_local_path, job_id), keys["score"]),
        ):
            if midi_path.exists():
                storage_backend.save_local_file(
                    midi_path,
                    key,
                    content_type="audio/midi",
                )

        from engine.sidecars import extra_result_files, result_object_key

        out_dir = Path(audio_local_path).parent / f"bp_{job_id}"
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

        published = db.complete_job_attempt(
            job_id,
            attempt_id,
            result_storage_key=stored_result_key,
            progress=100,
            error=None,
        )
        if not published:
            return

    except Exception as exc:
        public_error = str(exc)
        code = getattr(exc, "code", None)
        if code:
            print(f"[Job {job_id}] {code}: {exc}", flush=True)
        if getattr(exc, "public_message", None):
            public_error = exc.public_message
        db.fail_job_attempt(job_id, attempt_id, public_error)

    finally:
        if audio_local_path and storage_backend.backend != "local":
            Path(audio_local_path).unlink(missing_ok=True)
