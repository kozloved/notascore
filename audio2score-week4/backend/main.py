from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from contextlib import asynccontextmanager
from pathlib import Path
from pydantic import BaseModel, Field
import json
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
    extract_from_musicxml,
    extract_from_performance,
    loads_edits,
    dumps_edits,
    parse_edits_payload,
    time_map_from_tempo_payload,
)
from publishing import edit_bundle_keys, validate_revision_bundle

STALE_REVISION = "This score was updated elsewhere. Reload and try again."

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
    from adapters.mt3_backend import mt3_available
    from engine.flags import log_pipeline_configuration

    log_pipeline_configuration(mt3_configured=mt3_available())
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
    edited_key = job.get("edited_result_storage_key")
    if not edited_key:
        return None
    storage_backend = storage_service.get_storage()
    try:
        if storage_backend.backend == "local":
            path = Path(edited_key).with_name(filename)
            if not path.exists():
                return None
            return path.read_text(encoding="utf-8") if text else path.read_bytes()
        key = storage_backend.result_sidecar_key(edited_key, filename)
        data = (
            storage_backend.read_result_text(key)
            if text
            else storage_backend.read_result_bytes(key)
        )
        return data
    except Exception:
        return None


def _write_edited_sidecars(job: dict, json_text: str, musicxml_text: str, midi_bytes: bytes) -> str:
    extras = _overlay_derived_files(job)
    extras.update(
        {
            "json": json_text,
            "musicxml": musicxml_text,
            "midi": midi_bytes,
        }
    )
    return _write_revision_bundle(job, extras, require_complete=False)


def _overlay_derived_files(job: dict) -> dict[str, str | bytes]:
    """Copy notation sidecars from the currently published overlay, if any."""
    extras: dict[str, str | bytes] = {}
    mapping = {
        "notation_settings": f"{job['id']}.notation_settings.json",
        "decisions": f"{job['id']}.notation_decisions.json",
        "interpretation": f"{job['id']}.interpretation_context.json",
        "corrections": f"{job['id']}.corrections.json",
        "manifest": f"{job['id']}.revision.json",
    }
    for logical, filename in mapping.items():
        payload = _read_edited_sidecar(job, filename, text=True)
        if payload:
            extras[logical] = payload
    return extras


def _baseline_identity_sidecars(
    extras: dict[str, str | bytes],
    *,
    kind: str,
) -> dict[str, str]:
    """Label copied interpretation sidecars as baseline input, not this score."""
    updated: dict[str, str] = {}
    baseline = None
    settings_raw = extras.get("notation_settings")
    if isinstance(settings_raw, str) and settings_raw.strip():
        try:
            stored = json.loads(settings_raw)
        except Exception:
            stored = None
        if isinstance(stored, dict):
            baseline = (
                stored.get("output_identity")
                or stored.get("interpretation_context_digest")
                or stored.get("input_identity")
            )
            stored["identity_role"] = "baseline_input"
            stored["describes_published_score"] = False
            stored["baseline_output_identity"] = baseline
            updated["notation_settings"] = json.dumps(stored, indent=2)
    context_raw = extras.get("interpretation")
    if isinstance(context_raw, str) and context_raw.strip():
        try:
            context = json.loads(context_raw)
        except Exception:
            context = None
        if isinstance(context, dict):
            baseline = context.get("identity_digest") or baseline
    manifest_raw = extras.get("manifest")
    try:
        manifest = json.loads(manifest_raw) if isinstance(manifest_raw, str) and manifest_raw.strip() else {}
    except Exception:
        manifest = {}
    if not isinstance(manifest, dict):
        manifest = {}
    manifest.update(
        {
            "scope": "published_revision",
            "kind": kind,
            "output_artifacts": ["json", "musicxml", "midi", "corrections"],
            "baseline_interpretation_artifacts": [
                "notation_settings",
                "interpretation",
                "decisions",
            ],
            "describes_published_score": False,
            "baseline_output_identity": baseline,
        }
    )
    updated["manifest"] = json.dumps(manifest, indent=2)
    return updated


def _write_revision_bundle(
    job: dict,
    files: dict[str, str | bytes],
    *,
    require_complete: bool = True,
) -> str:
    """Write an unpublished edit bundle. Never touches the published pointer."""
    if require_complete:
        validate_revision_bundle(files)
    storage_backend = storage_service.get_storage()
    job_id = job["id"]
    bundle_id = uuid.uuid4().hex
    keys = edit_bundle_keys(job_id, bundle_id)
    content_types = {
        "json": "application/json",
        "musicxml": "application/vnd.recordare.musicxml+xml",
        "midi": "audio/midi",
        "notation_settings": "application/json",
        "decisions": "application/json",
        "interpretation": "application/json",
        "corrections": "application/json",
        "manifest": "application/json",
    }
    written: list[str] = []
    try:
        if storage_backend.backend == "local":
            parent = Path(job["result_storage_key"]).parent / f"{job_id}.edits" / bundle_id
            parent.mkdir(parents=True, exist_ok=True)
            xml_path = None
            for logical, payload in files.items():
                if logical not in keys or payload is None:
                    continue
                dest = parent / Path(keys[logical]).name
                if isinstance(payload, bytes):
                    dest.write_bytes(payload)
                else:
                    dest.write_text(payload if str(payload).endswith("\n") else str(payload) + "\n", encoding="utf-8")
                written.append(str(dest))
                if logical == "musicxml":
                    xml_path = dest
            if xml_path is None:
                raise ValueError("incomplete revision bundle: missing musicxml")
            return str(xml_path)
        musicxml_key = None
        for logical, payload in files.items():
            if logical not in keys or payload is None:
                continue
            ctype = content_types.get(logical, "application/octet-stream")
            if isinstance(payload, bytes):
                storage_backend.save_bytes(keys[logical], payload, content_type=ctype)
            else:
                storage_backend.save_text(keys[logical], payload, content_type=ctype)
            written.append(keys[logical])
            if logical == "musicxml":
                musicxml_key = keys[logical]
        if musicxml_key is None:
            raise ValueError("incomplete revision bundle: missing musicxml")
        return musicxml_key
    except Exception:
        try:
            if hasattr(storage_backend, "gc_edit_bundle") and written:
                storage_backend.gc_edit_bundle(written[0], job_id)
        except Exception:
            pass
        raise


