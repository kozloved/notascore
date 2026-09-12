"""Job lease heartbeats, recovery, publish validation, and delayed GC."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from engine.artifacts import ArtifactKind, ArtifactManifest, ArtifactRef, hash_file
from publishing import attempt_keys, attempt_object_key

# Required performance evidence for a published attempt. Optional diagnostics
# (fusion, debug, stems) must never be treated as required.
REQUIRED_PUBLISH_KINDS = (
    ArtifactKind.MUSICXML,
    ArtifactKind.SCORE_MIDI,
    ArtifactKind.VALIDATED_MIDI,
)

_KIND_BY_SUFFIX = {
    ".musicxml": ArtifactKind.MUSICXML,
    ".raw.mid": ArtifactKind.RAW_MIDI,
    ".validated.mid": ArtifactKind.VALIDATED_MIDI,
    ".score.mid": ArtifactKind.SCORE_MIDI,
    ".performance.json": ArtifactKind.PERFORMANCE_JSON,
    ".manifest.json": ArtifactKind.MANIFEST_JSON,
}


def lease_ttl_seconds() -> int:
    raw = os.getenv("JOB_LEASE_TTL_SECONDS", "120")
    try:
        return max(15, int(raw))
    except (TypeError, ValueError):
        return 120


def heartbeat_interval_seconds() -> float:
    raw = os.getenv("JOB_HEARTBEAT_INTERVAL_SECONDS", "30")
    try:
        return max(5.0, float(raw))
    except (TypeError, ValueError):
        return 30.0


def artifact_gc_grace_seconds() -> int:
    raw = os.getenv("ARTIFACT_GC_GRACE_SECONDS", "300")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 300


def max_job_retries() -> int:
    raw = os.getenv("JOB_MAX_RETRIES", "3")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 3


def recovery_backoff_seconds(retry_count: int) -> int:
    base = os.getenv("JOB_RETRY_BACKOFF_SECONDS", "30")
    try:
        seconds = max(1, int(base))
    except (TypeError, ValueError):
        seconds = 30
    return min(seconds * (2 ** max(0, int(retry_count))), 3600)


def lease_expiry_iso(ttl_seconds: int | None = None) -> str:
    ttl = lease_ttl_seconds() if ttl_seconds is None else max(1, int(ttl_seconds))
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class AttemptHeartbeat:
    """Attempt-fenced lease renewals that stop after fencing-out."""

    def __init__(
        self,
        job_id: str,
        attempt_id: str,
        renew: Callable[[str, str], bool],
        *,
        interval_seconds: float | None = None,
    ):
        self.job_id = job_id
        self.attempt_id = attempt_id
        self._renew = renew
        self.interval = (
            heartbeat_interval_seconds()
            if interval_seconds is None
            else max(0.05, float(interval_seconds))
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.alive = True
        self.renewals = 0

    def start(self) -> "AttemptHeartbeat":
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._run,
            name=f"heartbeat-{self.attempt_id[:8]}",
            daemon=True,
        )
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            if not self._renew(self.job_id, self.attempt_id):
                self.alive = False
                self._stop.set()
                return
            self.renewals += 1

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

    def __enter__(self) -> "AttemptHeartbeat":
        return self.start()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()


def kind_for_filename(name: str) -> ArtifactKind | None:
    lower = name.lower()
    for suffix, kind in _KIND_BY_SUFFIX.items():
        if lower.endswith(suffix):
            return kind
    if lower.endswith(".mid") or lower.endswith(".midi"):
        return ArtifactKind.SCORE_MIDI
    if lower.endswith(".json"):
        return ArtifactKind.DEBUG_JSON
    return None


def build_publish_manifest(
    job_id: str,
    attempt_id: str,
    local_files: dict[str, Path],
    *,
    required_kinds: tuple[ArtifactKind, ...] = REQUIRED_PUBLISH_KINDS,
) -> ArtifactManifest:
    """Validate required local artifacts and return a hashed publish manifest.

    Raises ValueError when a required kind is missing or empty.
    """
    manifest = ArtifactManifest(job_id=job_id, schema_version=2)
    present: dict[ArtifactKind, ArtifactRef] = {}
    for logical, path in local_files.items():
        dest = Path(path)
        if not dest.is_file() or dest.stat().st_size <= 0:
            continue
        kind = kind_for_filename(dest.name) or kind_for_filename(logical)
        if kind is None:
            kind = ArtifactKind.DEBUG_JSON
        digest, size = hash_file(dest)
        key = attempt_object_key(job_id, attempt_id, dest.name)
        ref = ArtifactRef(
            kind=kind,
            path=str(dest),
            content_type=_content_type(dest),
            sha256=digest,
            bytes=size,
            storage_key=key,
            source_stage="publish",
            artifact_id=f"{kind.value}:{attempt_id[:8]}:{digest[:12]}",
        )
        manifest.add(ref)
        present[kind] = ref

    missing = [kind.value for kind in required_kinds if kind not in present]
    if missing:
        raise ValueError(f"missing required publish artifacts: {', '.join(missing)}")
    return manifest


def verify_uploaded_hashes(
    storage,
    manifest: ArtifactManifest,
    *,
    required_kinds: tuple[ArtifactKind, ...] = REQUIRED_PUBLISH_KINDS,
) -> None:
    """Re-read uploaded objects and confirm sha256 matches the local manifest."""
    required = {kind.value for kind in required_kinds}
    checked = set()
    for ref in manifest.artifacts:
        if ref.kind.value not in required:
            continue
        raw = storage.read_result_bytes(ref.storage_key)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != ref.sha256:
            raise ValueError(
                f"corrupt published artifact {ref.storage_key}: "
                f"expected {ref.sha256}, got {digest}"
            )
        checked.add(ref.kind.value)
    missing = sorted(required - checked)
    if missing:
        raise ValueError(f"missing required published artifacts: {', '.join(missing)}")


def write_publish_manifest(storage, job_id: str, attempt_id: str, manifest: ArtifactManifest) -> str:
    keys = attempt_keys(job_id, attempt_id)
    payload = json.dumps(manifest.to_dict(), indent=2) + "\n"
    return storage.save_text(
        keys["manifest"],
        payload,
        content_type="application/json",
    )


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".mid", ".midi"}:
        return "audio/midi"
    if suffix == ".wav":
        return "audio/wav"
    if suffix in {".xml", ".musicxml"}:
        return "application/vnd.recordare.musicxml+xml"
    return "application/json"


# --- Delayed, reachability-aware GC -----------------------------------------

_holds_lock = threading.Lock()
_reader_holds: dict[str, float] = {}  # job_id -> unix expiry
_tombstones: list[dict] = []
_tombstones_lock = threading.Lock()


def hold_job_artifacts(job_id: str, ttl_seconds: int | None = None) -> float:
    """Keep published/previous bundles readable for an in-flight download/reader."""
    ttl = artifact_gc_grace_seconds() if ttl_seconds is None else max(1, int(ttl_seconds))
    until = time.time() + ttl
    with _holds_lock:
        previous = _reader_holds.get(job_id, 0.0)
        _reader_holds[job_id] = max(previous, until)
    return until


def reader_hold_active(job_id: str, *, now: float | None = None) -> bool:
    stamp = time.time() if now is None else now
    with _holds_lock:
        until = _reader_holds.get(job_id)
        if until is None:
            return False
        if until <= stamp:
            _reader_holds.pop(job_id, None)
            return False
        return True


def schedule_attempt_gc(
    job_id: str,
    attempt_ids,
    *,
    keep_attempt_ids=(),
    not_before: float | None = None,
) -> dict:
    keep = {str(item) for item in (keep_attempt_ids or ()) if item}
    doomed = sorted({str(item) for item in (attempt_ids or ()) if item and str(item) not in keep})
    entry = {
        "job_id": job_id,
        "attempt_ids": doomed,
        "keep_attempt_ids": sorted(keep),
        "not_before": float(
            time.time() + artifact_gc_grace_seconds() if not_before is None else not_before
        ),
        "kind": "attempts",
    }
    with _tombstones_lock:
        _tombstones.append(entry)
    return entry


def schedule_edit_bundle_gc(
    job_id: str,
    edited_key: str | None,
    *,
    keep_key: str | None = None,
    not_before: float | None = None,
) -> dict | None:
    if not edited_key or edited_key == keep_key:
        return None
    entry = {
        "job_id": job_id,
        "edited_key": edited_key,
        "keep_key": keep_key,
        "not_before": float(
            time.time() + artifact_gc_grace_seconds() if not_before is None else not_before
        ),
        "kind": "edit",
    }
    with _tombstones_lock:
        _tombstones.append(entry)
    return entry


def pending_tombstones(*, now: float | None = None) -> list[dict]:
    stamp = time.time() if now is None else now
    with _tombstones_lock:
        return [dict(item) for item in _tombstones if float(item.get("not_before") or 0) <= stamp]


def clear_tombstones_for_tests() -> None:
    with _tombstones_lock:
        _tombstones.clear()
    with _holds_lock:
        _reader_holds.clear()


def sweep_artifact_gc(storage, *, now: float | None = None) -> list[dict]:
    """Delete tombstoned artifacts once grace elapsed and no reader hold remains."""
    stamp = time.time() if now is None else now
    applied: list[dict] = []
    remaining: list[dict] = []
    with _tombstones_lock:
        queue = list(_tombstones)
        _tombstones.clear()
    for entry in queue:
        if float(entry.get("not_before") or 0) > stamp:
            remaining.append(entry)
            continue
        job_id = str(entry.get("job_id") or "")
        if reader_hold_active(job_id, now=stamp):
            remaining.append(entry)
            continue
        try:
            if entry.get("kind") == "edit":
                if hasattr(storage, "gc_edit_bundle"):
                    storage.gc_edit_bundle(
                        entry.get("edited_key"),
                        job_id,
                        keep_key=entry.get("keep_key"),
                    )
            else:
                keep = set(entry.get("keep_attempt_ids") or [])
                if hasattr(storage, "gc_unreachable_attempts"):
                    storage.gc_unreachable_attempts(job_id, keep_attempt_ids=keep)
            applied.append(entry)
        except Exception:
            # Cleanup failures must not fail transcription/publish.
            remaining.append(entry)
    with _tombstones_lock:
        _tombstones.extend(remaining)
    return applied


def discover_unreachable_attempt_ids(storage, job_id: str, keep_attempt_ids) -> list[str]:
    from publishing import attempt_id_from_key

    keep = {str(item) for item in (keep_attempt_ids or ()) if item}
    prefix = f"{job_id}.attempts"
    found: set[str] = set()
    for key in storage.list_result_keys(prefix):
        attempt_id = attempt_id_from_key(key, job_id)
        if attempt_id and attempt_id not in keep:
            found.add(attempt_id)
    return sorted(found)
