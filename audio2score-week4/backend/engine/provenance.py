"""Safe live-job provenance: transcription identity + stage timings.

Never include API keys, tokens, or credential-bearing URLs.
"""

from __future__ import annotations

from typing import Any

from engine.stages import StageName, StageResult


def _stage(stages: list[StageResult], name: StageName) -> StageResult | None:
    for row in stages:
        if row.name == name:
            return row
    return None


def _duration(stages: list[StageResult], name: StageName) -> float | None:
    row = _stage(stages, name)
    if row is None:
        return None
    return round(float(row.duration_ms or 0.0), 3)


def total_pipeline_ms(stages: list[StageResult]) -> float | None:
    """Wall-clock span from first started_at to last finished_at when present."""
    starts = [s.started_at for s in stages if s.started_at is not None]
    ends = [s.finished_at for s in stages if s.finished_at is not None]
    if starts and ends:
        return round((max(ends) - min(starts)) * 1000.0, 3)
    timed = [s.duration_ms for s in stages if not s.skipped and s.duration_ms]
    if not timed:
        return None
    return round(sum(timed), 3)


def stage_timings(stages: list[StageResult], pipeline=None) -> dict[str, Any]:
    transcribe = _stage(stages, StageName.TRANSCRIBE_GLOBAL)
    extra = dict(transcribe.extra) if transcribe is not None else {}
    analyze = _stage(stages, StageName.ANALYZE_AUDIO)
    analyze_extra = dict(analyze.extra) if analyze is not None else {}
    interpret = _stage(stages, StageName.INTERPRET_SCORE)
    interpret_extra = dict(interpret.extra) if interpret is not None else {}
    mt3_ms = extra.get("wall_ms")
    if mt3_ms is None:
        mt3_ms = _duration(stages, StageName.TRANSCRIBE_GLOBAL)
    tracker_ms = analyze_extra.get("tracker_ms")
    if tracker_ms is None and pipeline is not None:
        tracker_ms = getattr(pipeline, "_last_tracker_ms", None)
    notation_ms = interpret_extra.get("export_ms")
    if notation_ms is None and pipeline is not None:
        notation_ms = getattr(pipeline, "last_export_ms", None)
    return {
        "preprocess_ms": _duration(stages, StageName.PREPROCESS),
        "mt3_request_ms": None if mt3_ms is None else round(float(mt3_ms), 3),
        "audio_analysis_ms": _duration(stages, StageName.ANALYZE_AUDIO),
        "beat_tracking_ms": None if tracker_ms is None else round(float(tracker_ms), 3),
        "interpretation_ms": _duration(stages, StageName.INTERPRET_SCORE),
        "notation_ms": None if notation_ms is None else round(float(notation_ms), 3),
        "export_ms": _duration(stages, StageName.EXPORT),
        "total_pipeline_ms": total_pipeline_ms(stages),
    }


def _mt3_public_meta() -> dict[str, str]:
    from adapters.mt3_backend import mt3_status

    status = mt3_status()
    return {
        "provider": str(status.get("provider") or "none"),
        "model": str(status.get("model") or ""),
    }


def transcription_section(pipeline) -> dict[str, Any]:
    identity = dict(getattr(pipeline, "last_raw_identity", None) or {})
    backend = (
        getattr(pipeline, "backend_name", None)
        or getattr(getattr(pipeline, "last_raw_performance", None), "source_backend", None)
        or ""
    )
    section: dict[str, Any] = {
        "backend": backend,
        "provider_raw_sha256": identity.get("provider_raw_sha256"),
        "saved_raw_sha256": identity.get("saved_raw_sha256"),
        "raw_identity_match": identity.get("raw_identity_match"),
    }
    if backend == "mt3":
        section.update(_mt3_public_meta())
    elif backend == "basic_pitch":
        section["provider"] = "local"
        section["model"] = "basic_pitch"
    return section


def live_provenance_fields(pipeline, stages: list[StageResult]) -> dict[str, Any]:
    timings = stage_timings(stages, pipeline)
    return {
        "transcription": transcription_section(pipeline),
        "timings": timings,
        "total_pipeline_ms": timings.get("total_pipeline_ms"),
    }
