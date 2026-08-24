"""Gemini HTTP provider parsing (no network)."""

from __future__ import annotations

import io
import json

from intelligence.config import gemini_config
from intelligence.gemini_provider import GeminiProvider
from intelligence.packet import build_analysis_packet
from mir.cmr_builder import notes_to_events
from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent, TempoMap, TempoPoint


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_gemini_provider_parses_json_candidate(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setenv("TEMP_DIR", str(tmp_path))
    cfg = gemini_config()
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "overall_confidence": 0.81,
                                    "corrections": [],
                                    "instrument_analysis": {"primary_instruments": ["piano"]},
                                }
                            )
                        }
                    ]
                }
            }
        ],
        "usageMetadata": {"promptTokenCount": 200, "candidatesTokenCount": 40},
    }

    def opener(request, timeout=0):
        header = request.get_header("X-goog-api-key") or request.get_header("x-goog-api-key")
        assert header == "secret-key"
        assert b"secret-key" not in (request.data or b"")
        return _FakeResponse(json.dumps(payload).encode())

    notes = [NoteEvent(60, 0.0, 0.4, 80, 0.9)]
    tempo = TempoMap(points=[TempoPoint(0.0, 0.0, 120.0, 1.0)])
    packet = build_analysis_packet(
        job_id="http",
        notes=notes,
        events=notes_to_events(notes, tempo, instrument=InstrumentKind.PIANO),
        tempo_map=tempo,
        prediction=InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.8),
    )
    analysis, usage = GeminiProvider(cfg, opener=opener).analyse(
        packet, model="gemini-2.5-flash-lite", audio_bytes=None, audio_mime="audio/wav", task="full"
    )
    assert analysis.overall_confidence == 0.81
    assert usage["prompt_tokens"] == 200


def test_parse_json_object_accepts_array_and_fenced_text():
    from intelligence.gemini_provider import _parse_json_object

    wrapped = _parse_json_object('```json\n[{"overall_confidence": 0.5}]\n```')
    assert wrapped["overall_confidence"] == 0.5
    listed = _parse_json_object(
        json.dumps([{"type": "pitch", "time_start": 0, "time_end": 0.2, "confidence": 0.9}])
    )
    assert listed["corrections"][0]["type"] == "pitch"
    noisy = _parse_json_object('prefix {"overall_confidence": 0.4, "corrections": []} trailing')
    assert noisy["overall_confidence"] == 0.4


def test_correction_normalizes_flash_note_objects_and_word_confidence():
    from intelligence.schemas import Correction

    drop = Correction.from_dict(
        {
            "time_start": 1.99,
            "time_end": 3.08,
            "confidence": "high",
            "original_notes": [{"pitch": 88, "start": 1.99, "duration": 1.1, "velocity": 59}],
            "corrected_notes": [],
            "reason": "spurious overtone",
        }
    )
    assert drop.type == "pitch"
    assert drop.proposed_value.get("drop") is True
    assert drop.proposed_value.get("pitch") == 88
    assert drop.confidence == 0.9

    retune = Correction.from_dict(
        {
            "type": "update_note",
            "time_start": 1.6,
            "time_end": 2.0,
            "original_notes": [{"pitch": 71, "start": 1.6, "duration": 0.4}],
            "corrected_notes": [{"pitch": 69, "start": 1.6, "duration": 0.4}],
            "confidence": 0.92,
        }
    )
    assert retune.type == "pitch"
    assert retune.proposed_value.get("pitch") == 69
    assert retune.existing_value.get("pitch") == 71
