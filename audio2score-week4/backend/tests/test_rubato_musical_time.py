from fractions import Fraction
from math import isfinite

import pytest

from mir.cmr_builder import notes_to_events
from mir.models import MeterHypothesis
from mir.quantizer import MeasureQuantizer
from mir.types import NoteEvent, TempoMap, TempoPoint
from timing.service import resolve_from_beat_times
from timing.tempo_map import (
    ROUNDTRIP_TOLERANCE_SEC,
    MusicalTimeMap,
    assert_roundtrip,
    sanitize_beat_times,
)


METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)

# Simple quarters performed with human timing (seconds).
RUBATO_QUARTERS = (0.00, 0.54, 1.03, 1.62, 2.25, 2.82, 3.34, 3.91, 4.50)
RITARDANDO = (0.00, 0.45, 0.95, 1.55, 2.25, 3.10, 4.10, 5.30, 6.70)
ACCELERANDO = (0.00, 0.70, 1.30, 1.80, 2.22, 2.58, 2.88, 3.12, 3.32)


def _notes_at(times, *, pitches=None):
    notes = []
    last = times[-1]
    for i, start in enumerate(times[:-1]):
        end = times[i + 1] - 0.01
        pitch = 60 + (i % 4) if pitches is None else pitches[i]
        notes.append(
            NoteEvent(
                pitch=pitch,
                start_time=start,
                end_time=end,
                velocity=80,
                note_id=f"n{i}",
                source_backend="fixture",
            )
        )
    assert last > times[-2]
    return notes


def _quantize(events):
    quantizer = MeasureQuantizer(mode="performance")
    out, _ = quantizer.quantize(events, METER)
    return out, quantizer.last_report


def test_sanitize_drops_nan_inf_and_duplicates():
    cleaned = sanitize_beat_times([0.0, float("nan"), 0.5, 0.5, float("inf"), 1.2, "x"])
    assert cleaned == [0.0, 0.5, 1.2]


def test_from_beat_times_sanitizes():
    time_map = MusicalTimeMap.from_beat_times([0.0, 0.5, 0.5, 1.0])
    assert time_map.beat_times == (0.0, 0.5, 1.0)


def test_roundtrip_before_between_after_and_tempo_jump():
    times = (0.423, 1.006, 1.614, 2.199, 2.754, 4.5)
    time_map = MusicalTimeMap.from_beat_times(times)
    samples = [0.1, 0.423, 0.8, 1.006, 1.3, 2.754, 5.0, 18.351]
    assert_roundtrip(time_map, samples, tol=ROUNDTRIP_TOLERANCE_SEC)
    assert all(isfinite(time_map.seconds_to_beats(t)) for t in samples)
    with pytest.raises(ValueError):
        time_map.seconds_to_beats(float("nan"))


def test_notes_to_events_uses_both_endpoints_under_rubato():
    time_map = MusicalTimeMap.from_beat_times(RUBATO_QUARTERS)
    notes = _notes_at(RUBATO_QUARTERS)
    events = notes_to_events(notes, time_map)
    starts = [round(e.start_beat, 6) for e in events]
    assert starts == [float(i) for i in range(8)]
    assert all(0.9 < e.duration_beats < 1.0 for e in events)


def test_eighths_triplets_rit_accel_map_to_musical_grid():
    quarters = MusicalTimeMap.from_beat_times(RUBATO_QUARTERS)
    eighth_times = [quarters.beats_to_seconds(i * 0.5) for i in range(17)]
    eighths = notes_to_events(_notes_at(eighth_times), quarters)
    assert [round(e.start_beat, 6) for e in eighths] == [i * 0.5 for i in range(16)]

    trips = [quarters.beats_to_seconds(i / 3) for i in range(13)]
    trip_events = notes_to_events(_notes_at(trips), quarters)
    assert [round(e.start_beat, 6) for e in trip_events] == [round(i / 3, 6) for i in range(12)]

    rit = MusicalTimeMap.from_beat_times(RITARDANDO)
    rit_events = notes_to_events(_notes_at(RITARDANDO), rit)
    assert [round(e.start_beat, 6) for e in rit_events] == [float(i) for i in range(8)]

    acc = MusicalTimeMap.from_beat_times(ACCELERANDO)
    acc_events = notes_to_events(_notes_at(ACCELERANDO), acc)
    assert [round(e.start_beat, 6) for e in acc_events] == [float(i) for i in range(8)]


