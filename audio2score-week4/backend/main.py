from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from contextlib import asynccontextmanager
from pathlib import Path
import os
import uuid

import database as db
import storage as storage_service
import job_queue as queue_service

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "results"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "http://localhost:3000")

ALLOWED_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage_service.LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()
    yield


app = FastAPI(
    title="Audio2Score API",
    lifespan=lifespan,
)

origins = [
    origin.strip()
    for origin in CORS_ORIGIN.split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def is_allowed_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def public_job(job: dict) -> dict:
    if not job:
        return {}

    return {
        "job_id": job.get("id"),
        "status": job.get("status"),
        "filename": job.get("filename"),
        "content_type": job.get("content_type"),
        "size_bytes": job.get("size_bytes"),
        "progress": job.get("progress", 0),
        "error": job.get("error"),
        "result_available": bool(job.get("result_storage_key")),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "engine": os.getenv("TRANSCRIPTION_ENGINE", "placeholder"),
    }


@app.post("/upload", status_code=202)
async def upload(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file provided",
        )

    if not is_allowed_filename(file.filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Allowed types: .wav, .mp3, .m4a, .flac",
        )

    if file.content_type and not file.content_type.startswith("audio/"):
        raise HTTPException(
            status_code=400,
            detail="Invalid content type. Please upload an audio file.",
        )

    job_id = str(uuid.uuid4())
    suffix = Path(file.filename).suffix.lower()

    temp_path = storage_service.LOCAL_TEMP_DIR / f"{job_id}.part"

    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    size = 0
    too_large = False

    try:
        with temp_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                size += len(chunk)

                if size > max_bytes:
                    too_large = True
                    break

                out.write(chunk)

        if too_large:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Max {MAX_UPLOAD_MB} MB.",
            )

        if size == 0:
            raise HTTPException(
                status_code=400,
                detail="File is empty",
            )

    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise

    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="Failed to receive file.",
        ) from exc

    storage_backend = storage_service.get_storage()

    audio_key = f"audio/{job_id}{suffix}"

    try:
        storage_key = storage_backend.save_upload_file(
            temp_path,
            audio_key,
            content_type=file.content_type,
        )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=502,
            detail="Failed to store uploaded file.",
        ) from exc

    now = db.utcnow()

    job = {
        "id": job_id,
        "status": "queued",
        "filename": Path(file.filename).name,
        "content_type": file.content_type,
        "size_bytes": size,
        "storage_key": storage_key,
        "result_storage_key": None,
        "progress": 0,
        "error": None,
        "created_at": now,
        "updated_at": now,
    }

    db.create_job(job)

    try:
        queue_service.enqueue_job(job_id)
    except Exception as exc:
        db.update_job(
            job_id,
            status="failed",
            error="Failed to enqueue job",
        )

        raise HTTPException(
            status_code=503,
            detail="Queue unavailable. Make sure Redis is running.",
        ) from exc

    return public_job(job)


@app.get("/jobs")
def jobs_list(limit: int = 50):
    limit = max(1, min(limit, 200))

    jobs = db.list_jobs(limit)

    return [
        public_job(job)
        for job in jobs
    ]


@app.get("/jobs/{job_id}")
def job_detail(job_id: str):
    job = db.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return public_job(job)


def _musicxml_to_midi_bytes(musicxml_text: str) -> bytes:
    from music21 import converter
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "score.musicxml"
        xml_path.write_text(musicxml_text, encoding="utf-8")

        score = converter.parse(str(xml_path))

        midi_path = Path(tmp) / "score.mid"
        score.write("midi", fp=str(midi_path))

        return midi_path.read_bytes()


@app.get("/jobs/{job_id}/result")
def job_result(job_id: str, format: str = "musicxml"):
    fmt = (format or "musicxml").lower()

    if fmt not in ("musicxml", "midi"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported format. Use 'musicxml' or 'midi'.",
        )

    job = db.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    if job.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail="Job is not completed yet",
        )

    result_storage_key = job.get("result_storage_key")

    if not result_storage_key:
        raise HTTPException(
            status_code=404,
            detail="Result not available",
        )

    storage_backend = storage_service.get_storage()
    stem = Path(job.get("filename") or "result").stem

    if storage_backend.backend == "local" and not Path(result_storage_key).exists():
        raise HTTPException(
            status_code=404,
            detail="Result file missing",
        )

    if fmt == "musicxml":
        if storage_backend.backend == "local":
            return FileResponse(
                path=str(Path(result_storage_key)),
                media_type="application/vnd.recordare.musicxml+xml",
                filename=f"{stem}.musicxml",
            )

        signed_url = storage_backend.get_result_signed_url(
            result_storage_key,
            expires_in=3600,
        )

        if not signed_url:
            raise HTTPException(
                status_code=502,
                detail="Failed to generate download URL",
            )

        return RedirectResponse(signed_url)

    # fmt == "midi": derive a MIDI file from the stored MusicXML on the fly.
    try:
        musicxml_text = storage_backend.read_result_text(result_storage_key)
        midi_bytes = _musicxml_to_midi_bytes(musicxml_text)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate MIDI from the transcription.",
        ) from exc

    return Response(
        content=midi_bytes,
        media_type="audio/midi",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.mid"',
        },
    )
