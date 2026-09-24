"""Assemble existing runtime metadata for diagnostics.

Does not invent provider or fallback facts. Ordinary editor payloads should
not include this object unless a field is actionable to the user.
"""

from __future__ import annotations

from typing import Any


def identify_runtime(
    *,
    transcription: Any = None,
    debug: Any = None,
    notation_settings: dict | None = None,
    quantization_summary: dict | None = None,
    interpretation_context: dict | None = None,
) -> dict[str, Any]:
    """Identify the actual runtime from artifacts that already exist.

    Sources, in order of specificity:
    - ``TranscriptionResult.diagnostic_payload()`` for provider / fallback
    - ``PipelineDebug`` for source backend and fallback flag
    - notation settings JSON for algorithm / planner version
    - quantization summary for timing origin and planner engine
    - interpretation context for stored fallback and source backend
    """
    payload = {}
    if transcription is not None and hasattr(transcription, "diagnostic_payload"):
        payload = dict(transcription.diagnostic_payload() or {})
    elif isinstance(transcription, dict):
        payload = dict(transcription)

    debug_d = debug.to_dict() if debug is not None and hasattr(debug, "to_dict") else (
        dict(debug) if isinstance(debug, dict) else {}
    )
    settings = dict(notation_settings or {})
    nested = settings.get("notation_settings")
    if isinstance(nested, dict):
        settings = {**nested, **{k: v for k, v in settings.items() if k != "notation_settings"}}
    summary = dict(quantization_summary or {})
    context = dict(interpretation_context or {})

    provider = (
        payload.get("actual_backend")
        or payload.get("backend")
        or debug_d.get("source_backend")
        or context.get("source_backend")
        or None
    )
    requested = payload.get("requested_backend") or None
    fallback = payload.get("fallback_reason")
    if not fallback and settings.get("fallback"):
        fallback = settings.get("fallback")
    if not fallback and context.get("fallback"):
        fallback = context.get("fallback")
    if not fallback and debug_d.get("fallback_used"):
        fallback = "pipeline_fallback"

    timing_source = (
        summary.get("beat_origin_source")
        or summary.get("layout_source")
        or None
    )
    planner = summary.get("engine") or "notation_engine"
    notation_version = (
        settings.get("algorithm_version")
        or summary.get("algorithm_version")
        or None
    )
    return {
        "provider": provider or "unknown",
        "requested_provider": requested,
        "fallback_reason": fallback,
        "timing_source": timing_source,
        "planner": planner,
        "notation_version": notation_version,
        "layout_authority": summary.get("layout_authority"),
        "user_visible": False,
    }
