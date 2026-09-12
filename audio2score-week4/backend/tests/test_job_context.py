from mir.job import ImmutableNoteSet, PipelineJob
from mir.quantizer import MeasureQuantizer
from mir.quantizer_compare import compare_quantizers
from mir.models import MeterHypothesis
from mir.pipeline_config import QuantizationMode, is_experimental_quantization
from mir.types import MusicalEvent, NoteEvent
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
    original[0].pitch = 72
    assert frozen.notes[0].pitch == 60
    working = frozen.copy_notes()
    working[0].pitch = 64
    assert frozen.notes[0].pitch == 60
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


def test_production_quantize_ignores_adaptive_mode_on_explicit_production_call():
    events = [_ev(60, 0.0, 1.0, "q")]
    q = MeasureQuantizer(mode="adaptive")
    result = q.quantize_production(events, _meter())
    assert result.engine == "performance"
    assert result.experimental is False
    assert not is_experimental_quantization("performance")
    assert is_experimental_quantization("adaptive")
    assert is_experimental_quantization(QuantizationMode.PM2S)


def test_compare_quantizers_keeps_performance_as_production():
    events = [_ev(64, 0.0, 1.0, "e")]
    report = compare_quantizers(events, _meter(), experimental_modes=("adaptive", "off"))
    assert report["production_engine"] == "performance"
    assert report["production"]["engine"] == "performance"
    assert "adaptive" in report["experimental"]
    assert report["experimental"]["adaptive"]["experimental"] is True
    assert report["experimental"]["off"]["engine"] == "identity"
