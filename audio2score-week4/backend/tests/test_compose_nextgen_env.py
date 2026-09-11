"""Compose interpolates NEXTGEN_* into api/worker environment."""

from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def test_compose_interpolates_nextgen_pipeline_mode_for_api_and_worker():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "NEXTGEN_PIPELINE_MODE: ${NEXTGEN_PIPELINE_MODE:-legacy}" in text
    assert "x-nextgen-env:" in text
    assert "<<: *nextgen-env" in text
    assert text.count("<<: *nextgen-env") >= 2
    assert "NEXTGEN_SEPARATION_ENABLED: ${NEXTGEN_SEPARATION_ENABLED:-0}" in text
    assert "NEXTGEN_STEM_TRANSCRIPTION_ENABLED: ${NEXTGEN_STEM_TRANSCRIPTION_ENABLED:-0}" in text
    assert "NEXTGEN_FUSION_ENABLED: ${NEXTGEN_FUSION_ENABLED:-0}" in text
    assert "NEXTGEN_ENSEMBLE_RENDER: ${NEXTGEN_ENSEMBLE_RENDER:-0}" in text
