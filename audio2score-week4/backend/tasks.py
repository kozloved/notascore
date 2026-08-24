from dotenv import load_dotenv

load_dotenv()

import time
from pathlib import Path

import database as db
import storage as storage_service
import transcription as transcription_service


def process_job(job_id: str):
    storage_backend = storage_service.get_storage()
    audio_local_path = None

    try:
        job = db.get_job(job_id)

        if not job:
            return

        db.update_job(
            job_id,
            status="processing",
            progress=5,
            error=None,
        )

        audio_local_path = storage_backend.get_local_audio_path(
            job["storage_key"]
        )

        db.update_job(job_id, progress=20)

        engine = transcription_service.get_engine()

        db.update_job(job_id, progress=35)

        musicxml_text = engine.transcribe(
            audio_local_path,
            job_id,
        )

        db.update_job(job_id, progress=75)

        result_key = f"{job_id}.musicxml"

        stored_result_key = storage_backend.save_text(
            result_key,
            musicxml_text,
            content_type="application/vnd.recordare.musicxml+xml",
        )

        from mir.raw_midi import job_raw_midi_path, job_score_midi_path

        for midi_path, key in (
            (job_raw_midi_path(audio_local_path, job_id), f"{job_id}.raw.mid"),
            (job_score_midi_path(audio_local_path, job_id), f"{job_id}.score.mid"),
        ):
            if midi_path.exists():
                storage_backend.save_local_file(
                    midi_path,
                    key,
                    content_type="audio/midi",
                )

        db.update_job(
            job_id,
            status="completed",
            progress=100,
            result_storage_key=stored_result_key,
            error=None,
        )

    except Exception as exc:
        db.update_job(
            job_id,
            status="failed",
            error=str(exc),
        )

    finally:
        if audio_local_path and storage_backend.backend != "local":
            Path(audio_local_path).unlink(missing_ok=True)
