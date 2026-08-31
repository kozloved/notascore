"""Score titles, claim tokens, and job visibility. No transcription logic."""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path


def title_from_filename(filename: str | None) -> str:
    stem = Path(filename or "").stem
    cleaned = re.sub(r"[_-]+", " ", stem)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return "Untitled score"
    return cleaned.title()


def new_claim_token() -> str:
    return secrets.token_urlsafe(32)


def hash_claim_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sanitize_title(value: str | None) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text:
        return "Untitled score"
    return text[:120]


def job_is_deleted(job: dict | None) -> bool:
    return bool(job and job.get("deleted_at"))


def job_visible_to(job: dict | None, user_id: str | None) -> bool:
    if not job or job_is_deleted(job):
        return False
    owner = job.get("user_id")
    if not owner:
        return True
    return bool(user_id) and owner == user_id
