"""Runtime identity is assembled from existing artifacts, not editor payloads."""

from __future__ import annotations

from mir.debug import PipelineDebug
from mir.models import TranscriptionResult
from mir.runtime_identity import identify_runtime


def test_identify_runtime_from_existing_artifacts():
    transcription = TranscriptionResult(
        notes=[],
        backend="basic_pitch",
        requested_backend="mt3",
        actual_backend="basic_pitch",
        fallback_reason="mt3_unavailable",
    )
    debug = PipelineDebug(source_backend="basic_pitch", fallback_used=True)
    identity = identify_runtime(
        transcription=transcription,
        debug=debug,
        notation_settings={"algorithm_version": "performance-score-1"},
        quantization_summary={
            "engine": "performance",
            "beat_origin_source": "midi_tempo_map",
            "layout_authority": "pipeline",
        },
        interpretation_context={"source_backend": "basic_pitch", "fallback": None},
    )
    assert identity["provider"] == "basic_pitch"
    assert identity["requested_provider"] == "mt3"
    assert identity["fallback_reason"] == "mt3_unavailable"
    assert identity["timing_source"] == "midi_tempo_map"
    assert identity["planner"] == "performance"
    assert identity["notation_version"] == "performance-score-1"
    assert identity["layout_authority"] == "pipeline"
    assert identity["user_visible"] is False


def test_identify_runtime_does_not_invent_fallback():
    identity = identify_runtime(
        quantization_summary={"engine": "notation_engine"},
        notation_settings={"algorithm_version": "performance-score-2"},
    )
    assert identity["provider"] == "unknown"
    assert identity["requested_provider"] is None
    assert identity["fallback_reason"] is None
    assert identity["timing_source"] is None
    assert identity["planner"] == "notation_engine"
    assert identity["notation_version"] == "performance-score-2"
    assert identity["user_visible"] is False


def test_editor_response_omits_runtime_identity():
    from main import _edits_response

    payload = _edits_response(
        {"id": "job-1", "edit_revision": 2},
        {"tempo_bpm": 120, "time_signature": "4/4", "notes": []},
        has_edits=False,
    )
    assert "runtime_identity" not in payload
    assert "provider" not in payload
    assert "fallback_reason" not in payload
    assert "timing_source" not in payload
    assert set(payload) == {
        "score_id",
        "revision",
        "has_edits",
        "tempo_bpm",
        "time_signature",
        "tempo_curve",
        "printed_tempo_marks",
        "provenance",
        "notes",
    }
