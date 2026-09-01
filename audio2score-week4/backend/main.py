from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from contextlib import asynccontextmanager
from pathlib import Path
from pydantic import BaseModel, Field
import os
import uuid

import database as db
import storage as storage_service
import job_queue as queue_service
from auth_user import NOT_FOUND_DETAIL, SIGN_IN_DETAIL, user_id_from_authorization
from modes import POLYPHONIC, canonical_mode
from ownership import (
    hash_claim_token,
    job_visible_to,
    new_claim_token,
    sanitize_title,
    title_from_filename,
)
from score_edits import (
    EditError,
    build_musicxml_and_midi,
    edited_keys,
    extract_from_musicxml,
    loads_edits,
    dumps_edits,
    parse_edits_payload,
)

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


def public_job(job: dict, *, claim_token: str | None = None) -> dict:
    if not job:
        return {}

    payload = {
        "job_id": job.get("id"),
        "score_id": job.get("id"),
        "status": job.get("status"),
        "filename": job.get("filename"),
        "title": job.get("title") or title_from_filename(job.get("filename")),
        "duration_seconds": job.get("duration_seconds"),
        "content_type": job.get("content_type"),
        "size_bytes": job.get("size_bytes"),
        "progress": job.get("progress", 0),
        "error": job.get("error"),
        "mode": canonical_mode(job.get("mode")),
        "source_kind": _job_source_kind(job),
        "result_available": bool(job.get("result_storage_key")),
        "owned": bool(job.get("user_id")),
        "has_edits": bool(job.get("edited_result_storage_key")),
        "edit_revision": int(job.get("edit_revision") or 0),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }
    if claim_token:
        payload["claim_token"] = claim_token
    return payload


def _optional_user_id(authorization: str | None) -> str | None:
    return user_id_from_authorization(authorization)


def _require_user_id(authorization: str | None) -> str:
    user_id = user_id_from_authorization(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail=SIGN_IN_DETAIL)
    return user_id


def _visible_job(job_id: str, authorization: str | None) -> dict:
    job = db.get_job(job_id)
    if not job_visible_to(job, _optional_user_id(authorization)):
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    return job