def _conflict(code: str, message: str, **extra) -> HTTPException:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return HTTPException(status_code=409, detail=payload)


def _overlay_corrections(job: dict) -> tuple[list[dict] | None, str | None]:
    """Load explicit corrections from the published overlay.

    Returns (operations, error_message). error_message is set when the overlay
    exists but the correction bundle cannot be read.
    """
    ops, _uncorrected, error = _overlay_correction_sidecar(job)
    return ops, error


def _overlay_correction_sidecar(job: dict) -> tuple[list[dict] | None, dict, str | None]:
    if not job.get("edited_result_storage_key"):
        return [], {}, None
    raw = _read_edited_sidecar(job, f"{job['id']}.corrections.json", text=True)
    if raw is None:
        return None, {}, "Saved note corrections are missing from this revision."
    try:
        payload = json.loads(raw)
    except Exception:
        return None, {}, "Saved note corrections could not be read."
    from mir.notation_regen import NotationEditConflict, parse_corrections_sidecar

    try:
        ops, uncorrected = parse_corrections_sidecar(payload)
        return ops, uncorrected, None
    except NotationEditConflict as exc:
        return None, {}, str(exc)


def _performance_snapshot(job: dict):
    from mir.performance import PerformanceSnapshot
    from pathlib import Path as _Path
    import tempfile

    storage_backend = storage_service.get_storage()
    snap_bytes = _load_result_artifact_bytes(
        storage_backend, job["id"], job.get("result_storage_key"), f"{job['id']}.performance.json"
    )
    if not snap_bytes:
        return None
    with tempfile.NamedTemporaryFile(suffix=".json") as handle:
        handle.write(snap_bytes)
        handle.flush()
        return PerformanceSnapshot.read_json(_Path(handle.name))


def _edits_response(job: dict, model: dict, *, has_edits: bool | None = None) -> dict:
    if has_edits is None:
        ops, _err = _overlay_corrections(job) if job.get("edited_result_storage_key") else ([], None)
        has_edits = bool(ops)
    return {
        "score_id": job.get("id"),
        "revision": int(job.get("edit_revision") or 0),
        "has_edits": bool(has_edits),
        "tempo_bpm": model["tempo_bpm"],
        "time_signature": model["time_signature"],
        "tempo_curve": list(model.get("tempo_curve") or [{"beat": 0.0, "bpm": model["tempo_bpm"]}]),
        "printed_tempo_marks": list(model.get("printed_tempo_marks") or []),
        "provenance": model.get("provenance"),
        "notes": model["notes"],
    }


def _editor_notes_changed(submitted: dict, displayed: dict) -> bool:
    """True when the editor model changed timing or identity vs the current view."""
    current = {
        str(row.get("source_note_id") or row.get("id") or ""): row
        for row in (displayed or {}).get("notes") or []
        if row.get("source_note_id") or row.get("id")
    }
    incoming = {
        str(row.get("source_note_id") or row.get("id") or ""): row
        for row in (submitted or {}).get("notes") or []
        if row.get("source_note_id") or row.get("id")
    }
    if set(current) != set(incoming):
        return True
    for sid, row in incoming.items():
        other = current[sid]
        for field in ("pitch", "track", "voice", "velocity"):
            if row.get(field) is None and other.get(field) is None:
                continue
            if int(row.get(field) or 0) != int(other.get(field) or 0):
                return True
        for field in ("start", "duration"):
            if abs(float(row.get(field) or 0) - float(other.get(field) or 0)) > 1e-6:
                return True
    return False


def _read_result_sidecar(job: dict, filename: str, *, text: bool = False):
    storage_backend = storage_service.get_storage()
    result_key = job.get("result_storage_key")
    if not result_key:
        return None
    try:
        key = storage_backend.result_sidecar_key(result_key, filename)
        if storage_backend.backend == "local":
            path = Path(key)
            if not path.exists():
                return None
            return path.read_text(encoding="utf-8") if text else path.read_bytes()
        if hasattr(storage_backend, "result_exists") and not storage_backend.result_exists(key):
            return None
        return (
            storage_backend.read_result_text(key)
            if text
            else storage_backend.read_result_bytes(key)
        )
    except Exception:
        return None


