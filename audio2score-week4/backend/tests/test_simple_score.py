"""Musician-facing regressions: simple rhythm without erasing real detail."""

from copy import deepcopy
from fractions import Fraction
from types import SimpleNamespace

import pytest
from music21 import converter

from mir.cmr_builder import notes_to_events
from mir.hand_separator import HandSeparator
from mir.models import MeterHypothesis, PlannedNote, PlannedRest
from mir.performance_score import assign_pipeline_layout
from mir.quantizer import MeasureQuantizer
from mir.score_profile import score_profile
from mir.types import Hand, MusicalEvent, NoteEvent, ScoreMeta, TempoMap, TempoPoint
from mir.voice_separator import VoiceSeparator
from notation_engine.plan import NotationPlanner, validate_voice_timeline
from notation_engine.writer import NotationWriter
from timing.printed_tempo import printed_tempo_annotations
from timing.service import resolve_from_existing_tracker
from timing.tempo_map import MusicalTimeMap, assert_roundtrip

METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)


def simple_phrase():
    return [MusicalEvent(pitch, i + 0.05, duration, note_id=f"{i}:{pitch}",
                        hand=Hand.RIGHT, hand_locked=True, velocity=80)
            for i in range(8) for pitch, duration in ((60, 0.93), (67, 0.99))]


def planned(events):
    events = assign_pipeline_layout(events, score_profile(events), HandSeparator(), VoiceSeparator())
    return NotationPlanner().build(events, meta=ScoreMeta(time_sig_hint="4/4"),
                                   quantization_mode="performance")[0]


def test_jittered_dyads_are_quarter_chords_without_micro_rests(tmp_path):
    source = simple_phrase()
    before = deepcopy(source)
    plan = planned(source)
    assert source == before
    notes = []
    for measure in plan.measures:
        staff = measure.staves[0]
        assert len(staff.voices) == 1
        elements = staff.voices[0].elements
        assert not validate_voice_timeline(elements, measure.duration_beats)
        assert not any(isinstance(e, PlannedRest) for e in elements)
        notes.extend(elements)
    assert len(notes) == 8
    assert all(n.duration_q == 1 and n.tie is None and n.tuplet is None for n in notes)
    assert all(sorted(n.pitches) == [60, 67] for n in notes)
    writer = NotationWriter()
    path = tmp_path / "simple.musicxml"
    writer._export_musicxml(writer.score_from_plan(plan), path)
    reparsed = converter.parse(path)
    assert len(list(reparsed.parts[0].flatten().notes)) == 8
    assert "<time-modification>" not in path.read_text()
    assert "<accidental>natural</accidental>" not in path.read_text()


def test_offbeats_sixteenths_and_real_short_rests_survive():
    starts = [0.5, 1.25, 2.5, 3.25]
    source = [MusicalEvent(72, s, 0.25, note_id=str(i), hand=Hand.RIGHT)
              for i, s in enumerate(starts)]
    q = MeasureQuantizer(mode="performance")
    out, _ = q.quantize(source, METER)
    assert [e.start_beat for e in out] == starts
    assert all(e.duration_beats == 0.25 for e in out)
    plan = planned(source)
    assert any(isinstance(e, PlannedRest) and e.duration_q == Fraction(1, 2)
               for e in plan.measures[0].staves[0].voices[0].elements)


def test_chord_accidental_cancellation_is_still_printed(tmp_path):
    events = [MusicalEvent(p, i, 1, note_id=f"{i}:{p}", hand=Hand.RIGHT)
              for i, pitches in enumerate(((61, 67), (60, 67))) for p in pitches]
    writer = NotationWriter()
    plan = planned(events)
    plan.key_signature = "C"
    path = tmp_path / "chromatic.musicxml"
    writer._export_musicxml(writer.score_from_plan(plan), path)
    text = path.read_text()
    assert "<accidental>sharp</accidental>" in text
    assert text.count("<accidental>natural</accidental>") == 1


def test_early_pickup_notes_do_not_collapse_to_one_attack():
    grid = MusicalTimeMap.from_beat_times([1.0, 1.5, 2.0, 2.5])
    notes = [NoteEvent(72 + i, s, s + 0.10, note_id=str(i))
             for i, s in enumerate([0.25, 0.50, 0.75, 1.0])]
    events = notes_to_events(notes, grid)
    assert [e.start_beat for e in events] == [0.5, 1.0, 1.5, 2.0]
    assert [e.start_time_sec for e in events] == [0.25, 0.5, 0.75, 1.0]


