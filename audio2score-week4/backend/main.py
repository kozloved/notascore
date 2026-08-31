from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from contextlib import asynccontextmanager
from pathlib import Path
import os
import uuid

import database as db
import storage as storage_service
import job_queue as queue_service
from modes import POLYPHONIC, canonical_mode

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "results"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
CORS_ORIGIN = os.getenv(
    "CORS_ORIGIN",
    "http://localhost:3000,http://127.0.0.1:3000",
)


def _cors_origins() -> list[str]:
    origins = [
        origin.strip()
        for origin in CORS_ORIGIN.split(",")
        if origin.strip()
    ]
    extra = (os.getenv("FRONTEND_PUBLIC_URL") or "").strip()
    if extra and extra not in origins:
        origins.append(extra)
    return origins

ALLOWED_AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".m4a",
    ".flac",
}
ALLOWED_MIDI_EXTENSIONS = {".mid", ".midi"}
ALLOWED_EXTENSIONS = ALLOWED_AUDIO_EXTENSIONS | ALLOWED_MIDI_EXTENSIONS
MIDI_CONTENT_TYPES = {
    "audio/midi",
    "audio/mid",
    "audio/x-midi",
    "audio/sp-midi",
    "application/midi",
    "application/x-midi",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage_service.LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()
    yield


app = FastAPI(
    title="NotaScore",
    lifespan=lifespan,
)

origins = _cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def is_allowed_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


SOURCE_MEDIA_TYPES = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".flac": "audio/flac",
    ".mid": "audio/midi",
    ".midi": "audio/midi",
}


def _is_midi_name(name) -> bool:
    return Path(name or "").suffix.lower() in ALLOWED_MIDI_EXTENSIONS


def _job_source_kind(job: dict) -> str:
    if _is_midi_name(job.get("filename")) or _is_midi_name(job.get("storage_key")):
        return "midi"
    return "audio"


def _safe_download_name(name: str) -> str:
    return Path(name).name.replace('"', "").replace("\r", "").replace("\n", "")


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
        "mode": canonical_mode(job.get("mode")),
        "source_kind": _job_source_kind(job),
        "result_available": bool(job.get("result_storage_key")),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


@app.get("/health")
def health():
    from adapters.basic_pitch_backend import basic_pitch_settings
    from adapters.mt3_backend import mt3_status
    from audio_engine.beat_tracker import beat_status
    from intelligence.config import gemini_status
    from mir.pipeline_config import load_pipeline_config

    bp = basic_pitch_settings()
    mt3 = mt3_status()
    gemini = gemini_status()
    poly_available = bool(mt3["available"])
    cfg = load_pipeline_config()
    return {
        "status": "ok",
        "engine": os.getenv("TRANSCRIPTION_ENGINE", "basic_pitch"),
        "pipeline": os.getenv("TRANSCRIPTION_PIPELINE", "understanding"),
        "mode": os.getenv("TRANSCRIPTION_MODE", "solo"),
        "backend": os.getenv("TRANSCRIPTION_BACKEND", "basic_pitch"),
        "use_cleaner": os.getenv("TRANSCRIPTION_USE_CLEANER", "0"),
        "use_normalizer": os.getenv("TRANSCRIPTION_USE_NORMALIZER", "1"),
        "use_beat_tracker": os.getenv("TRANSCRIPTION_USE_BEAT_TRACKER", "1"),
        "use_piano_analyzer": os.getenv("TRANSCRIPTION_USE_PIANO_ANALYZER", "1"),
        "use_mir_layers": os.getenv("TRANSCRIPTION_USE_MIR_LAYERS", "1"),
        "pipeline_fallback": os.getenv("TRANSCRIPTION_PIPELINE_FALLBACK", "1"),
        "validation_mode": cfg.validation_mode.value,
        "quantization_mode": cfg.quantization_mode.value,
        "enable_gemini": cfg.enable_gemini,
        "canonical": cfg.to_dict(),
        "basic_pitch": bp,
        "polyphonic": mt3,
        "quality": mt3,
        "gemini": gemini,
        "beat": beat_status(),
        "modes": {
            "solo": True,
            "polyphonic": poly_available,
            "fast": True,
            "quality": poly_available,
        },
    }