def _load_edit_model(job: dict) -> dict:
    raw = _read_edited_sidecar(job, f"{job['id']}.edits.json", text=True)
    if raw:
        return loads_edits(raw)
    performance_raw = _read_result_sidecar(job, f"{job['id']}.performance.json", text=True)
    tempo_raw = _read_result_sidecar(job, f"{job['id']}.tempo.json", text=True)
    if performance_raw:
        import json as json_lib
        import tempfile

        from mir.performance import PerformanceSnapshot

        with tempfile.TemporaryDirectory() as tmp:
            snap_path = Path(tmp) / "performance.json"
            snap_path.write_text(performance_raw, encoding="utf-8")
            snapshot = PerformanceSnapshot.read_json(snap_path)
        if tempo_raw:
            tempo_payload = json_lib.loads(tempo_raw)
            time_map = time_map_from_tempo_payload(tempo_payload)
            printed = tempo_payload.get("printed_tempo") or []
            time_signature = "4/4"
            selected = tempo_payload.get("selected_meter")
            if isinstance(selected, str) and "/" in selected:
                time_signature = selected
            elif isinstance(selected, dict):
                ratio = selected.get("ratio") or selected.get("meter")
                if ratio:
                    time_signature = str(ratio)
            else:
                meter = (tempo_payload.get("meter_candidates") or [None])[0]
                if isinstance(meter, dict):
                    ratio = meter.get("ratio") or meter.get("meter")
                    if ratio:
                        time_signature = str(ratio)
                elif isinstance(meter, str) and "/" in meter:
                    time_signature = meter
        else:
            duration = max((note.end_sec for note in snapshot.notes), default=4.0)
            from timing.tempo_map import MusicalTimeMap

            time_map = MusicalTimeMap.from_bpm(120.0, duration_sec=max(duration, 1.0))
            printed = []
            time_signature = "4/4"
        return extract_from_performance(
            snapshot,
            time_map,
            printed_marks=printed,
            time_signature=time_signature,
        )
    return extract_from_musicxml(_read_original_musicxml(job))


