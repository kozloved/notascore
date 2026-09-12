"""Immutable attempt/edit bundles and the storage keys that point at them.

Committed results are a database pointer. Bundles are never overwritten
in place; a losing compare-and-swap leaves the previous pointer readable.
"""

from __future__ import annotations

from pathlib import Path


def attempt_prefix(job_id: str, attempt_id: str) -> str:
    return f"{job_id}.attempts/{attempt_id}"


def attempt_keys(job_id: str, attempt_id: str) -> dict[str, str]:
    prefix = attempt_prefix(job_id, attempt_id)
    return {
        "musicxml": f"{prefix}/{job_id}.musicxml",
        "raw": f"{prefix}/{job_id}.raw.mid",
        "validated": f"{prefix}/{job_id}.validated.mid",
        "score": f"{prefix}/{job_id}.score.mid",
        "manifest": f"{prefix}/{job_id}.manifest.json",
    }


def edit_bundle_prefix(job_id: str, bundle_id: str) -> str:
    return f"{job_id}.edits/{bundle_id}"


def edit_bundle_keys(job_id: str, bundle_id: str) -> dict[str, str]:
    prefix = edit_bundle_prefix(job_id, bundle_id)
    return {
        "json": f"{prefix}/{job_id}.edits.json",
        "musicxml": f"{prefix}/{job_id}.edited.musicxml",
        "midi": f"{prefix}/{job_id}.edited.mid",
    }


def sibling_key(storage_key: str | None, filename: str) -> str | None:
    if not storage_key:
        return None
    name = Path(filename).name
    parent = Path(storage_key).parent
    if str(parent) in {".", ""}:
        return name
    return str(parent / name)


def is_edit_bundle_key(storage_key: str | None, job_id: str) -> bool:
    if not storage_key:
        return False
    marker = f"{job_id}.edits/"
    return marker in str(storage_key).replace("\\", "/")


def is_attempt_key(storage_key: str | None, job_id: str) -> bool:
    if not storage_key:
        return False
    marker = f"{job_id}.attempts/"
    return marker in str(storage_key).replace("\\", "/")


def attempt_object_key(job_id: str, attempt_id: str, filename: str) -> str:
    return f"{attempt_prefix(job_id, attempt_id)}/{Path(filename).name}"


def edit_bundle_directory(storage_key: str | None, job_id: str) -> str | None:
    if not storage_key:
        return None
    normalized = str(storage_key).replace("\\", "/")
    marker = f"{job_id}.edits/"
    index = normalized.find(marker)
    if index < 0:
        return None
    rest = normalized[index + len(marker) :]
    bundle_id = rest.split("/")[0]
    if not bundle_id:
        return None
    return normalized[: index + len(marker)] + bundle_id


def attempt_directory(storage_key: str | None, job_id: str) -> str | None:
    if not storage_key:
        return None
    normalized = str(storage_key).replace("\\", "/")
    marker = f"{job_id}.attempts/"
    index = normalized.find(marker)
    if index < 0:
        return None
    rest = normalized[index + len(marker) :]
    attempt_id = rest.split("/")[0]
    if not attempt_id:
        return None
    return normalized[: index + len(marker)] + attempt_id
