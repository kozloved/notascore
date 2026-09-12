from dataclasses import FrozenInstanceError, replace

import pytest

from mir.job import ImmutableNoteSet, PipelineJob
from mir.quantizer import MeasureQuantizer
from mir.quantizer_compare import compare_quantizers
from mir.models import MeterHypothesis
from mir.pipeline_config import QuantizationMode, is_experimental_quantization
from mir.types import MusicalEvent, NoteEvent
from notation_engine.plan import NotationPlanner
from timing.tempo_map import MusicalTimeMap


def _ev(pitch, start, dur, note_id="n"):
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        note_id=note_id,
        start_time_sec=start * 0.5,
        end_time_sec=(start + dur) * 0.5,
    )


def _meter():
    return MeterHypothesis(
        time_signature="4/4",
        numerator=4,
        denominator=4,
        measure_quarter_length=4.0,
        score=1.0,
        confidence=1.0,
    )


def test_immutable_note_set_copies_are_independent():
    original = [NoteEvent(pitch=60, start_time=0.0, end_time=0.5, note_id="a")]
    frozen = ImmutableNoteSet.from_notes(original, source="full_mix")
    with pytest.raises(FrozenInstanceError):
        original[0].pitch = 72
    with pytest.raises(FrozenInstanceError):
        frozen.notes[0].pitch = 99
    working = frozen.copy_notes()
    working[0] = replace(working[0], pitch=64)
    assert frozen.notes[0].pitch == 60
    assert working[0].pitch == 64
    assert frozen.source == "full_mix"


def test_pipeline_job_holds_one_time_map():
    notes = ImmutableNoteSet.from_notes(
        [NoteEvent(pitch=60, start_time=0.0, end_time=0.4, note_id="a")]
    )
    time_map = MusicalTimeMap.from_bpm(120.0, duration_sec=2.0)
    job = PipelineJob(job_id="j1", notes=notes, mix_notes=notes, time_map=time_map)
    assert job.time_map is time_map
    assert job.notes.source == "full_mix"
    payload = job.to_dict()
    assert payload["time_map_beats"] >= 2
    with pytest.raises(FrozenInstanceError):
        job.job_id = "other"


def test_production_quantize_ignores_adaptive_mode_on_explicit_production_call():
    events = [_ev(60, 0.0, 1.0, "q")]
    q = MeasureQuantizer(mode="adaptive")
    result = q.quantize_production(events, _meter())
    assert result.engine == "performance"
    assert result.experimental is False
    assert not is_experimental_quantization("performance")
    assert is_experimental_quantization("adaptive")
    assert is_experimental_quantization(QuantizationMode.PM2S)


def test_quantize_result_defaults_to_production_even_if_mode_is_experimental():
    events = [_ev(60, 0.11, 0.37, "q")]
    q = MeasureQuantizer(mode="off")
    result = q.quantize_result(events, _meter())
    assert result.engine == "performance"
    assert result.experimental is False
    experimental = q.quantize_experimental(events, _meter(), "off")
    assert experimental.engine == "identity"
    assert experimental.experimental is True


def test_compare_quantizers_keeps_performance_as_production():
    events = [_ev(64, 0.0, 1.0, "e")]
    report = compare_quantizers(events, _meter(), experimental_modes=("adaptive", "off"))
    assert report["production_engine"] == "performance"
    assert report["production"]["engine"] == "performance"
    assert "adaptive" in report["experimental"]
    assert report["experimental"]["adaptive"]["experimental"] is True
    assert report["experimental"]["off"]["engine"] == "identity"


def test_planner_omitted_mode_stays_production_when_env_is_off():
    events = [_ev(72, 0.0, 1.0, "a"), _ev(74, 1.0, 1.0, "b")]
    planner = NotationPlanner()
    planner.quantizer.mode = QuantizationMode.OFF
    built = planner.build_result(events, quantization_mode=None)
    assert built.quantization.engine == "performance"
    assert built.quantization.experimental is False


def test_mutating_quantizer_diagnostics_does_not_change_job_snapshot():
    events = [_ev(60, 0.0, 1.0, "q")]
    result = MeasureQuantizer().quantize_production(events, _meter())
    notes = ImmutableNoteSet.from_notes(
        [NoteEvent(pitch=60, start_time=0.0, end_time=0.5, note_id="a")]
    )
    job = PipelineJob(
        job_id="j1",
        notes=notes,
        mix_notes=notes,
        quantization=result.copy(),
    )
    original_count = len(job.quantization.events)
    original_decisions = list(job.quantization.decisions)
    result.events.clear()
    result.decisions.append({"mutated": True})
    assert len(job.quantization.events) == original_count
    assert job.quantization.decisions == original_decisions