@app.post("/upload", status_code=202)
async def upload(
    file: UploadFile = File(...),
    mode: str = Form("solo"),
):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file provided",
        )

    if not is_allowed_filename(file.filename):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Allowed types: .wav, .mp3, .m4a, .flac, .mid, .midi",
        )

    from transcription import parse_transcription_mode, queue_timeout_for_mode

    try:
        resolved_mode = parse_transcription_mode(mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Browsers send audio/* or audio/midi; CLI tools often send application/octet-stream.
    # Trust the allowed extension when the declared type is missing or generic.
    content_type = (file.content_type or "").lower()
    suffix = Path(file.filename).suffix.lower()
    midi_upload = suffix in ALLOWED_MIDI_EXTENSIONS
    if resolved_mode == POLYPHONIC and not midi_upload:
        from adapters.mt3_backend import mt3_available

        if not mt3_available():
            raise HTTPException(
                status_code=503,
                detail=(
                    "Polyphonic mode is not configured. "
                    "Set MT3_ENDPOINT or MT3_TRANSCRIBE_COMMAND."
                ),
            )
    if content_type and not (
        content_type.startswith("audio/")
        or content_type in ("application/octet-stream", "binary/octet-stream")
        or (midi_upload and content_type in MIDI_CONTENT_TYPES)
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid content type. Please upload an audio or MIDI file.",
        )

    job_id = str(uuid.uuid4())

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
        "mode": resolved_mode,
    }

    db.create_job(job)

    try:
        queue_service.enqueue_job(
            job_id,
            job_timeout=queue_timeout_for_mode(resolved_mode),
        )
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


def _source_media_type(job: dict) -> str:
    suffix = Path(job.get("filename") or job.get("storage_key") or "").suffix.lower()
    if suffix in SOURCE_MEDIA_TYPES:
        return SOURCE_MEDIA_TYPES[suffix]
    content_type = (job.get("content_type") or "").strip()
    if content_type and content_type.lower() not in (
        "application/octet-stream",
        "binary/octet-stream",
    ):
        return content_type
    return "application/octet-stream"


@app.get("/jobs/{job_id}/source")
def job_source(job_id: str):
    """Original uploaded audio (or MIDI) for in-page preview."""
    job = db.get_job(job_id)

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    storage_key = job.get("storage_key")
    if not storage_key:
        raise HTTPException(
            status_code=404,
            detail="Original file is not available",
        )

    storage_backend = storage_service.get_storage()
    media_type = _source_media_type(job)
    filename = _safe_download_name(job.get("filename") or Path(storage_key).name)

    if storage_backend.backend == "local":
        path = Path(storage_key)
        if not path.exists():
            raise HTTPException(
                status_code=404,
                detail="Original file is missing",
            )
        return FileResponse(
            path=str(path),
            media_type=media_type,
            filename=filename,
            content_disposition_type="inline",
        )

    try:
        data = storage_backend.read_upload_bytes(storage_key)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail="Original file is missing",
        ) from exc

    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Accept-Ranges": "bytes",
        },
    )


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

    if fmt not in ("musicxml", "midi", "midi_score"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported format. Use 'musicxml', 'midi', or 'midi_score'.",
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

    if fmt == "midi":
        raw_bytes = _load_sidecar_midi_bytes(
            storage_backend, job_id, result_storage_key, f"{job_id}.raw.mid"
        )
        if raw_bytes:
            return Response(
                content=raw_bytes,
                media_type="audio/midi",
                headers={
                    "Content-Disposition": f'attachment; filename="{stem}.mid"',
                },
            )
        # Older jobs: fall back to score MIDI derived from MusicXML.

    if fmt == "midi_score":
        score_bytes = _load_sidecar_midi_bytes(
            storage_backend, job_id, result_storage_key, f"{job_id}.score.mid"
        )
        if score_bytes:
            return Response(
                content=score_bytes,
                media_type="audio/midi",
                headers={
                    "Content-Disposition": f'attachment; filename="{stem}.score.mid"',
                },
            )

    # fmt == "midi_score" (or sidecars missing): derive from stored MusicXML.
    try:
        musicxml_text = storage_backend.read_result_text(result_storage_key)
        midi_bytes = _musicxml_to_midi_bytes(musicxml_text)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to generate MIDI from the transcription.",
        ) from exc

    filename = f"{stem}.score.mid" if fmt == "midi_score" else f"{stem}.mid"
    return Response(
        content=midi_bytes,
        media_type="audio/midi",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _load_sidecar_midi_bytes(
    storage_backend, job_id: str, result_storage_key: str, filename: str
):
    try:
        if storage_backend.backend == "local":
            midi_path = Path(result_storage_key).with_name(filename)
            if midi_path.exists():
                return midi_path.read_bytes()
            return None
        return storage_backend.read_result_bytes(filename)
    except Exception:
        return None
