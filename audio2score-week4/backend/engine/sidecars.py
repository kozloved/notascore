"""Job sidecar filenames and storage-backed artifact access."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from engine.artifacts import ArtifactKind, ArtifactManifest, ArtifactRef
from separation.base import ALLOWED_STEMS

CORE_SIDECARS = (
    ("raw.mid", "audio/midi"),
    ("validated.mid", "audio/midi"),
    ("score.mid", "audio/midi"),
    ("fused.mid", "audio/midi"),
    ("musicxml", "application/vnd.recordare.musicxml+xml"),
    ("tempo.json", "application/json"),
    ("performance.json", "application/json"),
    ("fused.json", "application/json"),
    ("fusion.json", "application/json"),
    ("provenance.json", "application/json"),
    ("manifest.json", "application/json"),
    ("debug.json", "application/json"),
    ("interpretation.json", "application/json"),
)

_CONTENT_TYPES = {
    ".mid": "audio/midi",
    ".midi": "audio/midi",
    ".wav": "audio/wav",
    ".json": "application/json",
    ".musicxml": "application/vnd.recordare.musicxml+xml",
    ".xml": "application/vnd.recordare.musicxml+xml",
}


def job_work_dir(source: str | Path, job_id: str) -> Path:
    return Path(source).parent / f"bp_{job_id}"


def result_object_key(path: str | Path) -> str:
    """Uploaded result key. Production uses flat `{filename}` object names."""
    return Path(path).name


def extra_result_files(out_dir: str | Path, job_id: str) -> list[Path]:
    """Sidecars to upload besides MusicXML / raw / validated / score MIDI."""
    root = Path(out_dir)
    names = (
        f"{job_id}.fused.mid",
        f"{job_id}.fused.json",
        f"{job_id}.fusion.json",
        f"{job_id}.manifest.json",
        f"{job_id}.provenance.json",
        f"{job_id}.tempo.json",
        f"{job_id}.performance.json",
        f"{job_id}.debug.json",
        f"{job_id}.interpretation.json",
        f"{job_id}_norm.wav",
    )
    found = [root / name for name in names if (root / name).exists()]
    found.extend(sorted(p for p in root.glob(f"{job_id}.stem.*") if p.is_file()))
    found.extend(sorted(p for p in root.glob(f"{job_id}.raw.*.mid") if p.is_file()))
    return found


def content_type_for_filename(filename: str) -> str:
    name = Path(filename).name
    suffix = Path(name).suffix.lower()
    if name.endswith(".musicxml"):
        return "application/vnd.recordare.musicxml+xml"
    return _CONTENT_TYPES.get(suffix, "application/octet-stream")


def sanitize_artifact_filename(job_id: str, filename: str) -> str | None:
    """Reject path traversal and anything outside this job's namespace."""
    if filename is None:
        return None
    raw = unquote(str(filename)).replace("\\", "/")
    if unquote(raw) != raw:
        raw = unquote(raw)
    if not raw or "\x00" in raw:
        return None
    if raw.startswith("/") or raw.startswith("~"):
        return None
    parts = [part for part in raw.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        return None
    if len(parts) != 1:
        return None
    name = Path(parts[0]).name
    if name != parts[0] or name in {".", ".."}:
        return None
    if not _belongs_to_job(job_id, name):
        return None
    return name


def _belongs_to_job(job_id: str, filename: str) -> bool:
    return filename.startswith(f"{job_id}.") or filename == f"{job_id}_norm.wav"


def public_artifact_descriptor(ref: ArtifactRef, *, job_id: str = "") -> dict:
    filename = Path(ref.storage_key or ref.path).name
    if not filename or filename in {".", ".."}:
        filename = result_object_key(ref.path) if ref.path else ""
    return {
        "id": ref.artifact_id,
        "kind": ref.kind.value if isinstance(ref.kind, ArtifactKind) else str(ref.kind),
        "name": filename,
        "filename": filename,
        "storage_key": filename,
        "content_type": ref.content_type or content_type_for_filename(filename),
        "stem_id": ref.stem_id or "",
        "instrument": ref.instrument or "",
        "sha256": ref.sha256,
        "bytes": ref.bytes,
        "source_stage": ref.source_stage or "",
        "source_model": ref.source_model or ref.model or "",
        "model": ref.model or "",
        "model_version": ref.model_version or "",
    }


def load_job_manifest(job_id: str, result_storage_key: str, storage) -> ArtifactManifest | None:
    filename = f"{job_id}.manifest.json"
    try:
        key = storage.result_sidecar_key(result_storage_key, filename)
        if not storage.result_exists(key):
            return None
        return ArtifactManifest.from_json(storage.read_result_bytes(key))
    except Exception:
        return None


def list_job_artifacts(job_id: str, result_storage_key: str, storage) -> list[dict]:
    """API-safe descriptors. Never includes absolute filesystem paths."""
    manifest = load_job_manifest(job_id, result_storage_key, storage)
    if manifest is not None and manifest.artifacts:
        rows = [
            public_artifact_descriptor(ref, job_id=job_id)
            for ref in manifest.artifacts
            if Path(ref.storage_key or ref.path).name
            and _belongs_to_job(job_id, Path(ref.storage_key or ref.path).name)
        ]
        manifest_name = f"{job_id}.manifest.json"
        if not any(row["filename"] == manifest_name for row in rows):
            rows.append(_manifest_descriptor(job_id, result_storage_key, storage))
        return [row for row in rows if row.get("filename")]
    return _legacy_probe(job_id, result_storage_key, storage)


def resolve_job_artifact(
    job_id: str, result_storage_key: str, filename: str, storage
) -> tuple[str, str, str] | None:
    """Return (storage_key, content_type, download_name) if the file is allowed."""
    name = sanitize_artifact_filename(job_id, filename)
    if name is None:
        return None
    manifest = load_job_manifest(job_id, result_storage_key, storage)
    allowed: set[str] = set()
    content_types: dict[str, str] = {}
    if manifest is not None and manifest.artifacts:
        for ref in manifest.artifacts:
            listed = Path(ref.storage_key or ref.path).name
            if not listed or not _belongs_to_job(job_id, listed):
                continue
            allowed.add(listed)
            content_types[listed] = ref.content_type or content_type_for_filename(listed)
        allowed.add(f"{job_id}.manifest.json")
        if name not in allowed:
            return None
    elif not _belongs_to_job(job_id, name):
        return None
    key = storage.result_sidecar_key(result_storage_key, name)
    if not storage.result_exists(key):
        return None
    media = content_types.get(name) or content_type_for_filename(name)
    return key, media, name


def list_job_sidecars(result_storage_key: str, job_id: str) -> list[dict]:
    """Backward-compatible local filesystem listing used by older callers."""
    from storage import LocalStorage

    return list_job_artifacts(job_id, result_storage_key, LocalStorage())


def sidecar_path(result_storage_key: str, job_id: str, filename: str) -> Path | None:
    """Local-only helper. Prefer resolve_job_artifact for API routes."""
    name = sanitize_artifact_filename(job_id, filename)
    if name is None:
        return None
    path = Path(result_storage_key).parent / name
    if path.exists() and path.is_file():
        return path
    return None


def _manifest_descriptor(job_id: str, result_storage_key: str, storage) -> dict:
    filename = f"{job_id}.manifest.json"
    key = storage.result_sidecar_key(result_storage_key, filename)
    size = None
    try:
        if storage.result_exists(key):
            size = len(storage.read_result_bytes(key))
    except Exception:
        size = None
    return {
        "id": f"{ArtifactKind.MANIFEST_JSON.value}:default:{job_id}",
        "kind": ArtifactKind.MANIFEST_JSON.value,
        "name": filename,
        "filename": filename,
        "storage_key": filename,
        "content_type": "application/json",
        "stem_id": "",
        "instrument": "",
        "sha256": None,
        "bytes": size,
        "source_stage": "",
        "source_model": "",
        "model": "",
        "model_version": "",
    }


def _legacy_probe(job_id: str, result_storage_key: str, storage) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    candidates = [f"{job_id}.{suffix}" for suffix, _ctype in CORE_SIDECARS]
    candidates.append(f"{job_id}_norm.wav")
    for stem_id in ALLOWED_STEMS:
        candidates.append(f"{job_id}.stem.{stem_id}.wav")
        candidates.append(f"{job_id}.raw.{stem_id}.mid")
    for name in candidates:
        if name in seen:
            continue
        key = storage.result_sidecar_key(result_storage_key, name)
        try:
            exists = storage.result_exists(key)
        except Exception:
            exists = False
        if not exists:
            continue
        seen.add(name)
        size = None
        try:
            size = len(storage.read_result_bytes(key))
        except Exception:
            size = None
        kind = "stem" if ".stem." in name else ("stem_midi" if ".raw." in name and name.endswith(".mid") and name != f"{job_id}.raw.mid" else Path(name).name[len(job_id) + 1 :])
        stem_id = ""
        if ".stem." in name:
            stem_id = name.split(".stem.", 1)[-1].rsplit(".", 1)[0]
            kind = "stem"
        elif name.startswith(f"{job_id}.raw.") and name.endswith(".mid") and name != f"{job_id}.raw.mid":
            stem_id = name[len(job_id) + 5 : -4]
            kind = "stem_midi"
        rows.append(
            {
                "id": f"{kind}:{stem_id or 'default'}:{name}",
                "kind": kind,
                "name": name,
                "filename": name,
                "storage_key": name,
                "content_type": content_type_for_filename(name),
                "stem_id": stem_id,
                "instrument": stem_id,
                "sha256": None,
                "bytes": size,
                "source_stage": "",
                "source_model": "",
                "model": "",
                "model_version": "",
            }
        )
    if getattr(storage, "backend", "") == "local" and result_storage_key:
        folder = Path(result_storage_key).parent
        if folder.is_dir():
            for path in sorted(folder.glob(f"{job_id}.stem.*")):
                if path.name in seen or not path.is_file():
                    continue
                seen.add(path.name)
                stem_id = path.name.split(".stem.", 1)[-1].rsplit(".", 1)[0]
                rows.append(
                    {
                        "id": f"stem:{stem_id}:{path.name}",
                        "kind": "stem",
                        "name": path.name,
                        "filename": path.name,
                        "storage_key": path.name,
                        "content_type": content_type_for_filename(path.name),
                        "stem_id": stem_id,
                        "instrument": stem_id,
                        "sha256": None,
                        "bytes": path.stat().st_size,
                        "source_stage": "",
                        "source_model": "",
                        "model": "",
                        "model_version": "",
                    }
                )
            for path in sorted(folder.glob(f"{job_id}.raw.*.mid")):
                if path.name in seen or not path.is_file():
                    continue
                seen.add(path.name)
                stem_id = path.name[len(job_id) + 5 : -4]
                rows.append(
                    {
                        "id": f"stem_midi:{stem_id}:{path.name}",
                        "kind": "stem_midi",
                        "name": path.name,
                        "filename": path.name,
                        "storage_key": path.name,
                        "content_type": "audio/midi",
                        "stem_id": stem_id,
                        "instrument": stem_id,
                        "sha256": None,
                        "bytes": path.stat().st_size,
                        "source_stage": "",
                        "source_model": "",
                        "model": "",
                        "model_version": "",
                    }
                )
    return rows