def test_score_origin_uses_measured_downbeat_without_moving_offbeat():
    # First detected beat is beat 2. First played note is its following offbeat.
    grid = MusicalTimeMap.from_beat_times([0.5, 1.0, 1.5, 2.0, 2.55, 3.1, 3.7, 4.3])
    mapped = grid.for_score(0.75, downbeat_times=[2.0, 4.3], beats_per_bar=4)
    assert mapped.seconds_to_beats(0.75) == 1.5
    assert mapped.seconds_to_beats(2.0) == 4
    assert mapped.seconds_to_beats(4.3) == 8
    assert_roundtrip(mapped, [0.25, 0.75, 2.23, 4.3])
    for a, b in zip(grid.beat_times, grid.beat_times[1:]):
        assert mapped.seconds_to_beats(b) - mapped.seconds_to_beats(a) == pytest.approx(1)


def test_unknown_or_inconsistent_downbeats_do_not_guess_bar_phase():
    grid = MusicalTimeMap.from_beat_times([0, 0.5, 1, 1.5, 2, 2.5])
    assert grid.for_score(0.25) is grid
    assert grid.for_score(0.25, downbeat_times=[0.5, 2], beats_per_bar=4) is grid


def test_audio_pipeline_aligns_only_compatible_meter_evidence():
    from mir.pipeline import UnderstandingPipeline
    from timing.service import resolve_from_beat_times

    pipe = UnderstandingPipeline()
    pipe.beat_tracker.last_beat_result = SimpleNamespace(beats_per_bar=4, downbeat_times=[2, 4])
    timing = resolve_from_beat_times([0.5 + i * 0.5 for i in range(9)])
    notes = [NoteEvent(72, 0.75, 1.25, note_id="offbeat")]
    events = notes_to_events(notes, timing.time_map)
    wrong = MeterHypothesis("3/4", 3, 4, 3.0, 1.0, 1.0)
    unchanged = pipe._align_score_meter(events, notes, timing, wrong)
    assert unchanged[0].start_beat == 0.5
    aligned = pipe._align_score_meter(events, notes, timing, METER)
    assert aligned[0].start_beat == 1.5
    assert timing.time_map.seconds_to_beats(notes[0].start_time) == 1.5
    assert aligned[0].duration_beats == events[0].duration_beats
    assert pipe.last_musical_time_map is timing.time_map


def test_middle_register_phrase_keeps_viterbi_hand_path():
    events = [MusicalEvent(p, float(i), 1, note_id=str(i))
              for i, p in enumerate([60, 59, 60])]
    separator = HandSeparator()
    out = separator.separate(events)
    assert all(e.hand in (Hand.LEFT, Hand.RIGHT) for e in out)
    assert len({e.hand for e in out}) == 1
    assert [e.hand.value for e in out] == [d.selected for d in separator.last_decisions]


def test_single_slow_beat_does_not_print_a_tempo_change():
    series = [(float(i), 70 if i == 12 else 120) for i in range(30)]
    marks = printed_tempo_annotations(series, min_hold_beats=8)
    assert [(m.beat, m.bpm, m.mark) for m in marks] == [(0, 120, "metronome")]


def test_writer_uses_sparse_score_tempi_instead_of_rubato_points():
    source = [MusicalEvent(72, i, 1, note_id=str(i), hand=Hand.RIGHT) for i in range(16)]
    tempo = TempoMap([TempoPoint(i / 2, i, 100 if i % 2 else 120) for i in range(16)])
    meta = ScoreMeta(display_tempo_bpm=120, tempo_map=tempo, time_sig_hint="4/4",
                     extra={"printed_tempo": [{"beat": 0, "bpm": 120, "mark": "metronome"}]})
    score = NotationWriter().write_from_events_direct(source, meta, quantization_mode="performance")
    assert [m.number for m in score.recurse().getElementsByClass("MetronomeMark")] == [120]


def test_reconstructed_grid_is_reported_as_fallback():
    timing = resolve_from_existing_tracker(SimpleNamespace(last_source="librosa"),
        TempoMap([TempoPoint(0, 0, 120)]), duration_sec=4)
    assert timing.fallback_used and timing.quality.fallback_used
    assert "reconstructed" in timing.failure_reason
