"""Provider MIDI identity: hash received bytes, never reconstructed MIDI.

Invariant for MT3 / provider-byte-backed transcription:

    SHA256(provider MIDI bytes) == SHA256({job}.raw.mid)

Raw MIDI is immutable. A mismatch is an internal failure, not a retry path.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

RAW_IDENTITY_VIOLATION = "raw_transcription_identity_violation"
_PUBLIC_IDENTITY_ERROR = "Transcription failed"


def sha256_hex(data: bytes) -> str:
    """SHA-256 of exact bytes. Do not rebuild MIDI to hash it."""
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str | Path) -> str:
    return sha256_hex(Path(path).read_bytes())


def transcription_identity(
    *,
    provider_raw_sha256: str | None,
    saved_raw_sha256: str | None,
) -> dict[str, Any]:
    """Record identity without inventing a provider SHA for local engines."""
    if provider_raw_sha256 is None:
        return {
            "provider_raw_sha256": None,
            "saved_raw_sha256": saved_raw_sha256,
            "raw_identity_match": None,
        }
    match = bool(saved_raw_sha256) and saved_raw_sha256 == provider_raw_sha256
    return {
        "provider_raw_sha256": provider_raw_sha256,
        "saved_raw_sha256": saved_raw_sha256,
        "raw_identity_match": match,
    }


def enforce_provider_identity(record: dict[str, Any]) -> None:
    """Hard-fail when a provider-backed raw MIDI was rewritten before save."""
    if record.get("provider_raw_sha256") is None:
        return
    if record.get("raw_identity_match") is True:
        return
    from transcription import TranscriptionError

    provider = record.get("provider_raw_sha256")
    saved = record.get("saved_raw_sha256")
    raise TranscriptionError(
        f"{RAW_IDENTITY_VIOLATION}: provider_raw_sha256={provider} "
        f"saved_raw_sha256={saved}",
        code=RAW_IDENTITY_VIOLATION,
        public_message=_PUBLIC_IDENTITY_ERROR,
    )


def record_saved_raw(
    raw_path: str | Path,
    *,
    provider_raw_sha256: str | None,
) -> dict[str, Any]:
    """Hash the file that was just written and compare to the provider SHA."""
    saved = hash_file(raw_path)
    record = transcription_identity(
        provider_raw_sha256=provider_raw_sha256,
        saved_raw_sha256=saved,
    )
    enforce_provider_identity(record)
    return record
