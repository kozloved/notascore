"""Adaptive notation quantizer: raw vs notation, chords, patterns, triplets."""

from __future__ import annotations

import pretty_midi
import pytest

from mir.adaptive_quantizer import (
    QuantizerIdentityError,
    _choose_duration,
    _raw_by_id,
    restore_identity,
    validate_identity_invariants,
)
from mir.models import MeterHypothesis, PlannedNote, PlannedRest
from mir.pipeline import UnderstandingPipeline
from mir.quantizer import MeasureQuantizer, QuantizerConfig
from mir.types import Hand, MusicalEvent, ScoreMeta, copy_event
from notation_engine.plan import NotationPlanner


def _ev(pitch, start, dur, hand=Hand.RIGHT, velocity=80, **kwargs):
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        hand=hand,
        voice=0,
        velocity=velocity,
        **kwargs,
    )


def _meter_44():
    return MeterHypothesis(
        time_signature="4/4",
        numerator=4,
        denominator=4,
        measure_quarter_length=4.0,
        score=1.0,
        confidence=1.0,
    )


def _meter_68():
    return MeterHypothesis(
        time_signature="6/8",
        numerator=6,
        denominator=8,
        measure_quarter_length=3.0,
        score=1.0,
        confidence=1.0,
    )


def _by_id(events):
    return {e.note_id: e for e in events}


def _starts(events):
    return [round(e.start_beat, 6) for e in sorted(events, key=lambda e: (e.start_beat, e.pitch))]


QUALITY_METRIC_KEYS = (
    "mean_onset_displacement",
    "mean_duration_displacement",
    "max_onset_displacement",
    "max_duration_displacement",
    "notes_moved",
    "notes_preserved",
    "chord_alignments",
    "triplet_groups",
    "tiny_rests",
    "invalid_duration_events",
    "measure_violations",
    "overlaps_detected",
    "fallback_preserved",
    "identity_valid",
    "duplicate_note_ids",
    "pitch_mismatches",
    "velocity_mismatches",
    "notes_shortened_for_overlap",
    "notes_preserved_duration",
    "barline_splits_required",
)


def test_raw_events_remain_unchanged_after_quantization():
    events = [
        _ev(60, 0.03, 0.47, note_id="a"),
        _ev(64, 0.07, 0.44, note_id="b"),
        _ev(67, 0.51, 0.48, note_id="c"),
    ]
    original = [(e.note_id, e.pitch, e.start_beat, e.duration_beats) for e in events]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    after = [(e.note_id, e.pitch, e.start_beat, e.duration_beats) for e in events]
    assert after == original
    raw_snap = [
        (e.note_id, e.pitch, e.start_beat, e.duration_beats) for e in q.last_raw_events
    ]
    assert raw_snap == original
    assert q.last_notation_events is not q.last_raw_events
    assert [e.start_beat for e in q.last_notation_events] != [
        e.start_beat for e in q.last_raw_events
    ] or [e.duration_beats for e in q.last_notation_events] != [
        e.duration_beats for e in q.last_raw_events
    ]
    assert len(notation) == len(events)


def test_quantization_produces_separate_notation_representation():
    events = [_ev(72, i * 0.5 + 0.04, 0.46, note_id=f"n{i}") for i in range(8)]
    q = MeasureQuantizer(mode="adaptive")
    notation, decisions = q.quantize(events, _meter_44())
    assert q.last_raw_events
    assert q.last_notation_events
    assert [id(e) for e in q.last_raw_events] != [id(e) for e in q.last_notation_events]
    assert all(d.get("quantized_start") is not None for d in decisions)
    starts = [round(e.start_beat, 6) for e in notation]
    assert starts[0] == 0.0
    assert all(abs(b - a - 0.5) < 0.02 for a, b in zip(starts, starts[1:]))