def _parse_duration(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    if seconds < 0 or seconds > 24 * 60 * 60:
        return None
    return seconds


def _delete_job_files(job: dict) -> None:
    storage_backend = storage_service.get_storage()
    try:
        storage_backend.delete_upload(job.get("storage_key"))
    except Exception:
        pass
    try:
        storage_backend.delete_result(
            job.get("result_storage_key"),
            job_id=job.get("id"),
        )
    except Exception:
        pass


def _editor_job(job_id: str, authorization: str | None) -> dict:
    job = _visible_job(job_id, authorization)
    owner = job.get("user_id")
    if owner:
        user_id = _require_user_id(authorization)
        if owner != user_id:
            raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    if job.get("status") != "completed" or not job.get("result_storage_key"):
        raise HTTPException(status_code=409, detail="This score isn’t ready to edit yet.")
    return job


def _read_original_musicxml(job: dict) -> str:
    storage_backend = storage_service.get_storage()
    return storage_backend.read_result_text(job["result_storage_key"])


def _read_edited_sidecar(job: dict, filename: str, *, text: bool = False):
    storage_backend = storage_service.get_storage()
    try:
        if storage_backend.backend == "local":
            path = Path(job["result_storage_key"]).with_name(filename)
            if not path.exists():
                return None
            return path.read_text(encoding="utf-8") if text else path.read_bytes()
        data = (
            storage_backend.read_result_text(filename)
            if text
            else storage_backend.read_result_bytes(filename)
        )
        return data
    except Exception:
        return None


def _write_edited_sidecars(job: dict, json_text: str, musicxml_text: str, midi_bytes: bytes) -> str:
    storage_backend = storage_service.get_storage()
    job_id = job["id"]
    keys = edited_keys(job_id)
    if storage_backend.backend == "local":
        parent = Path(job["result_storage_key"]).parent
        (parent / keys["json"]).write_text(json_text, encoding="utf-8")
        xml_path = parent / keys["musicxml"]
        xml_path.write_text(musicxml_text, encoding="utf-8")
        (parent / keys["midi"]).write_bytes(midi_bytes)
        return str(xml_path)
    storage_backend.save_text(keys["json"], json_text, content_type="application/json")
    storage_backend.save_text(
        keys["musicxml"],
        musicxml_text,
        content_type="application/vnd.recordare.musicxml+xml",
    )
    storage_backend.save_bytes(keys["midi"], midi_bytes, content_type="audio/midi")
    return keys["musicxml"]


def _edits_response(job: dict, model: dict, *, has_edits: bool | None = None) -> dict:
    return {
        "score_id": job.get("id"),
        "revision": int(job.get("edit_revision") or 0),
        "has_edits": bool(job.get("edited_result_storage_key"))
        if has_edits is None
        else has_edits,
        "tempo_bpm": model["tempo_bpm"],
        "time_signature": model["time_signature"],
        "notes": model["notes"],
    }


def _load_edit_model(job: dict) -> dict:
    raw = _read_edited_sidecar(job, f"{job['id']}.edits.json", text=True)
    if raw:
        return loads_edits(raw)
    return extract_from_musicxml(_read_original_musicxml(job))


class ScorePatch(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ClaimBody(BaseModel):
    token: str = Field(min_length=8, max_length=200)


class ClaimUnownedBody(BaseModel):
    job_ids: list[str] = Field(default_factory=list, max_length=40)


class ScoreNoteIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    pitch: int = Field(ge=0, le=127)
    start: float = Field(ge=0, le=10000)
    duration: float = Field(gt=0, le=32)
    velocity: int = Field(default=64, ge=1, le=127)
    track: int = Field(default=0, ge=0, le=3)


class ScoreEditsIn(BaseModel):
    revision: int = Field(ge=0)
    notes: list[ScoreNoteIn] = Field(max_length=4000)
    tempo_bpm: float | None = None
    time_signature: str | None = None


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
        "auth": {
            "jwt": bool(os.getenv("SUPABASE_JWT_SECRET") or os.getenv("SUPABASE_URL")),
        },
    }


@app.post("/upload", status_code=202)
async def upload(
    file: UploadFile = File(...),
    mode: str = Form("solo"),
    duration_seconds: str | None = Form(None),
    authorization: str | None = Header(default=None),
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

    owner_id = None
    if authorization:
        owner_id = _optional_user_id(authorization)
        if not owner_id:
            raise HTTPException(status_code=401, detail=SIGN_IN_DETAIL)

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
    filename = Path(file.filename).name
    claim_token = None if owner_id else new_claim_token()

    job = {
        "id": job_id,
        "status": "queued",
        "filename": filename,
        "content_type": file.content_type,
        "size_bytes": size,
        "storage_key": storage_key,
        "result_storage_key": None,
        "progress": 0,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "mode": resolved_mode,
        "user_id": owner_id,
        "title": title_from_filename(filename),
        "duration_seconds": _parse_duration(duration_seconds),
        "claim_token_hash": hash_claim_token(claim_token) if claim_token else None,
        "deleted_at": None,
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

    return public_job(job, claim_token=claim_token)


@app.get("/jobs")
def jobs_list(
    limit: int = 50,
    authorization: str | None = Header(default=None),
):
    user_id = _require_user_id(authorization)
    limit = max(1, min(limit, 200))
    jobs = db.list_jobs_for_user(user_id, limit)
    return [public_job(job) for job in jobs]


@app.get("/jobs/{job_id}")
def job_detail(
    job_id: str,
    authorization: str | None = Header(default=None),
):
    job = _visible_job(job_id, authorization)
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
def job_source(
    job_id: str,
    authorization: str | None = Header(default=None),
):
    """Original uploaded audio (or MIDI) for in-page preview."""
    job = _visible_job(job_id, authorization)

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
def job_result(
    job_id: str,
    format: str = "musicxml",
    authorization: str | None = Header(default=None),
):
    fmt = (format or "musicxml").lower()

    if fmt not in ("musicxml", "midi", "midi_score"):
        raise HTTPException(
            status_code=400,
            detail="Unsupported format. Use 'musicxml', 'midi', or 'midi_score'.",
        )

    job = _visible_job(job_id, authorization)

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

    edited_key = job.get("edited_result_storage_key")
    no_store = {"Cache-Control": "no-store"}

    if fmt == "musicxml":
        xml_key = edited_key or result_storage_key
        if storage_backend.backend == "local":
            return FileResponse(
                path=str(Path(xml_key)),
                media_type="application/vnd.recordare.musicxml+xml",
                filename=f"{stem}.musicxml",
                headers=no_store,
            )

        signed_url = storage_backend.get_result_signed_url(
            xml_key,
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
                    **no_store,
                },
            )
        # Older jobs: fall back to score MIDI derived from MusicXML.

    if fmt == "midi_score":
        edited_midi = _load_sidecar_midi_bytes(
            storage_backend, job_id, result_storage_key, f"{job_id}.edited.mid"
        )
        if edited_key and edited_midi:
            return Response(
                content=edited_midi,
                media_type="audio/midi",
                headers={
                    "Content-Disposition": f'attachment; filename="{stem}.score.mid"',
                    **no_store,
                },
            )
        score_bytes = _load_sidecar_midi_bytes(
            storage_backend, job_id, result_storage_key, f"{job_id}.score.mid"
        )
        if score_bytes:
            return Response(
                content=score_bytes,
                media_type="audio/midi",
                headers={
                    "Content-Disposition": f'attachment; filename="{stem}.score.mid"',
                    **no_store,
                },
            )

    # fmt == "midi_score" (or sidecars missing): derive from stored MusicXML.
    try:
        xml_key = edited_key or result_storage_key
        musicxml_text = storage_backend.read_result_text(xml_key)
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
            **no_store,
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


@app.post("/jobs/{job_id}/retry")
def job_retry(
    job_id: str,
    authorization: str | None = Header(default=None),
):
    job = _visible_job(job_id, authorization)
    if job.get("status") != "failed":
        raise HTTPException(
            status_code=409,
            detail="This score isn’t waiting to be retried.",
        )
    if not job.get("storage_key"):
        raise HTTPException(
            status_code=409,
            detail="The original recording is not available.",
        )

    from transcription import queue_timeout_for_mode

    db.update_job(job_id, status="queued", progress=0, error=None)
    try:
        queue_service.enqueue_job(
            job_id,
            job_timeout=queue_timeout_for_mode(job.get("mode") or "solo"),
        )
    except Exception as exc:
        db.update_job(job_id, status="failed", error="Failed to enqueue job")
        raise HTTPException(
            status_code=503,
            detail="Queue unavailable. Make sure Redis is running.",
        ) from exc

    return public_job(db.get_job(job_id))


@app.get("/scores")
def scores_list(
    limit: int = 100,
    authorization: str | None = Header(default=None),
):
    user_id = _require_user_id(authorization)
    limit = max(1, min(limit, 200))
    jobs = db.list_jobs_for_user(user_id, limit)
    return [public_job(job) for job in jobs]


@app.get("/scores/{score_id}")
def score_detail(
    score_id: str,
    authorization: str | None = Header(default=None),
):
    job = _visible_job(score_id, authorization)
    return public_job(job)


@app.get("/scores/{score_id}/edits")
def score_edits_get(
    score_id: str,
    authorization: str | None = Header(default=None),
):
    job = _visible_job(score_id, authorization)
    if job.get("status") != "completed" or not job.get("result_storage_key"):
        raise HTTPException(status_code=409, detail="This score isn’t ready to edit yet.")
    try:
        model = _load_edit_model(job)
    except EditError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not load this score for editing.",
        ) from exc
    return _edits_response(job, model)


@app.put("/scores/{score_id}/edits")
def score_edits_put(
    score_id: str,
    body: ScoreEditsIn,
    authorization: str | None = Header(default=None),
):
    job = _editor_job(score_id, authorization)
    current_revision = int(job.get("edit_revision") or 0)
    if body.revision != current_revision:
        raise HTTPException(
            status_code=409,
            detail="This score was updated elsewhere. Reload and try again.",
        )
    try:
        model = parse_edits_payload(body.model_dump())
        xml_text, midi_bytes = build_musicxml_and_midi(model)
        json_text = dumps_edits(model)
        edited_key = _write_edited_sidecars(job, json_text, xml_text, midi_bytes)
    except EditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Changes couldn't be saved.",
        ) from exc

    next_revision = current_revision + 1
    db.update_job(
        score_id,
        edited_result_storage_key=edited_key,
        edit_revision=next_revision,
    )
    job = db.get_job(score_id)
    return _edits_response(job, model, has_edits=True)


