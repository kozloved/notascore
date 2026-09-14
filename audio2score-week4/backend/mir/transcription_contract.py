"""Build and capture TranscriptionResult without relying on adapter last_* fields.

Adapters may still populate last_* for older tests. Production interpretation
must receive this object explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mir.midi_ingest import NoPitchedNotesError
from mir.models import TranscriptionResult
from mir.types import NoteEvent


def result_from_backend_state(
    backend,
    notes: list[NoteEvent],
    audio_path: str | Path = "",
    *,
    requested_backend: str | None = None,
) -> TranscriptionResult:
    """Compatibility wrap after transcribe_notes(), including test doubles."""
    name = str(getattr(backend, "name", "") or "unknown")
    requested = requested_backend or name
    last_result = getattr(backend, "last_result", None)
    if isinstance(last_result, TranscriptionResult) and last_result.notes is not None:
        if last_result.requested_backend == last_result.actual_backend and requested != name:
            last_result.requested_backend = requested
        return last_result
    return TranscriptionResult(
        notes=list(notes),
        backend=name,
        requested_backend=requested,
        actual_backend=name,
        original_notes=list(notes),
        audio_path=str(audio_path or ""),
        provider_midi_bytes=getattr(backend, "last_midi_bytes", None),
        provider_raw_sha256=getattr(backend, "last_provider_raw_sha256", None),
        performance=getattr(backend, "last_performance", None),
        provider_job_id=getattr(backend, "last_provider_job_id", None),
        timings=dict(getattr(backend, "last_timing", None) or {}),
        settings=dict(getattr(backend, "last_settings", None) or {}),
        extra=dict(getattr(backend, "last_extra", None) or {}),
    )


def capture_transcription(backend, audio_path: str | Path) -> TranscriptionResult:
    """Run the backend and return an owned result.

    Calls transcribe_notes so existing mocks keep working. Prefers last_result
    when the adapter populated the contract during the same call.
    """
    notes = backend.transcribe_notes(audio_path)
    return result_from_backend_state(backend, list(notes or []), audio_path)


def unsuccessful_from_exception(exc: NoPitchedNotesError, *, backend: str) -> dict[str, Any]:
    sha = exc.provider_raw_sha256
    if sha is None and exc.performance is not None:
        sha = getattr(exc.performance, "midi_sha256", None)
    return {
        "backend": backend,
        "reason": exc.reason,
        "error": str(exc),
        "provider_raw_sha256": sha,
        "provider_midi_bytes": exc.midi_bytes,
        "performance": exc.performance,
        "note_count": 0,
        "drum_note_count": (
            sum(1 for n in exc.performance.notes if n.is_drum)
            if exc.performance is not None
            else 0
        ),
    }


def json_safe_unsuccessful(row: dict[str, Any]) -> dict[str, Any]:
    skip = {"provider_midi_bytes", "performance"}
    payload = {key: value for key, value in row.items() if key not in skip}
    performance = row.get("performance")
    if performance is not None:
        payload["performance_midi_sha256"] = getattr(performance, "midi_sha256", None)
        payload["performance_note_count"] = len(getattr(performance, "notes", ()) or ())
    return payload


def unsuccessful_from_result(result: TranscriptionResult) -> dict[str, Any]:
    return {
        "backend": result.actual_backend or result.backend,
        "reason": "empty_note_list",
        "error": "transcription returned no pitched notes",
        "provider_raw_sha256": result.provider_raw_sha256,
        "provider_midi_bytes": result.provider_midi_bytes,
        "performance": result.performance,
        "note_count": len(result.notes),
        "timings": dict(result.timings or {}),
        "provider_job_id": result.provider_job_id,
    }


def apply_basic_pitch_fallback(
    bp_result: TranscriptionResult,
    *,
    requested_backend: str,
    unsuccessful: dict[str, Any],
    reason: str,
) -> TranscriptionResult:
    """Label a coherent Basic Pitch result; keep the failed MT3 payload separate."""
    warnings = list(bp_result.warnings or [])
    message = (
        "MT3 returned no pitched notes; falling back to Basic Pitch "
        "for this polyphonic job"
    )
    if message not in warnings:
        warnings.append(message)
    bp_result.requested_backend = requested_backend or "mt3"
    bp_result.actual_backend = "basic_pitch"
    bp_result.backend = "basic_pitch"
    bp_result.fallback_reason = reason
    bp_result.warnings = warnings
    bp_result.unsuccessful = [unsuccessful]
    # Fallback evidence is Basic Pitch's. Do not keep MT3 bytes as the
    # successful provider payload.
    if bp_result.provider_midi_bytes is unsuccessful.get("provider_midi_bytes"):
        bp_result.provider_midi_bytes = None
        bp_result.provider_raw_sha256 = None
        bp_result.performance = None
    return bp_result
