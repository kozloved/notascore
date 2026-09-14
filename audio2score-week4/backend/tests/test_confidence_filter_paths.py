"""Optional filtering cannot change raw MIDI; both execution paths agree."""

from __future__ import annotations

import hashlib

from engine.orchestrator import PipelineOrchestrator
from mir.confidence_gate import apply_optional_filter
from mir.pipeline import UnderstandingPipeline
from mir.raw_midi import job_raw_midi_path
from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent
from tests.test_live_orchestrator_job import _wav


def _notes():
    return [
        NoteEvent(
            pitch=60,
            start_time=0.0,
            end_time=0.4,
            velocity=90,
            confidence=0.9,
            model_score=0.9,
            confidence_source="amplitude",
            source_backend="basic_pitch",
            note_id="n0000",
        ),
        NoteEvent(
            pitch=72,
            start_time=0.1,
            end_time=0.3,
            velocity=20,
            confidence=0.12,
            model_score=0.12,
            confidence_source="amplitude",
            source_backend="basic_pitch",
            note_id="n0001",
        ),
        NoteEvent(
            pitch=61,
            start_time=0.2,
            end_time=0.4,
            velocity=40,
            confidence=0.2,
            confidence_source="calibrated",
            source_backend="basic_pitch",
            note_id="n0002",
        ),
    ]


def _support(monkeypatch, notes):
    from audio_engine.beat_tracker import constant_tempo_map

    def fake_bp(self, path):
        return list(notes)

    def fake_track(self, audio):
        self.last_source = "madmom"
        self.last_time_signature = "4/4"
        self.last_beat_times = [0.0, 0.5, 1.0]
        return constant_tempo_map(120.0)

    monkeypatch.setattr(
        "adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes", fake_bp
    )
    monkeypatch.setattr("audio_engine.beat_tracker.BeatTracker.track", fake_track)
    monkeypatch.setattr(
        "audio_engine.instrument_classifier.InstrumentClassifier.classify",
        lambda self, audio: InstrumentPrediction(
            instrument=InstrumentKind.PIANO, confidence=0.9
        ),
    )
    monkeypatch.setattr("mir.pipeline.AudioSegmenter.segment", lambda self, audio: [])
    monkeypatch.setenv("NEXTGEN_PIPELINE_MODE", "live")
    monkeypatch.setenv("NEXTGEN_SEPARATION_ENABLED", "0")
    monkeypatch.setenv("NEXTGEN_FUSION_ENABLED", "0")
    monkeypatch.setenv("NEXTGEN_STEM_TRANSCRIPTION_ENABLED", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_PIANO_ANALYZER", "0")


def test_disabled_filter_keeps_quiet_and_uncalibrated_notes(monkeypatch, tmp_path):
    notes = _notes()
    _support(monkeypatch, notes)
    monkeypatch.delenv("NOTASCORE_DROP_LOW_CONFIDENCE", raising=False)
    audio = _wav(tmp_path / "off.wav")
    pipe = UnderstandingPipeline(mode="solo")
    pipe.transcribe(audio, "filt-off")
    assert [n.note_id for n in pipe.last_raw_notes] == ["n0000", "n0001", "n0002"]
    assert [n.note_id for n in pipe.last_filtered_notes] == ["n0000", "n0001", "n0002"]
    assert pipe.last_filter_report.enabled is False
    assert pipe.last_filter_report.removals == []


def test_enabled_filter_does_not_change_raw_midi_or_original_inventory(
    monkeypatch, tmp_path
):
    notes = _notes()
    _support(monkeypatch, notes)
    monkeypatch.setenv("NOTASCORE_DROP_LOW_CONFIDENCE", "1")
    audio = _wav(tmp_path / "on.wav")
    pipe = UnderstandingPipeline(mode="solo")
    pipe.transcribe(audio, "filt-on")
    raw_ids = [n.note_id for n in pipe.last_raw_notes]
    assert raw_ids == ["n0000", "n0001", "n0002"]
    filtered_ids = [n.note_id for n in pipe.last_filtered_notes]
    assert "n0002" not in filtered_ids
    assert "n0001" in filtered_ids  # quiet amplitude is not presumed false
    report = pipe.last_filter_report
    assert report.enabled is True
    assert [r.note_id for r in report.removals] == ["n0002"]
    assert report.removals[0].criterion == "calibrated_confidence"
    assert report.removals[0].score == 0.2
    assert report.removals[0].threshold == 0.45
    raw_path = job_raw_midi_path(audio, "filt-on")
    off_dir = tmp_path / "off-compare"
    off_dir.mkdir()
    audio2 = _wav(off_dir / "off.wav")
    monkeypatch.setenv("NOTASCORE_DROP_LOW_CONFIDENCE", "0")
    UnderstandingPipeline(mode="solo").transcribe(audio2, "filt-off2")
    off_raw = job_raw_midi_path(audio2, "filt-off2").read_bytes()
    assert raw_path.read_bytes() == off_raw


def test_direct_and_orchestrated_paths_make_the_same_filter_decision(
    monkeypatch, tmp_path
):
    notes = _notes()
    _support(monkeypatch, notes)
    monkeypatch.setenv("NOTASCORE_DROP_LOW_CONFIDENCE", "1")
    audio = _wav(tmp_path / "parity.wav")
    direct = UnderstandingPipeline(mode="solo")
    direct.transcribe(audio, "parity-direct")
    live = PipelineOrchestrator().run(audio, "parity-live", mode="solo")
    # Orchestrator debug.json records the same filter report as the direct path.
    import json

    debug = json.loads((tmp_path / "bp_parity-live" / "parity-live.debug.json").read_text())
    extra = debug.get("extra") or {}
    live_filter = extra.get("filter") or {}
    direct_ids = [r.note_id for r in direct.last_filter_report.removals]
    live_ids = [r["note_id"] for r in live_filter.get("removals") or []]
    assert live.musicxml
    assert live_ids == direct_ids == ["n0002"]
    assert hashlib.sha256(
        job_raw_midi_path(audio, "parity-direct").read_bytes()
    ).hexdigest() == hashlib.sha256(
        job_raw_midi_path(audio, "parity-live").read_bytes()
    ).hexdigest()


def test_apply_optional_filter_does_not_mutate_input():
    notes = _notes()
    snapshot = list(notes)
    kept, report = apply_optional_filter(notes, enabled=True, threshold=0.45)
    assert notes == snapshot
    assert report.input_count == 3
    assert [n.note_id for n in kept] == ["n0000", "n0001"]
