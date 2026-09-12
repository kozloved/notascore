"""Phase 2: selected meter, strict edits, tempo MIDI, nested result copies."""

from __future__ import annotations

import io
import json
from pathlib import Path

import mido
import pytest

import database as db
import main as app_main
from mir.canonical_edit import SCHEMA_VERSION, editable_contract_meta
from mir.job import NotationResult, QuantizationResult
from mir.types import NoteEvent
from score_edits import EditError, build_musicxml_and_midi, parse_edits_payload


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'phase2.db'}"
    previous_url = db.DATABASE_URL
    previous_engine = db.engine
    monkeypatch.setenv("DATABASE_URL", url)
    db.DATABASE_URL = url
    db.engine = db.create_engine(
        url, connect_args={"check_same_thread": False, "timeout": 30}
    )
    db.SessionLocal.configure(bind=db.engine)
    db.init_db()
    yield tmp_path
    db.engine.dispose()
    db.engine = previous_engine
    db.DATABASE_URL = previous_url
    db.SessionLocal.configure(bind=previous_engine)


def test_editable_contract_version():
    meta = editable_contract_meta(selected_meter="6/8", note_source="reconciled")
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["selected_meter"] == "6/8"
    assert meta["note_source"] == "reconciled"


def test_selected_meter_persisted_and_loaded(isolated_db, monkeypatch):
    job_id = "meter-348"
    xml = isolated_db / f"{job_id}.musicxml"
    xml.write_text("<score-partwise version='3.1'><part-list/><part id='P1'/></score-partwise>")
    results = isolated_db / "results"
    results.mkdir()
    monkeypatch.setenv("RESULTS_DIR", str(results))
    import storage as storage_mod

    storage_mod.LOCAL_RESULTS_DIR = results
    storage_mod.get_storage.cache_clear()
    attempt = results / f"{job_id}.attempts" / "a1"
    attempt.mkdir(parents=True)
    musicxml = attempt / f"{job_id}.musicxml"
    musicxml.write_text(xml.read_text())
    # Minimal performance snapshot
    from mir.performance import PerformanceSnapshot, SourceNote

    snap = PerformanceSnapshot(
        source_backend="test",
        notes=(
            SourceNote(
                note_id="src-1",
                pitch=60,
                start_sec=0.0,
                end_sec=0.5,
                velocity=80,
                confidence=0.9,
            ),
        ),
    )
    snap_path = attempt / f"{job_id}.performance.json"
    if hasattr(snap, "write_json"):
        snap.write_json(snap_path)
    else:
        snap_path.write_text(json.dumps({
            "source_backend": "test",
            "schema_version": 1,
            "notes": [{
                "note_id": "src-1",
                "pitch": 60,
                "start_sec": 0.0,
                "end_sec": 0.5,
                "velocity": 80,
                "confidence": 0.9,
            }],
            "tracks": [],
            "tempo_changes": [],
            "meter_changes": [],
        }), encoding="utf-8")
    tempo = {
        "selected_meter": "3/4",
        "meter_candidates": [{"meter": "4/4", "score": 0.9}],
        "beat_times": [0.0, 0.5, 1.0, 1.5],
        "printed_tempo": [{"beat": 0, "bpm": 90, "mark": "metronome", "reason": "seed"}],
        "quality": {"median_bpm": 90},
        "performance": {"median_bpm": 90, "beat_times": [0.0, 0.5, 1.0, 1.5]},
        "score": {"median_bpm": 90, "beat_times": [0.0, 0.5, 1.0, 1.5], "tempo_scale": 1.0},
    }
    (attempt / f"{job_id}.tempo.json").write_text(json.dumps(tempo), encoding="utf-8")
    db.create_job(
        {
            "id": job_id,
            "status": "completed",
            "result_storage_key": str(musicxml),
            "created_at": db.utcnow(),
            "updated_at": db.utcnow(),
            "progress": 100,
            "mode": "solo",
            "filename": "clip.wav",
        }
    )
    model = app_main._load_edit_model(db.get_job(job_id))
    assert model["time_signature"] == "3/4"


def test_strict_edit_rejects_invalid_tempo_and_track():
    with pytest.raises(EditError):
        parse_edits_payload(
            {
                "revision": 0,
                "tempo_bpm": 12,
                "time_signature": "4/4",
                "notes": [
                    {
                        "id": "n-1",
                        "pitch": 60,
                        "start": 0,
                        "duration": 1,
                        "velocity": 80,
                        "track": 0,
                        "voice": 0,
                    }
                ],
            }
        )
    with pytest.raises(EditError):
        parse_edits_payload(
            {
                "revision": 0,
                "tempo_bpm": 120,
                "time_signature": "4/4",
                "notes": [
                    {
                        "id": "n-1",
                        "pitch": 60,
                        "start": 0,
                        "duration": 1,
                        "velocity": 80,
                        "track": 99,
                        "voice": 0,
                    }
                ],
            }
        )


def test_long_held_notes_and_extra_tracks_are_accepted():
    model = parse_edits_payload(
        {
            "revision": 0,
            "tempo_bpm": 100,
            "time_signature": "6/8",
            "notes": [
                {
                    "id": "n-1",
                    "pitch": 60,
                    "start": 0,
                    "duration": 64,
                    "velocity": 80,
                    "track": 5,
                    "voice": 0,
                    "start_sec": 0.0,
                    "end_sec": 38.4,
                }
            ],
            "tempo_curve": [{"beat": 0, "bpm": 100}, {"beat": 2, "bpm": 80}],
        }
    )
    assert model["notes"][0]["duration"] == 64
    assert model["notes"][0]["track"] == 5
    xml, midi = build_musicxml_and_midi(model)
    assert "<" in xml
    mid = mido.MidiFile(file=io.BytesIO(midi))
    tempos = [
        msg
        for track in mid.tracks
        for msg in track
        if msg.type == "set_tempo"
    ]
    assert len(tempos) >= 2


def test_nested_result_copy_isolates_events():
    event = NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=80)
    quant = QuantizationResult(events=[event], report={"mode": "performance"})
    notation = NotationResult(quantized_events=[event], quantization=quant, plan={"x": 1})
    copied = notation.copy()
    assert copied.quantized_events[0] is not event
    assert copied.quantization is not quant
    assert copied.quantization.events[0] is not event
    assert copied.plan is not notation.plan
    copied.plan["x"] = 99
    assert notation.plan["x"] == 1