class ScorePatch(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ClaimBody(BaseModel):
    token: str = Field(min_length=8, max_length=200)


class ClaimUnownedBody(BaseModel):
    job_ids: list[str] = Field(default_factory=list, max_length=40)


class ScoreNoteIn(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    pitch: int = Field(ge=0, le=127)
    start: float = Field(ge=0, le=10000)
    duration: float = Field(gt=0, le=32)
    velocity: int = Field(default=64, ge=1, le=127)
    track: int = Field(default=0, ge=0, le=3)
    voice: int = Field(default=0, ge=0, le=15)
    source_note_id: str | None = Field(default=None, max_length=128)
    start_sec: float | None = Field(default=None, ge=0, le=10000)
    end_sec: float | None = Field(default=None, ge=0, le=10000)


class TempoCurvePointIn(BaseModel):
    beat: float = Field(ge=0, le=10000)
    bpm: float = Field(ge=20, le=300)


class PrintedTempoMarkIn(BaseModel):
    beat: float = Field(ge=0, le=10000)
    bpm: float | None = Field(default=None, ge=20, le=300)
    mark: str = "metronome"
    reason: str = ""


class ScoreEditsIn(BaseModel):
    revision: int = Field(ge=0)
    notes: list[ScoreNoteIn] = Field(max_length=4000)
    tempo_bpm: float | None = None
    time_signature: str | None = None
    tempo_curve: list[TempoCurvePointIn] | None = Field(default=None, max_length=8192)
    printed_tempo_marks: list[PrintedTempoMarkIn] | None = None
    provenance: str | None = None


class ScoreResetIn(BaseModel):
    revision: int | None = Field(default=None, ge=0)


class NotationSettingsIn(BaseModel):
    display_grid: str | None = None
    triplet_policy: str | None = None
    interpretation: str | None = None
    syncopation: str | None = None
    overlap_handling: str | None = None
    max_dots: int | None = Field(default=None, ge=0, le=3)
    algorithm_version: str | None = None
    meter: str | None = None
    pickup_beats: float | None = Field(default=None, ge=0, le=16)
    first_downbeat_beat: float | None = Field(default=None, ge=0, le=10000)
    measure_overrides: list[dict] | None = None
    reset: bool = False
    revision: int | None = Field(default=None, ge=0)


@app.get("/health")
def health():
    from adapters.basic_pitch_backend import basic_pitch_settings
    from adapters.mt3_backend import mt3_status
    from audio_engine.beat_tracker import beat_status
    from engine.flags import nextgen_status
    from intelligence.config import gemini_status
    from mir.pipeline_config import (
        inspect_hand_separator_env,
        inspect_quantization_env,
        load_pipeline_config,
    )
    from mir.pm2s_hands import pm2s_status

    bp = basic_pitch_settings()
    mt3 = mt3_status()
    gemini = gemini_status()
    poly_available = bool(mt3["available"])
    hands = inspect_hand_separator_env()
    quant = inspect_quantization_env()
    try:
        cfg = load_pipeline_config()
        cfg_error = None
    except Exception as exc:
        print(f"[health] pipeline config fallback: {exc}", flush=True)
        from mir.pipeline_config import PipelineConfig

        cfg = PipelineConfig()
        cfg_error = str(exc)
    pipeline_config = {
        "valid": bool(hands["valid"] and quant["valid"] and cfg_error is None),
        "error": hands["error"] or quant["error"] or cfg_error,
        "warning": hands["warning"] or quant["warning"],
        "effective_hand_separator": hands["effective_hand_separator"],
        "requested_quantization_mode": quant["requested_quantization_mode"],
        "effective_quantization_mode": quant["effective_quantization_mode"],
        "quantization_mode_fallback": quant["quantization_mode_fallback"],
    }
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
        "requested_quantization_mode": (cfg.extra or {}).get(
            "requested_quantization_mode", cfg.quantization_mode.value
        ),
        "quantization_mode_fallback": (cfg.extra or {}).get("quantization_mode_fallback"),
        "hand_separator": cfg.hand_separator.value,
        "pipeline_config": pipeline_config,
        "enable_gemini": cfg.enable_gemini,
        "canonical": cfg.to_dict(),
        "basic_pitch": bp,
        "polyphonic": mt3,
        "quality": mt3,
        "gemini": gemini,
        "beat": beat_status(),
        "pm2s": pm2s_status(),
        "nextgen": nextgen_status(),
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
    from mir.types import MusicalEvent
    from notation_engine.integrity import score_attacks, validate_exports
    from notation_engine.playback import playback_score
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "score.musicxml"
        xml_path.write_text(musicxml_text, encoding="utf-8")

        score = converter.parse(str(xml_path))
        events = [MusicalEvent(a.pitch, a.start, a.end - a.start, velocity=a.velocity,
                               note_id=str(i), source_track_id=f"{a.track}:{a.voice}",
                               source_program=score.parts[a.track].getInstrument().midiProgram)
                  for i, a in enumerate(score_attacks(score))]
        signatures = list(score.recurse().getElementsByClass("TimeSignature"))
        signature = signatures[0].ratioString if signatures else "4/4"
        tempi = {float(m.getOffsetInHierarchy(score)): float(m.number)
                 for m in score.recurse().getElementsByClass("MetronomeMark")
                 if m.number is not None}
        playback = playback_score(events, signature, sorted(tempi.items()) or [(0, 120)])
        midi_path = Path(tmp) / "score.mid"
        playback.write("midi", fp=str(midi_path))
        validate_exports(xml_path, midi_path, events)

        return midi_path.read_bytes()


@app.get("/jobs/{job_id}/result")
def job_result(
    job_id: str,
    format: str = "musicxml",
    authorization: str | None = Header(default=None),
):
    fmt = (format or "musicxml").lower()
    published_formats = {
        "notation_settings": (f"{job_id}.notation_settings.json", "application/json"),
        "notation_decisions": (f"{job_id}.notation_decisions.json", "application/json"),
        "interpretation_context": (
            f"{job_id}.interpretation_context.json",
            "application/json",
        ),
        "revision": (f"{job_id}.revision.json", "application/json"),
        "manifest": (f"{job_id}.revision.json", "application/json"),
    }
    original_formats = {
        "fused_midi": (f"{job_id}.fused.mid", "audio/midi"),
        "fused_json": (f"{job_id}.fused.json", "application/json"),
        "original_manifest": (f"{job_id}.manifest.json", "application/json"),
        "provenance": (f"{job_id}.provenance.json", "application/json"),
        "tempo": (f"{job_id}.tempo.json", "application/json"),
    }
    extra_formats = {**original_formats, **published_formats}

    if fmt not in ("musicxml", "midi", "midi_score") and fmt not in extra_formats:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported format. Use 'musicxml', 'midi', 'midi_score', "
                "'fused_midi', 'fused_json', 'manifest', 'original_manifest', "
                "'provenance', 'tempo', 'notation_settings', "
                "'notation_decisions', 'interpretation_context', or 'revision'."
            ),
        )

    job = _visible_job(job_id, authorization)

    if job.get("status") != "completed":
        raise HTTPException(
            status_code=409,
            detail="Job is not completed yet",
        )

    try:
        from lifecycle import hold_job_artifacts

        hold_job_artifacts(job_id)
    except Exception:
        pass

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

    if fmt in extra_formats:
        filename, media_type = extra_formats[fmt]
        payload = None
        scope = "original"
        if fmt in published_formats and edited_key:
            overlay_name = filename
            payload = _read_edited_sidecar(job, overlay_name, text=False)
            if payload:
                scope = "published_revision"
        if not payload and fmt == "manifest":
            payload = _load_result_artifact_bytes(
                storage_backend, job_id, result_storage_key, f"{job_id}.manifest.json"
            )
            filename = f"{job_id}.manifest.json"
            scope = "original"
        if not payload:
            original_name = (
                f"{job_id}.manifest.json" if fmt == "original_manifest" else filename
            )
            payload = _load_result_artifact_bytes(
                storage_backend, job_id, result_storage_key, original_name
            )
            scope = "original"
        if not payload:
            raise HTTPException(status_code=404, detail=f"{filename} is not available")
        return Response(
            content=payload,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Nota-Artifact-Scope": scope,
                **no_store,
            },
        )

    if fmt == "musicxml":
        xml_key = edited_key or result_storage_key
        scope = "published_revision" if edited_key else "original"
        headers = {**no_store, "X-Nota-Artifact-Scope": scope}
        if storage_backend.backend == "local":
            return FileResponse(
                path=str(Path(xml_key)),
                media_type="application/vnd.recordare.musicxml+xml",
                filename=f"{stem}.musicxml",
                headers=headers,
            )

        signed_url = None
        try:
            signed_url = storage_backend.get_result_signed_url(
                xml_key,
                expires_in=3600,
            )
        except Exception:
            signed_url = None

        if signed_url:
            return RedirectResponse(signed_url)

        try:
            payload = storage_backend.read_result_bytes(xml_key)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="Failed to generate download URL",
            ) from exc
        return Response(
            content=payload,
            media_type="application/vnd.recordare.musicxml+xml",
            headers={
                "Content-Disposition": f'attachment; filename="{stem}.musicxml"',
                "X-Nota-Artifact-Scope": scope,
                **no_store,
            },
        )

    if fmt == "midi":
        raw_bytes = _load_result_artifact_bytes(
            storage_backend, job_id, result_storage_key, f"{job_id}.raw.mid"
        )
        if raw_bytes:
            return Response(
                content=raw_bytes,
                media_type="audio/midi",
                headers={
                    "Content-Disposition": f'attachment; filename="{stem}.mid"',
                    "X-Nota-Artifact-Scope": "original",
                    **no_store,
                },
            )
        # Older jobs: fall back to score MIDI derived from MusicXML.

    if fmt == "midi_score":
        edited_midi = None
        if edited_key:
            edited_midi = _load_result_artifact_bytes(
                storage_backend, job_id, edited_key, f"{job_id}.edited.mid"
            )
        if edited_key and edited_midi:
            return Response(
                content=edited_midi,
                media_type="audio/midi",
                headers={
                    "Content-Disposition": f'attachment; filename="{stem}.score.mid"',
                    "X-Nota-Artifact-Scope": "published_revision",
                    **no_store,
                },
            )
        score_bytes = _load_result_artifact_bytes(
            storage_backend, job_id, result_storage_key, f"{job_id}.score.mid"
        )
        if score_bytes:
            return Response(
                content=score_bytes,
                media_type="audio/midi",
                headers={
                    "Content-Disposition": f'attachment; filename="{stem}.score.mid"',
                    "X-Nota-Artifact-Scope": "original",
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
            "X-Nota-Artifact-Scope": "published_revision" if edited_key else "original",
            **no_store,
        },
    )


