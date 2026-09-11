"""Dispatch production jobs across legacy / shadow / live pipeline modes."""

from __future__ import annotations

from pathlib import Path

from engine.flags import PIPELINE_MODE_LIVE, PIPELINE_MODE_SHADOW, pipeline_mode
from transcription import get_engine


def run_job(
    audio_path: str | Path,
    job_id: str,
    *,
    mode: str | None = None,
    filename: str | None = None,
) -> str:
    """Return MusicXML. Legacy behavior is the default."""
    source_name = filename or str(audio_path)
    pm = pipeline_mode()
    if pm == PIPELINE_MODE_LIVE:
        from engine.orchestrator import PipelineOrchestrator

        return PipelineOrchestrator().run(
            audio_path, job_id, mode=mode, filename=source_name
        ).musicxml

    engine = get_engine(mode=mode, filename=source_name)
    xml = engine.transcribe(audio_path, job_id)
    if pm == PIPELINE_MODE_SHADOW:
        from engine.orchestrator import PipelineOrchestrator

        PipelineOrchestrator().shadow_existing(
            audio_path, job_id, engine=engine, musicxml=xml
        )
    return xml