def test_chord_notes_remain_aligned():
    events = [
        _ev(60, 0.000, 1.0, note_id="c", hand=Hand.LEFT),
        _ev(64, 0.031, 0.95, note_id="e"),
        _ev(67, 0.048, 0.92, note_id="g"),
        _ev(72, 0.055, 0.90, note_id="c2"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    starts = {round(e.start_beat, 6) for e in notation}
    assert len(starts) == 1
    assert list(starts)[0] == 0.0


def test_repeated_eighth_pattern_stays_consistent():
    # Performance jitter around a repeated eighth pulse — not sixteenths.
    raw_starts = [0.00, 0.52, 0.97, 1.48, 2.03, 2.49, 3.02, 3.47]
    events = [
        _ev(72, s, 0.42, note_id=f"n{i}") for i, s in enumerate(raw_starts)
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    starts = [round(e.start_beat, 6) for e in notation]
    expected = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
    assert starts == expected
    assert q.last_summary.get("triplet_decisions", 0) == 0


def test_triplets_recognized_only_when_justified():
    meter = _meter_44()
    # One slightly late eighth must not become a triplet grid.
    eighths = [
        _ev(72, 0.0, 0.5, note_id="a"),
        _ev(74, 0.5, 0.5, note_id="b"),
        _ev(76, 1.0, 0.5, note_id="c"),
        _ev(77, 1.33, 0.5, note_id="d"),  # closer to 1/3 of beat 1, still one outlier
        _ev(79, 2.0, 0.5, note_id="e"),
        _ev(81, 2.5, 0.5, note_id="f"),
        _ev(83, 3.0, 0.5, note_id="g"),
        _ev(84, 3.5, 0.5, note_id="h"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    outlier, _ = q.quantize(eighths, meter)
    by_id = {e.note_id: e for e in outlier}
    assert abs((by_id["d"].start_beat * 3) - round(by_id["d"].start_beat * 3)) > 0.05 or round(
        by_id["d"].start_beat, 3
    ) in (1.25, 1.5, 1.0)
    assert q.last_summary.get("triplet_decisions", 0) == 0

    genuine = [
        _ev(72, 0.0, 1.0 / 3.0, note_id="a"),
        _ev(74, 1.0 / 3.0, 1.0 / 3.0, note_id="b"),
        _ev(76, 2.0 / 3.0, 1.0 / 3.0, note_id="c"),
        _ev(77, 1.0, 1.0 / 3.0, note_id="d"),
        _ev(79, 4.0 / 3.0, 1.0 / 3.0, note_id="e"),
        _ev(81, 5.0 / 3.0, 1.0 / 3.0, note_id="f"),
    ]
    q2 = MeasureQuantizer(mode="adaptive")
    tripped, _ = q2.quantize(genuine, meter)
    third_like = sum(
        1 for e in tripped if abs((e.start_beat * 3) - round(e.start_beat * 3)) < 0.05
    )
    assert third_like >= 4


def test_tiny_rests_and_odd_durations_are_cleaned():
    events = [
        _ev(72, 0.0, 0.47, note_id="a"),
        _ev(74, 0.50, 0.47, note_id="b"),
        _ev(76, 1.0, 0.47, note_id="c"),
        _ev(77, 1.5, 0.47, note_id="d"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    durs = [round(e.duration_beats, 6) for e in notation]
    assert all(abs(d - 0.5) < 0.02 for d in durs)
    assert not any(abs(d - 0.47) < 1e-9 for d in durs)

    plan, _ = NotationPlanner().build(
        events,
        meta=ScoreMeta(display_tempo_bpm=120, time_sig_hint="4/4"),
        quantization_mode="adaptive",
    )
    rests = [
        el
        for measure in plan.measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedRest)
    ]
    tiny = [r for r in rests if 0 < r.duration_q < 0.2]
    assert tiny == []


def test_bar_boundaries_remain_musically_valid():
    meter = _meter_44()
    events = [
        _ev(60, 0.0, 1.0, note_id="a"),
        _ev(62, 1.0, 1.0, note_id="b"),
        _ev(64, 2.0, 1.0, note_id="c"),
        _ev(65, 3.0, 1.0, note_id="d"),
        _ev(67, 3.996, 1.0, note_id="e"),
        _ev(69, 5.0, 1.0, note_id="f"),
        _ev(71, 6.0, 1.0, note_id="g"),
        _ev(72, 7.0, 1.0, note_id="h"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, meter)
    by_id = {e.note_id: e for e in notation}
    assert abs(by_id["e"].start_beat - 4.0) < 0.02
    # Downbeat of bar 2 must not also exist as a last-16th of bar 1.
    assert by_id["e"].start_beat >= 4.0 - 1e-9
    held = [_ev(72, 3.0, 2.0, note_id="hold")]
    q2 = MeasureQuantizer(mode="adaptive")
    held_out, _ = q2.quantize(held, meter)
    assert abs(held_out[0].start_beat - 3.0) < 0.02
    assert held_out[0].duration_beats >= 1.9


def test_pipeline_keeps_raw_midi_and_quantizes_notation(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "adaptive")
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    # Jittered C-major chord then eighths.
    for pitch, start in ((60, 0.00), (64, 0.03), (67, 0.05)):
        inst.notes.append(
            pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=start + 0.45)
        )
    for i, pitch in enumerate((72, 74, 76, 77)):
        start = 0.5 + i * 0.5 + 0.03
        inst.notes.append(
            pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=start + 0.4)
        )
    midi.instruments.append(inst)
    path = tmp_path / "fixture.mid"
    midi.write(str(path))

    pipe = UnderstandingPipeline()
    xml = pipe.transcribe(path, "raw-vs-notation")
    assert "score-partwise" in xml.lower()
    assert pipe.last_raw_notes is not None
    assert pipe.last_notation_notes is not None
    assert pipe.last_quantized_events is not None
    raw_starts = [round(n.start_time, 4) for n in pipe.last_raw_notes]
    assert 0.03 in raw_starts or any(abs(t - 0.03) < 1e-3 for t in raw_starts)
    raw_midi = tmp_path / "bp_raw-vs-notation" / "raw-vs-notation.raw.mid"
    score_midi = tmp_path / "bp_raw-vs-notation" / "raw-vs-notation.score.mid"
    assert raw_midi.exists()
    assert score_midi.exists()
    raw_pm = pretty_midi.PrettyMIDI(str(raw_midi))
    raw_pm_starts = sorted(
        round(n.start, 3) for inst in raw_pm.instruments for n in inst.notes
    )
    assert any(abs(t - 0.03) < 0.02 for t in raw_pm_starts)
    q_starts = [e.start_beat for e in pipe.last_notation_notes]
    chord = [e for e in pipe.last_notation_notes if e.pitch in (60, 64, 67)]
    assert pipe.job is not None
    assert pipe.job.quantization.engine == "performance"
    assert pipe.notation.last_quantization_mode.value == "performance"
    if len(chord) >= 3:
        chord_starts = {round(e.start_beat, 6) for e in chord}
        # Adaptive env must not collapse distinct attacks on the product path.
        assert len(chord_starts) >= 2
    planner = NotationPlanner()
    plan, _ = planner.build(
        list(pipe.last_quantized_events),
        meta=ScoreMeta(display_tempo_bpm=120, time_sig_hint="4/4"),
        quantization_mode="off",
    )
    notes = [
        el
        for measure in plan.measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedNote)
    ]
    assert notes
    assert all(el.duration_q >= 0.25 - 1e-9 for el in notes)


def test_short_gap_duration_never_overflows_next_onset():
    """Remaining space 0.10 must not become a 0.25 note ending at 2.15."""
    d = _choose_duration(
        target=0.5,
        cap=0.10,
        tuplet_ok=False,
        absorb=0.12,
        orig_crosses=False,
        measure_remaining=2.10,
        complexity_weight=0.35,
        tuplet_weight=0.55,
        rest_weight=0.7,
        tie_weight=0.2,
    )
    assert 0 < d <= 0.10 + 1e-9

    events = [
        _ev(72, 1.90, 0.50, note_id="a"),
        _ev(72, 2.00, 0.50, note_id="b"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    by_id = _by_id(notation)
    assert set(by_id) == {"a", "b"}
    assert by_id["a"].pitch == 72 and by_id["b"].pitch == 72
    assert by_id["a"].start_beat <= by_id["b"].start_beat + 1e-9
    if by_id["a"].start_beat < by_id["b"].start_beat - 1e-9:
        assert (
            by_id["a"].start_beat + by_id["a"].duration_beats
            <= by_id["b"].start_beat + 1e-6
        )
        assert by_id["a"].duration_beats <= 0.25 + 1e-9
        assert abs(
            (by_id["a"].start_beat + by_id["a"].duration_beats) - 2.15
        ) > 0.02 or by_id["a"].start_beat < 1.85
    assert by_id["a"].duration_beats > 0
    assert by_id["b"].duration_beats > 0


def test_identity_count_pitch_velocity_and_ids_preserved():
    events = [
        _ev(60, 0.03, 0.47, note_id="a", velocity=71),
        _ev(64, 0.51, 0.44, note_id="b", velocity=90),
        _ev(67, 1.02, 0.40, note_id="c", velocity=64),
        _ev(48, 0.04, 1.90, hand=Hand.LEFT, note_id="d", velocity=55),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    assert len(notation) == len(events)
    raw_ids = [e.note_id for e in events]
    out_ids = [e.note_id for e in notation]
    assert sorted(out_ids) == sorted(raw_ids)
    by_raw = _by_id(events)
    by_out = _by_id(notation)
    for nid in raw_ids:
        assert by_out[nid].pitch == by_raw[nid].pitch
        assert by_out[nid].velocity == by_raw[nid].velocity
        assert by_out[nid].duration_beats > 0


def test_quality_metrics_are_reported():
    events = [_ev(72, i * 0.5 + 0.03, 0.44, note_id=f"n{i}") for i in range(4)]
    q = MeasureQuantizer(mode="adaptive")
    q.quantize(events, _meter_44())
    for key in QUALITY_METRIC_KEYS:
        assert key in q.last_summary
    assert q.last_summary["notes_preserved"] == 4
    assert q.last_summary["events_removed"] == 0
    assert q.last_summary["overlaps_detected"] == 0
    assert q.last_summary["measure_violations"] == 0
    assert q.last_summary["invalid_duration_events"] == 0
    assert q.last_summary["mean_onset_displacement"] >= 0
    assert q.last_summary["max_onset_displacement"] >= q.last_summary["mean_onset_displacement"]


def test_a_jittered_eighths_use_consistent_grid():
    raw_starts = [0.01, 0.51, 0.99, 1.49, 2.01]
    events = [_ev(72, s, 0.42, note_id=f"n{i}") for i, s in enumerate(raw_starts)]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    assert _starts(notation) == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert q.last_summary.get("triplet_decisions", 0) == 0


def test_b_jittered_sixteenths_use_sixteenth_grid():
    raw_starts = [0.00, 0.26, 0.49, 0.76, 1.01, 1.24, 1.51, 1.74]
    events = [_ev(71, s, 0.20, note_id=f"s{i}") for i, s in enumerate(raw_starts)]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    starts = _starts(notation)
    expected = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75]
    assert starts == expected
    assert q.last_summary.get("triplet_decisions", 0) == 0


def test_c_genuine_triplets_selected():
    events = [
        _ev(72, i / 3.0, 1.0 / 3.0, note_id=f"t{i}") for i in range(6)
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    third_like = sum(
        1 for e in notation if abs((e.start_beat * 3) - round(e.start_beat * 3)) < 0.05
    )
    assert third_like >= 5
    assert q.last_summary.get("triplet_groups", 0) >= 1
    durs = [e.duration_beats for e in notation]
    assert all(abs(d - (1.0 / 3.0)) < 0.05 for d in durs)


def test_d_binary_passage_with_one_late_note_stays_binary():
    events = [
        _ev(72, 0.0, 0.5, note_id="a"),
        _ev(74, 0.5, 0.5, note_id="b"),
        _ev(76, 1.0, 0.5, note_id="c"),
        _ev(77, 1.58, 0.5, note_id="d"),  # late eighth, not a triplet cell
        _ev(79, 2.0, 0.5, note_id="e"),
        _ev(81, 2.5, 0.5, note_id="f"),
        _ev(83, 3.0, 0.5, note_id="g"),
        _ev(84, 3.5, 0.5, note_id="h"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    by_id = _by_id(notation)
    assert round(by_id["a"].start_beat, 3) == 0.0
    assert round(by_id["b"].start_beat, 3) == 0.5
    assert round(by_id["c"].start_beat, 3) == 1.0
    assert round(by_id["d"].start_beat, 3) in (1.5, 1.75)
    assert q.last_summary.get("triplet_decisions", 0) == 0


def test_e_staggered_chord_aligns():
    events = [
        _ev(60, 0.01, 1.0, note_id="c"),
        _ev(64, 0.04, 0.97, note_id="e"),
        _ev(67, 0.06, 0.94, note_id="g"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    starts = {round(e.start_beat, 6) for e in notation}
    assert starts == {0.0}
    assert q.last_summary["chord_alignments"] >= 1


def test_f_sustained_note_crossing_barline_keeps_tie():
    events = [_ev(72, 3.0, 2.0, note_id="hold")]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    assert abs(notation[0].start_beat - 3.0) < 0.02
    assert notation[0].duration_beats >= 1.9
    plan, _ = NotationPlanner().build(
        events,
        meta=ScoreMeta(display_tempo_bpm=120, time_sig_hint="4/4"),
        quantization_mode="adaptive",
    )
    notes = [
        el
        for measure in plan.measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedNote)
    ]
    assert any(n.tie for n in notes)
    assert len(plan.measures) >= 2


def test_g_very_short_gap_has_no_pathological_tiny_rest():
    events = [
        _ev(72, 0.0, 0.48, note_id="a"),
        _ev(74, 0.50, 0.48, note_id="b"),
        _ev(76, 1.00, 0.48, note_id="c"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    ordered = sorted(notation, key=lambda e: e.start_beat)
    for a, b in zip(ordered, ordered[1:]):
        gap = b.start_beat - (a.start_beat + a.duration_beats)
        assert gap <= 1e-6 or gap >= 0.2
    plan, _ = NotationPlanner().build(
        events,
        meta=ScoreMeta(display_tempo_bpm=120, time_sig_hint="4/4"),
        quantization_mode="adaptive",
    )
    rests = [
        el
        for measure in plan.measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedRest)
    ]
    assert [r for r in rests if 0 < r.duration_q < 0.2] == []
    assert q.last_summary["tiny_rests"] == 0


def test_h_notes_near_barline_assigned_to_correct_measure():
    events = [
        _ev(60, 0.0, 1.0, note_id="a"),
        _ev(62, 1.0, 1.0, note_id="b"),
        _ev(64, 2.0, 1.0, note_id="c"),
        _ev(65, 3.0, 0.75, note_id="d"),
        _ev(67, 3.996, 1.0, note_id="early_downbeat"),
        _ev(69, 3.75, 0.25, note_id="last_sixteenth"),
        _ev(71, 5.0, 1.0, note_id="f"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    by_id = _by_id(notation)
    assert by_id["early_downbeat"].start_beat >= 4.0 - 1e-9
    assert abs(by_id["early_downbeat"].start_beat - 4.0) < 0.02
    assert abs(by_id["last_sixteenth"].start_beat - 3.75) < 0.02
    assert by_id["last_sixteenth"].start_beat < 4.0 - 1e-9


def test_i_compound_six_eight_uses_eighth_pulse():
    raw_starts = [0.02, 0.51, 0.98, 1.52, 1.99, 2.48]
    events = [_ev(72, s, 0.42, note_id=f"n{i}") for i, s in enumerate(raw_starts)]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_68())
    assert _starts(notation) == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    assert q.last_summary.get("triplet_decisions", 0) == 0
    for ev in notation:
        assert ev.start_beat < 3.0 - 1e-9


def test_j_polyphonic_voices_independent_chords_aligned():
    events = [
        _ev(72, 0.01, 1.0, hand=Hand.RIGHT, note_id="rh_c"),
        _ev(76, 0.04, 1.0, hand=Hand.RIGHT, note_id="rh_e"),
        _ev(48, 0.00, 0.5, hand=Hand.LEFT, note_id="lh0"),
        _ev(50, 0.51, 0.5, hand=Hand.LEFT, note_id="lh1"),
        _ev(52, 0.99, 0.5, hand=Hand.LEFT, note_id="lh2"),
        _ev(53, 1.49, 0.5, hand=Hand.LEFT, note_id="lh3"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    by_id = _by_id(notation)
    assert round(by_id["rh_c"].start_beat, 6) == round(by_id["rh_e"].start_beat, 6)
    lh = [by_id[k].start_beat for k in ("lh0", "lh1", "lh2", "lh3")]
    expected_lh = [0.0, 0.5, 1.0, 1.5]
    assert [round(s, 6) for s in lh] == expected_lh
    assert len(notation) == 6
    assert q.last_summary["overlaps_detected"] == 0


def test_k_extreme_timing_is_not_dragged_onto_a_distant_grid():
    events = [
        _ev(72, 0.0, 1.0, note_id="a"),
        _ev(74, 1.0, 1.0, note_id="b"),
        _ev(76, 2.0, 1.0, note_id="c"),
        _ev(77, 2.40, 0.5, note_id="outlier"),
        _ev(79, 3.0, 1.0, note_id="e"),
    ]
    q = MeasureQuantizer(
        mode="adaptive", config=QuantizerConfig(max_onset_move=0.18)
    )
    notation, _ = q.quantize(events, _meter_44())
    outlier = _by_id(notation)["outlier"]
    assert abs(outlier.start_beat - 2.40) <= 0.18 + 1e-9
    assert abs(outlier.start_beat - 2.0) > 0.15
    assert abs(outlier.start_beat - 3.0) > 0.15


def test_identity_restored_after_notation_reorder():
    raw = [
        _ev(60, 0.03, 0.90, note_id="a", velocity=71),
        _ev(64, 0.50, 0.40, note_id="b", velocity=90),
        _ev(67, 1.02, 0.40, note_id="c", velocity=64),
    ]
    reordered = [
        copy_event(raw[2], start_beat=1.0, duration_beats=0.5, pitch=1, velocity=2),
        copy_event(raw[0], start_beat=0.0, duration_beats=1.0, pitch=3, velocity=4),
        copy_event(raw[1], start_beat=0.5, duration_beats=0.5, pitch=5, velocity=6),
    ]
    restored = restore_identity(raw, reordered)
    by_id = _by_id(restored)
    assert by_id["a"].pitch == 60 and by_id["a"].velocity == 71
    assert by_id["b"].pitch == 64 and by_id["b"].velocity == 90
    assert by_id["c"].pitch == 67 and by_id["c"].velocity == 64
    assert abs(by_id["a"].start_beat - 0.0) < 1e-9
    assert abs(by_id["b"].start_beat - 0.5) < 1e-9
    assert abs(by_id["c"].start_beat - 1.0) < 1e-9
    assert abs(by_id["a"].duration_beats - 1.0) < 1e-9


def test_duplicate_raw_note_id_raises():
    raw = [
        _ev(60, 0.0, 1.0, note_id="a", velocity=70),
        _ev(64, 1.0, 1.0, note_id="a", velocity=80),
    ]
    with pytest.raises(QuantizerIdentityError, match="duplicate"):
        _raw_by_id(raw)
    with pytest.raises(QuantizerIdentityError, match="duplicate"):
        restore_identity(raw, raw)


def test_missing_notation_note_id_fails_invariants():
    raw = [
        _ev(60, 0.0, 1.0, note_id="a", velocity=70),
        _ev(64, 1.0, 1.0, note_id="b", velocity=80),
    ]
    notation = [_ev(60, 0.0, 1.0, note_id="a", velocity=70)]
    with pytest.raises(QuantizerIdentityError):
        validate_identity_invariants(raw, notation)


def test_extra_notation_note_id_fails_invariants():
    raw = [
        _ev(60, 0.0, 1.0, note_id="a", velocity=70),
        _ev(64, 1.0, 1.0, note_id="b", velocity=80),
    ]
    notation = [
        _ev(60, 0.0, 1.0, note_id="a", velocity=70),
        _ev(64, 1.0, 1.0, note_id="b", velocity=80),
        _ev(67, 2.0, 1.0, note_id="c", velocity=81),
    ]
    with pytest.raises(QuantizerIdentityError):
        validate_identity_invariants(raw, notation)


def test_pitch_mismatch_fails_invariants():
    raw = [_ev(60, 0.0, 1.0, note_id="a", velocity=70)]
    notation = [_ev(61, 0.0, 1.0, note_id="a", velocity=70)]
    with pytest.raises(QuantizerIdentityError, match="pitch"):
        validate_identity_invariants(raw, notation)


def test_velocity_mismatch_fails_invariants():
    raw = [_ev(60, 0.0, 1.0, note_id="a", velocity=70)]
    notation = [_ev(60, 0.0, 1.0, note_id="a", velocity=99)]
    with pytest.raises(QuantizerIdentityError, match="velocity"):
        validate_identity_invariants(raw, notation)


def test_genuine_overlap_is_not_cleaned_by_quantizer():
    events = [
        _ev(72, 0.0, 1.0, note_id="held", velocity=80),
        _ev(76, 0.5, 1.0, note_id="entry", velocity=81),
    ]
    original = [
        (e.note_id, e.pitch, e.start_beat, e.duration_beats, e.velocity) for e in events
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    after = [
        (e.note_id, e.pitch, e.start_beat, e.duration_beats, e.velocity) for e in events
    ]
    assert after == original
    by_id = _by_id(notation)
    held = by_id["held"]
    entry = by_id["entry"]
    assert held.pitch == 72 and held.velocity == 80
    assert entry.pitch == 76 and entry.velocity == 81
    assert held.start_beat + held.duration_beats > entry.start_beat + 0.25
    assert abs(held.duration_beats - 1.0) <= 0.06
    assert q.last_summary["notes_shortened_for_overlap"] == 0
    assert q.last_summary["identity_valid"] is True
    assert q.last_summary["events_removed"] == 0


def test_barline_crossing_duration_is_preserved_for_ties():
    events = [_ev(72, 3.0, 2.0, note_id="hold", velocity=88)]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    hold = notation[0]
    assert hold.note_id == "hold"
    assert hold.pitch == 72 and hold.velocity == 88
    assert abs(hold.start_beat - 3.0) < 0.02
    assert abs(hold.duration_beats - 2.0) <= 0.06
    assert hold.start_beat + hold.duration_beats > 4.0 + 1e-9
    assert q.last_summary["barline_splits_required"] >= 1
    assert q.last_summary["measure_violations"] == 0


def test_fallback_preserved_does_not_double_count_cluster_members():
    from mir.adaptive_quantizer import ChordCluster, RhythmicAnalysis, quality_metrics

    raw = [_ev(72, 0.40, 0.5, note_id="a")]
    notation = [_ev(72, 0.40, 0.5, note_id="a")]
    analysis = RhythmicAnalysis(
        clusters=[
            ChordCluster(indices=[0], raw_onset=0.40, preserved=True),
        ]
    )
    decisions = [
        {
            "note_id": "a",
            "quantized_start": 0.40,
            "raw_start": 0.40,
            "quantized_duration": 0.5,
            "raw_duration": 0.5,
            "preserved_timing": True,
        }
    ]
    metrics = quality_metrics(raw, notation, analysis, decisions)
    assert metrics["fallback_preserved"] == 1


def test_measure_violations_count_invented_barline_overflow_not_zero_durations():
    from mir.adaptive_quantizer import RhythmicAnalysis, quality_metrics

    raw = [_ev(72, 3.0, 0.5, note_id="inside")]
    notation = [_ev(72, 3.0, 2.0, note_id="inside")]
    metrics = quality_metrics(raw, notation, RhythmicAnalysis(), [])
    assert metrics["measure_violations"] == 1
    assert metrics["invalid_duration_events"] == 0

    zero = [_ev(72, 0.0, 0.0, note_id="z")]
    zero_metrics = quality_metrics(zero, zero, RhythmicAnalysis(), [])
    assert zero_metrics["invalid_duration_events"] == 1
    assert zero_metrics["measure_violations"] == 0