def _load_result_artifact_bytes(
    storage_backend, job_id: str, result_storage_key: str, filename: str
):
    """Read a job result object via the storage backend (local path or remote key)."""
    try:
        key = storage_backend.result_sidecar_key(result_storage_key, filename)
        if hasattr(storage_backend, "result_exists") and not storage_backend.result_exists(key):
            return None
        return storage_backend.read_result_bytes(key)
    except Exception:
        return None


@app.get("/jobs/{job_id}/artifacts")
def job_artifacts(
    job_id: str,
    authorization: str | None = Header(default=None),
):
    job = _visible_job(job_id, authorization)
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Job is not completed yet")
    result_storage_key = job.get("result_storage_key")
    if not result_storage_key:
        raise HTTPException(status_code=404, detail="Result not available")
    from engine.sidecars import list_job_artifacts

    storage_backend = storage_service.get_storage()
    original = list_job_artifacts(job_id, result_storage_key, storage_backend)
    for row in original:
        row.setdefault("scope", "original")
    overlay = []
    edited_key = job.get("edited_result_storage_key")
    if edited_key:
        overlay_names = (
            f"{job_id}.notation_settings.json",
            f"{job_id}.notation_decisions.json",
            f"{job_id}.interpretation_context.json",
            f"{job_id}.revision.json",
            f"{job_id}.corrections.json",
        )
        for name in overlay_names:
            payload = _read_edited_sidecar(job, name, text=False)
            if not payload:
                continue
            overlay.append(
                {
                    "filename": name,
                    "name": name,
                    "content_type": "application/json",
                    "scope": "published_revision",
                    "bytes": len(payload),
                }
            )
    return {
        "job_id": job_id,
        "artifacts": overlay + original,
    }