@app.post("/scores/{score_id}/edits/reset")
def score_edits_reset(
    score_id: str,
    authorization: str | None = Header(default=None),
):
    job = _editor_job(score_id, authorization)
    storage_backend = storage_service.get_storage()
    try:
        storage_backend.delete_edited(score_id, job.get("result_storage_key"))
    except Exception:
        pass
    next_revision = int(job.get("edit_revision") or 0) + 1
    db.update_job(
        score_id,
        edited_result_storage_key=None,
        edit_revision=next_revision,
    )
    job = db.get_job(score_id)
    try:
        model = extract_from_musicxml(_read_original_musicxml(job))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not restore the original score.",
        ) from exc
    return _edits_response(job, model, has_edits=False)


@app.patch("/scores/{score_id}")
def score_rename(
    score_id: str,
    body: ScorePatch,
    authorization: str | None = Header(default=None),
):
    user_id = _require_user_id(authorization)
    job = db.get_job(score_id)
    if not job or job.get("deleted_at") or job.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    db.update_job(score_id, title=sanitize_title(body.title))
    return public_job(db.get_job(score_id))


@app.delete("/scores/{score_id}")
def score_delete(
    score_id: str,
    authorization: str | None = Header(default=None),
):
    user_id = _require_user_id(authorization)
    job = db.get_job(score_id)
    if not job or job.get("deleted_at") or job.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    _delete_job_files(job)
    db.update_job(score_id, deleted_at=db.utcnow(), claim_token_hash=None)
    return {"ok": True}


@app.post("/scores/claim")
def score_claim(
    body: ClaimBody,
    authorization: str | None = Header(default=None),
):
    user_id = _require_user_id(authorization)
    job = db.get_job_by_claim_hash(hash_claim_token(body.token.strip()))
    if not job:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    owner = job.get("user_id")
    if owner and owner != user_id:
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    db.update_job(job["id"], user_id=user_id, claim_token_hash=None)
    return public_job(db.get_job(job["id"]))


@app.post("/scores/claim-unowned")
def score_claim_unowned(
    body: ClaimUnownedBody,
    authorization: str | None = Header(default=None),
):
    user_id = _require_user_id(authorization)
    claimed = []
    for job_id in body.job_ids[:40]:
        job = db.get_job(job_id)
        if not job or job.get("deleted_at"):
            continue
        owner = job.get("user_id")
        if owner and owner != user_id:
            continue
        if not owner:
            db.update_job(job_id, user_id=user_id, claim_token_hash=None)
        claimed.append(public_job(db.get_job(job_id)))
    return claimed