def test_pipeline_creates_job_before_export_and_ignores_experimental_env(
    tmp_path, monkeypatch
):
    import mido
    from mir.pipeline import UnderstandingPipeline

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "off")
    source = tmp_path / "stage.mid"
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend(
        [
            mido.MetaMessage("set_tempo", tempo=500000),
            mido.MetaMessage("time_signature", numerator=4, denominator=4),
            mido.Message("note_on", note=60, velocity=80, time=0),
            mido.Message("note_off", note=60, time=480),
        ]
    )
    midi.save(source)

    seen = {}

    def _capture(self, *args, **kwargs):
        pipe = seen["pipe"]
        assert pipe.job is not None
        assert pipe.job.job_id == "stage"
        assert len(pipe.job.mix_notes) == 1
        assert pipe.job.time_map is not None
        return original(self, *args, **kwargs)

    from notation_engine.writer import NotationWriter

    original = NotationWriter.write_musicxml_with_result
    monkeypatch.setattr(NotationWriter, "write_musicxml_with_result", _capture)
    pipe = UnderstandingPipeline()
    seen["pipe"] = pipe
    pipe.transcribe_midi(source, "stage")
    assert pipe.job is not None
    assert pipe.job.quantization is not None
    assert pipe.job.quantization.engine == "performance"
    assert pipe.job.notation.quantization_mode == "performance"
    assert pipe.notation.last_quantization_mode.value == "performance"


def test_independent_jobs_keep_distinct_note_provenance(tmp_path):
    import mido
    from mir.pipeline import UnderstandingPipeline

    def _write(path, pitch):
        midi = mido.MidiFile(ticks_per_beat=480)
        track = mido.MidiTrack()
        midi.tracks.append(track)
        track.extend(
            [
                mido.MetaMessage("set_tempo", tempo=500000),
                mido.Message("note_on", note=pitch, velocity=80, time=0),
                mido.Message("note_off", note=pitch, time=480),
            ]
        )
        midi.save(path)

    left = tmp_path / "left.mid"
    right = tmp_path / "right.mid"
    _write(left, 60)
    _write(right, 72)
    a = UnderstandingPipeline()
    b = UnderstandingPipeline()
    a.transcribe_midi(left, "job-a")
    b.transcribe_midi(right, "job-b")
    assert a.job.job_id == "job-a"
    assert b.job.job_id == "job-b"
    assert a.job.mix_notes.notes[0].pitch == 60
    assert b.job.mix_notes.notes[0].pitch == 72
    with pytest.raises(FrozenInstanceError):
        a.job.mix_notes.notes[0].pitch = 1
    assert b.job.mix_notes.notes[0].pitch == 72


def test_quantize_public_entry_ignores_experimental_mode():
    events = [_ev(60, 0.11, 0.37, "q")]
    q = MeasureQuantizer(mode="off")
    out, decisions = q.quantize(events, _meter())
    assert q.last_result.engine == "performance"
    assert q.last_result.experimental is False
    assert all(d.get("reason") != "off_identity" for d in decisions)
    experimental, experimental_decisions = q.quantize_experimental(
        events, _meter(), "off"
    ).as_tuple()
    assert [round(e.start_beat, 4) for e in experimental] == [0.11]
    assert all(d.get("reason") == "off_identity" for d in experimental_decisions)


def test_musical_event_and_last_events_are_immutable_diagnostics():
    events = [_ev(60, 0.0, 1.0, "q")]
    q = MeasureQuantizer()
    result = q.quantize_production(events, _meter())
    with pytest.raises(FrozenInstanceError):
        events[0].pitch = 1
    with pytest.raises(FrozenInstanceError):
        result.events[0].pitch = 1
    snapshot = list(q.last_events)
    q.last_events.clear()
    assert len(q.last_events) == len(snapshot)
    result.events.clear()
    assert len(q.last_events) == len(snapshot)


def test_writer_last_diagnostics_are_derived_copies():
    from notation_engine.writer import NotationWriter

    writer = NotationWriter()
    writer.last_quantized_events = [_ev(60, 0.0, 1.0, "q")]
    writer.last_quantization_summary = {"engine": "performance"}
    events = writer.last_quantized_events
    events.clear()
    summary = writer.last_quantization_summary
    summary["engine"] = "mutated"
    assert len(writer.last_quantized_events) == 1
    assert writer.last_quantization_summary["engine"] == "performance"