@app.get("/jobs/{job_id}/artifacts/{filename:path}")
def job_artifact_file(
    job_id: str,
    filename: str,
    authorization: str | None = Header(default=None),
):
    job = _visible_job(job_id, authorization)
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Job is not completed yet")
    result_storage_key = job.get("result_storage_key")
    if not result_storage_key:
        raise HTTPException(status_code=404, detail="Result not available")
    from engine.sidecars import resolve_job_artifact

    storage_backend = storage_service.get_storage()
    published_names = {
        f"{job_id}.notation_settings.json",
        f"{job_id}.notation_decisions.json",
        f"{job_id}.interpretation_context.json",
        f"{job_id}.revision.json",
        f"{job_id}.corrections.json",
        f"{job_id}.edits.json",
        f"{job_id}.edited.musicxml",
        f"{job_id}.edited.mid",
    }
    name = Path(filename).name
    if name in published_names and job.get("edited_result_storage_key"):
        payload = _read_edited_sidecar(job, name, text=False)
        if payload:
            media = (
                "application/vnd.recordare.musicxml+xml"
                if name.endswith(".musicxml")
                else "audio/midi"
                if name.endswith(".mid")
                else "application/json"
            )
            return Response(
                content=payload,
                media_type=media,
                headers={
                    "Content-Disposition": f'attachment; filename="{name}"',
                    "Cache-Control": "no-store",
                    "X-Nota-Artifact-Scope": "published_revision",
                },
            )
    resolved = resolve_job_artifact(job_id, result_storage_key, filename, storage_backend)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Artifact not available")
    key, media, download_name = resolved
    if storage_backend.backend == "local":
        path = Path(key)
        if path.is_file():
            return FileResponse(
                path=str(path),
                media_type=media,
                filename=download_name,
                headers={
                    "Cache-Control": "no-store",
                    "X-Nota-Artifact-Scope": "original",
                },
            )
    try:
        payload = storage_backend.read_result_bytes(key)
    except Exception:
        payload = None
    if not payload:
        raise HTTPException(status_code=404, detail="Artifact not available")
    return Response(
        content=payload,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
            "Cache-Control": "no-store",
            "X-Nota-Artifact-Scope": "original",
        },
    )


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
        raise _conflict("stale_revision", STALE_REVISION)
    try:
        from mir.notation_regen import (
            NotationEditConflict,
            baseline_uncorrected,
            extract_corrections,
        )

        model = parse_edits_payload(body.model_dump())
        xml_text, midi_bytes = build_musicxml_and_midi(model)
        json_text = dumps_edits(model)
        snapshot = _performance_snapshot(job)
        displayed = _load_edit_model(job)
        existing_ops: list[dict] = []
        stored_uncorrected: dict = {}
        if job.get("edited_result_storage_key"):
            existing_ops, stored_uncorrected, corr_error = _overlay_correction_sidecar(job)
            if corr_error:
                raise _conflict("edit_conflict", corr_error)
            existing_ops = existing_ops or []
        uncorrected = baseline_uncorrected(
            displayed=displayed,
            existing_ops=existing_ops,
            snapshot=snapshot,
            stored=stored_uncorrected,
        )
        ops = extract_corrections(
            model,
            snapshot=snapshot,
            displayed=displayed,
            uncorrected=uncorrected,
            existing=existing_ops,
        )
        extras = _overlay_derived_files(job)
        extras.update(
            {
                "json": json_text,
                "musicxml": xml_text,
                "midi": midi_bytes,
                "corrections": json.dumps(
                    {"operations": ops, "uncorrected": uncorrected},
                    indent=2,
                ),
            }
        )
        extras.update(_baseline_identity_sidecars(extras, kind="note_edits"))
        edited_key = _write_revision_bundle(job, extras, require_complete=False)
        note_changed = _editor_notes_changed(model, displayed)
    except HTTPException:
        raise
    except NotationEditConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "edit_conflict", "message": str(exc)}) from exc
    except EditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Changes couldn't be saved.",
        ) from exc

    next_revision = current_revision + 1
    previous_key = job.get("edited_result_storage_key")
    published = db.cas_update_job(
        score_id,
        expected={"edit_revision": current_revision},
        edited_result_storage_key=edited_key,
        edit_revision=next_revision,
    )
    storage_backend = storage_service.get_storage()
    if not published:
        try:
            if hasattr(storage_backend, "gc_edit_bundle"):
                storage_backend.gc_edit_bundle(edited_key, score_id)
        except Exception:
            pass
        raise _conflict("stale_revision", STALE_REVISION)
    try:
        from lifecycle import schedule_edit_bundle_gc, sweep_artifact_gc

        schedule_edit_bundle_gc(score_id, previous_key, keep_key=edited_key)
        sweep_artifact_gc(storage_backend)
    except Exception:
        pass
    job = dict(job, edit_revision=next_revision, edited_result_storage_key=edited_key)
    return _edits_response(job, model, has_edits=bool(ops) or note_changed)


@app.post("/scores/{score_id}/edits/reset")
def score_edits_reset(
    score_id: str,
    body: ScoreResetIn | None = None,
    authorization: str | None = Header(default=None),
):
    job = _editor_job(score_id, authorization)
    previous_key = job.get("edited_result_storage_key")
    current_revision = int(job.get("edit_revision") or 0)
    expected_revision = current_revision
    if body is not None and body.revision is not None:
        expected_revision = int(body.revision)
        if expected_revision != current_revision:
            raise _conflict("stale_revision", STALE_REVISION)
    settings_raw = _read_edited_sidecar(job, f"{score_id}.notation_settings.json", text=True)
    if settings_raw:
        try:
            stored = json.loads(settings_raw)
            from mir.notation_settings import parse_notation_settings

            settings = parse_notation_settings(stored.get("notation_settings") or stored)
            payload = _recompute_notation_revision(
                job,
                settings,
                corrections=[],
                revision=expected_revision,
                kind="reset_corrections",
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail="Could not restore the score without note corrections.",
            ) from exc
        return _edits_response(
            dict(job, edit_revision=payload["edit_revision"], edited_result_storage_key=payload["edited_key"]),
            payload["editor_model"],
            has_edits=False,
        )
    restored_job = dict(job, edited_result_storage_key=None, edit_revision=current_revision + 1)
    try:
        model = _load_edit_model(restored_job)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not restore the original score.",
        ) from exc
    published = db.cas_update_job(
        score_id,
        expected={"edit_revision": expected_revision},
        edited_result_storage_key=None,
        edit_revision=expected_revision + 1,
    )
    if not published:
        raise _conflict("stale_revision", STALE_REVISION)
    storage_backend = storage_service.get_storage()
    try:
        from lifecycle import schedule_edit_bundle_gc, sweep_artifact_gc

        schedule_edit_bundle_gc(score_id, previous_key)
        sweep_artifact_gc(storage_backend)
    except Exception:
        pass
    restored_job = dict(job, edited_result_storage_key=None, edit_revision=expected_revision + 1)
    return _edits_response(restored_job, model, has_edits=False)