def test_local_delay_does_not_shift_the_grid():
    grid = MusicalTimeMap.from_bpm(120, duration_sec=6.0)
    notes = []
    for i in range(8):
        start = grid.beats_to_seconds(float(i))
        if i == 3:
            start += 0.07
        notes.append(
            NoteEvent(
                pitch=72,
                start_time=start,
                end_time=grid.beats_to_seconds(float(i) + 0.9),
                velocity=80,
                note_id=str(i),
            )
        )
    events = notes_to_events(notes, grid)
    beats = [e.start_beat for e in events]
    assert abs(beats[2] - 2.0) < 1e-9
    assert abs(beats[4] - 4.0) < 1e-9
    assert 3.10 < beats[3] < 3.20
    _, report = _quantize(events)
    onsets = [n.onset for n in report.notes]
    assert onsets[2] == Fraction(2, 1)
    assert onsets[4] == Fraction(4, 1)
    assert onsets[0] == Fraction(0, 1)
    assert onsets[-1] == Fraction(7, 1)


def test_beat_map_recovers_quarters_where_constant_bpm_fails():
    notes = _notes_at(RUBATO_QUARTERS)
    time_map = MusicalTimeMap.from_beat_times(RUBATO_QUARTERS)
    new_events = notes_to_events(notes, time_map)
    _, new_report = _quantize(new_events)
    assert [n.onset for n in new_report.notes] == [Fraction(i, 1) for i in range(8)]
    assert [n.duration for n in new_report.notes] == [Fraction(1, 1) for i in range(8)]

    span = RUBATO_QUARTERS[-2] - RUBATO_QUARTERS[0]
    bpm = 7 * 60.0 / span
    old_map = TempoMap(points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=bpm)])
    old_events = notes_to_events(notes, old_map)
    _, old_report = _quantize(old_events)
    assert [n.onset for n in old_report.notes] != [Fraction(i, 1) for i in range(8)]


def test_source_seconds_are_not_mutated():
    notes = _notes_at(RUBATO_QUARTERS)
    before = [(n.note_id, n.pitch, n.start_time, n.end_time) for n in notes]
    notes_to_events(notes, MusicalTimeMap.from_beat_times(RUBATO_QUARTERS))
    assert [(n.note_id, n.pitch, n.start_time, n.end_time) for n in notes] == before


def test_pipeline_midi_writes_tempo_json_and_keeps_raw_bytes(tmp_path):
    import hashlib
    import pretty_midi

    from mir.pipeline import UnderstandingPipeline
    from mir.raw_midi import job_raw_midi_path, job_score_midi_path, job_validated_midi_path

    src = tmp_path / "probe.mid"
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(0, name="Piano")
    inst.notes = [pretty_midi.Note(80, 60 + i, i * 0.5, i * 0.5 + 0.4) for i in range(8)]
    midi.instruments.append(inst)
    midi.write(str(src))
    original = src.read_bytes()
    pipe = UnderstandingPipeline()
    xml = pipe.transcribe_midi(src, "tempo_job")
    assert "score-partwise" in xml
    assert job_raw_midi_path(src, "tempo_job").read_bytes() == original
    assert job_validated_midi_path(src, "tempo_job").read_bytes() == original
    score = job_score_midi_path(src, "tempo_job").read_bytes()
    assert hashlib.sha256(score).hexdigest() != hashlib.sha256(original).hexdigest()
    tempo_path = src.parent / "bp_tempo_job" / "tempo_job.tempo.json"
    assert tempo_path.exists()
    import json

    payload = json.loads(tempo_path.read_text())
    assert payload["backend_used"] == "midi_file"
    assert payload["fallback_used"] is False
    assert len(payload["beat_times"]) >= 2
    assert pipe.last_musical_time_map is not None
    assert payload["quality"]["confidence"] is None


def test_timing_resolution_records_fallback():
    result = resolve_from_beat_times([0.0], duration_sec=2.0)
    assert result.fallback_used
    assert result.quality.confidence is None
    assert result.quality.beat_count >= 2
    assert result.quality.median_bpm is not None