def _recompute_notation_revision(
    job: dict,
    settings,
    *,
    corrections: list[dict],
    revision: int,
    kind: str,
    prior_decisions=None,
    explicit_pickup: bool = False,
):
    import json as json_mod

    from mir.interpretation_context import (
        FALLBACK_MISSING,
        InterpretationContextError,
        load_context_payload,
    )
    from mir.notation_regen import NotationEditConflict, recompute_notation
    from score_edits import dumps_edits

    job_id = job["id"]
    storage_backend = storage_service.get_storage()
    result_key = job.get("result_storage_key")
    raw_midi = _load_result_artifact_bytes(
        storage_backend, job_id, result_key, f"{job_id}.raw.mid"
    )
    if not raw_midi:
        raise _conflict(
            "missing_context",
            "Original performance MIDI is not available for reinterpretation.",
        )
    performance = _performance_snapshot(job)
    published_context = None
    if kind != "reset_interpretation":
        published_context = _read_edited_sidecar(
            job, f"{job_id}.interpretation_context.json", text=False
        )
    if not published_context:
        published_context = _load_result_artifact_bytes(
            storage_backend, job_id, result_key, f"{job_id}.interpretation_context.json"
        )
    tempo_bytes = _load_result_artifact_bytes(
        storage_backend, job_id, result_key, f"{job_id}.tempo.json"
    )
    tempo_payload = None
    if tempo_bytes:
        try:
            tempo_payload = json_mod.loads(tempo_bytes.decode("utf-8"))
        except Exception:
            tempo_payload = None
    try:
        context, context_status = load_context_payload(
            published_context,
            tempo_payload=tempo_payload,
            midi_sha256=getattr(performance, "midi_sha256", None),
            source_backend=getattr(performance, "source_backend", "") or "",
        )
    except InterpretationContextError as exc:
        raise _conflict("missing_context", str(exc)) from exc
    if context is None and context_status == FALLBACK_MISSING:
        raise _conflict(
            "missing_context",
            "This score is missing production interpretation context. "
            "Refusing to silently re-estimate tempo from raw MIDI.",
        )
    layout_prior = None
    if context is None or getattr(context, "fallback", None):
        debug_bytes = _load_result_artifact_bytes(
            storage_backend, job_id, result_key, f"{job_id}.debug.json"
        )
        if debug_bytes:
            try:
                debug = json_mod.loads(debug_bytes.decode("utf-8"))
                extra = debug.get("extra") or debug
                rows = extra.get("quantization_decisions")
                if isinstance(rows, list):
                    layout_prior = rows
            except Exception:
                layout_prior = None
        if prior_decisions:
            layout_prior = prior_decisions
    try:
        result = recompute_notation(
            midi_bytes=raw_midi,
            settings=settings,
            performance=performance,
            prior_decisions=layout_prior,
            context=context,
            corrections=corrections,
            fallback=context_status,
            explicit_pickup=explicit_pickup,
        )
    except NotationEditConflict as exc:
        raise HTTPException(
            status_code=409, detail={"code": "edit_conflict", "message": str(exc)}
        ) from exc
    except InterpretationContextError as exc:
        raise _conflict("invalid_selection", str(exc)) from exc
    editor_model = result.editor_model or {
        "notes": [],
        "tempo_bpm": 120,
        "time_signature": "4/4",
    }
    context_digest = result.output_identity or (
        result.context.identity_digest() if result.context else None
    )
    settings_json = json_mod.dumps(
        {
            "notation_settings": result.settings.to_dict(),
            "algorithm_version": result.settings.algorithm_version,
            "notation_cache_key": result.cache_key,
            "midi_sha256": result.midi_sha256,
            "fallback": result.fallback,
            "policy_exceptions": result.policy_exceptions,
            "interpretation_context_digest": context_digest,
            "input_identity": result.input_identity,
            "output_identity": result.output_identity,
            "identity_role": "regenerated_output",
            "describes_published_score": True,
            "corrections_digest": result.edits_digest,
        },
        indent=2,
    )
    if (
        result.context is not None
        and result.output_identity
        and result.output_identity != result.context.identity_digest()
    ):
        raise _conflict(
            "missing_context",
            "Output interpretation identity does not match the stored context.",
        )
    if result.cache_key != result.settings.cache_key(
        result.midi_sha256,
        context_digest=result.input_identity,
        edits_digest=result.edits_digest,
    ):
        raise _conflict(
            "missing_context",
            "Notation cache identity does not match the input interpretation.",
        )
    decisions_json = json_mod.dumps(
        {"quantization_decisions": result.decisions, "quantization_summary": result.summary},
        indent=2,
        default=str,
    )
    context_json = (
        json_mod.dumps(result.context.to_dict(), indent=2, default=str)
        if result.context
        else None
    )
    corrections_json = json_mod.dumps(
        {"operations": list(corrections or []), "uncorrected": result.uncorrected or {}},
        indent=2,
    )
    manifest_json = json_mod.dumps(
        {
            "scope": "published_revision",
            "kind": kind,
            "job_id": job_id,
            "has_note_corrections": bool(corrections),
            "interpretation_context_digest": context_digest,
            "input_identity": result.input_identity,
            "output_identity": result.output_identity,
            "identity_role": "regenerated_output",
            "describes_published_score": True,
            "corrections_digest": result.edits_digest,
            "original_result_labeled": True,
        },
        indent=2,
    )
    bundle_files = {
        "json": dumps_edits(editor_model),
        "musicxml": result.musicxml,
        "midi": result.score_midi,
        "notation_settings": settings_json,
        "decisions": decisions_json,
        "corrections": corrections_json,
        "manifest": manifest_json,
    }
    if context_json:
        bundle_files["interpretation"] = context_json
    try:
        edited_key = _write_revision_bundle(job, bundle_files, require_complete=True)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not store the regenerated score.",
        ) from exc
    previous_key = job.get("edited_result_storage_key")
    published = db.cas_update_job(
        job_id,
        expected={"edit_revision": revision},
        edited_result_storage_key=edited_key,
        edit_revision=revision + 1,
    )
    if not published:
        try:
            if hasattr(storage_backend, "gc_edit_bundle"):
                storage_backend.gc_edit_bundle(edited_key, job_id)
        except Exception:
            pass
        raise _conflict("stale_revision", STALE_REVISION)
    try:
        from lifecycle import schedule_edit_bundle_gc, sweep_artifact_gc

        schedule_edit_bundle_gc(job_id, previous_key, keep_key=edited_key)
        sweep_artifact_gc(storage_backend)
    except Exception:
        pass
    return {
        "edit_revision": revision + 1,
        "edited_key": edited_key,
        "result": result,
        "editor_model": editor_model,
        "has_edits": bool(corrections),
    }


def _notation_settings_payload(job: dict) -> dict:
    from mir.notation_settings import default_notation_settings

    settings = default_notation_settings()
    stored = None
    raw = _read_edited_sidecar(job, f"{job['id']}.notation_settings.json", text=True)
    if not raw and job.get("result_storage_key"):
        storage_backend = storage_service.get_storage()
        blob = _load_result_artifact_bytes(
            storage_backend,
            job["id"],
            job["result_storage_key"],
            f"{job['id']}.notation_settings.json",
        )
        raw = blob.decode("utf-8") if blob else None
    if raw:
        try:
            stored = json.loads(raw)
            from mir.notation_settings import parse_notation_settings

            settings = parse_notation_settings(stored.get("notation_settings") or stored)
            return {
                "notation_settings": settings.to_dict(),
                "algorithm_version": settings.algorithm_version,
                "notation_cache_key": stored.get("notation_cache_key") or settings.cache_key(),
                "midi_sha256": stored.get("midi_sha256"),
                "fallback": stored.get("fallback"),
                "policy_exceptions": stored.get("policy_exceptions") or [],
                "has_edits": bool(_overlay_corrections(job)[0]),
            }
        except Exception:
            pass
    return {
        "notation_settings": settings.to_dict(),
        "algorithm_version": settings.algorithm_version,
        "notation_cache_key": settings.cache_key(),
        "midi_sha256": None,
        "fallback": None,
        "policy_exceptions": [],
        "has_edits": bool(_overlay_corrections(job)[0]) if job.get("edited_result_storage_key") else False,
    }


@app.get("/jobs/{job_id}/notation-settings")
def job_notation_settings_get(
    job_id: str,
    authorization: str | None = Header(default=None),
):
    job = _visible_job(job_id, authorization)
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Job is not completed yet")
    return _notation_settings_payload(job)


@app.post("/jobs/{job_id}/notation-settings")
def job_notation_settings_post(
    job_id: str,
    body: NotationSettingsIn,
    authorization: str | None = Header(default=None),
):
    """Recompute derived notation. Does not resubmit audio transcription."""
    from mir.notation_settings import (
        NotationSettingsError,
        merge_notation_settings,
        settings_for_reset,
    )

    job = _editor_job(job_id, authorization)
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Job is not completed yet")
    current_revision = int(job.get("edit_revision") or 0)
    if body.revision is not None and int(body.revision) != current_revision:
        raise _conflict("stale_revision", STALE_REVISION)
    corrections, corr_error = _overlay_corrections(job)
    if corr_error:
        raise _conflict("edit_conflict", corr_error)
    fields_set = set(getattr(body, "model_fields_set", None) or getattr(body, "__fields_set__", set()))
    if hasattr(body, "model_dump"):
        dumped = body.model_dump(exclude_unset=True)
    else:
        dumped = body.dict(exclude_unset=True)
    explicit_pickup = (not body.reset) and (
        "pickup_beats" in fields_set or "first_downbeat_beat" in fields_set
    )
    try:
        if body.reset:
            settings = settings_for_reset()
        else:
            current = _notation_settings_payload(job)["notation_settings"]
            settings = merge_notation_settings(current, dumped, fields_set=fields_set)
        payload = _recompute_notation_revision(
            job,
            settings,
            corrections=corrections or [],
            revision=current_revision,
            kind="reset_interpretation" if body.reset else "notation",
            explicit_pickup=explicit_pickup,
        )
    except HTTPException:
        raise
    except NotationSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Could not recompute notation from the original performance.",
        ) from exc
    result = payload["result"]
    return {
        "job_id": job_id,
        "transcribed": False,
        "edit_revision": payload["edit_revision"],
        "has_edits": payload["has_edits"],
        "notation_settings": result.settings.to_dict(),
        "algorithm_version": result.settings.algorithm_version,
        "notation_cache_key": result.cache_key,
        "midi_sha256": result.midi_sha256,
        "source_note_count": result.source_note_count,
        "fallback": result.fallback,
        "policy_exceptions": result.policy_exceptions,
    }


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
