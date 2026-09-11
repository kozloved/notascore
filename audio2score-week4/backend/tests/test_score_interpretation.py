"""Interpretation hypotheses: derived score time only. Source identity is fixed."""

from copy import deepcopy
from fractions import Fraction

from mir.hand_separator import HandSeparator
from mir.models import MeterHypothesis, PlannedNote
from mir.performance_score import assign_pipeline_layout, quantize_notation
from mir.quantizer import MeasureQuantizer
from mir.score_interpretation import (
    choose_candidate,
    evaluate_candidates,
    infer_pickup,
    source_identity,
)
from mir.score_metrics import metrics_from_plan, source_identity_preserved
from mir.score_profile import score_profile
from mir.types import Hand, MusicalEvent, NoteEvent, ScoreMeta
from mir.voice_separator import VoiceSeparator
from notation_engine.plan import NotationPlanner
from timing.tempo_map import MusicalTimeMap

METER_44 = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)


def _note(pitch, start, end, ident, velocity=80):
    return NoteEvent(
        pitch=pitch,
        start_time=start,
        end_time=end,
        velocity=velocity,
        note_id=ident,
    )


def _event(pitch, start, duration, ident, hand=Hand.RIGHT, voice=0):
    return MusicalEvent(
        pitch,
        start,
        duration,
        note_id=ident,
        hand=hand,
        voice=voice,
        hand_locked=True,
        velocity=80,
    )


def _assert_identity(notes, snapshot):
    assert [source_identity(n) for n in notes] == snapshot


def test_a_jittered_quarters_stay_simple_and_preserve_identity():
    time_map = MusicalTimeMap.from_bpm(120, duration_sec=8)
    notes = [
        _note(72, i * 0.5 + 0.02, i * 0.5 + 0.47, f"n{i:04d}") for i in range(8)
    ]
    snapshot = [source_identity(n) for n in notes]
    candidates = evaluate_candidates(notes, time_map)
    _assert_identity(notes, snapshot)
    chosen = choose_candidate(candidates)
    assert chosen.tempo_scale == 1.0
    assert chosen.meter == "4/4"
    events = [
        _event(n.pitch, i + 0.04, 0.93, n.note_id) for i, n in enumerate(notes)
    ]
    before = deepcopy(events)
    out, decisions, report = quantize_notation(
        events, METER_44, config=type("C", (), {"max_onset_move": 0.18})()
    )
    assert events == before
    assert [n.onset for n in report.notes] == [Fraction(i, 1) for i in range(8)]
    assert all(n.duration == 1 for n in report.notes)
    assert source_identity_preserved(notes, out)


def test_b_genuine_sixteenths_survive():
    time_map = MusicalTimeMap.from_bpm(120, duration_sec=4)
    notes = [
        _note(72, i * 0.125, i * 0.125 + 0.1, f"n{i:04d}") for i in range(8)
    ]
    snapshot = [source_identity(n) for n in notes]
    chosen = choose_candidate(evaluate_candidates(notes, time_map))
    _assert_identity(notes, snapshot)
    assert chosen.tempo_scale == 1.0
    events = [_event(72, i * 0.25, 0.25, f"n{i:04d}") for i in range(8)]
    out, _ = MeasureQuantizer(mode="performance").quantize(events, METER_44)
    assert [e.start_beat for e in out] == [i * 0.25 for i in range(8)]
    assert all(abs(e.duration_beats - 0.25) < 1e-9 for e in out)


def test_c_triplet_phrase_survives():
    time_map = MusicalTimeMap.from_bpm(120, duration_sec=4)
    beat = 0.5
    notes = [
        _note(72, i * beat / 3, i * beat / 3 + beat / 3 * 0.9, f"n{i:04d}")
        for i in range(6)
    ]
    snapshot = [source_identity(n) for n in notes]
    chosen = choose_candidate(evaluate_candidates(notes, time_map))
    _assert_identity(notes, snapshot)
    assert chosen.tempo_scale == 1.0
    events = [_event(72, i / 3, 1 / 3, f"n{i:04d}") for i in range(6)]
    quantizer = MeasureQuantizer(mode="performance")
    quantizer.quantize(events, METER_44)
    assert [n.onset for n in quantizer.last_report.notes] == [Fraction(i, 3) for i in range(6)]


def test_d_syncopation_stays_offbeat():
    events = [
        _event(72, 0.5, 0.5, "a"),
        _event(74, 1.5, 0.5, "b"),
        _event(76, 2.5, 0.5, "c"),
        _event(77, 3.5, 0.5, "d"),
    ]
    out, _ = MeasureQuantizer(mode="performance").quantize(events, METER_44)
    assert [e.start_beat for e in out] == [0.5, 1.5, 2.5, 3.5]


def test_e_waltz_prefers_3_4_over_6_8():
    time_map = MusicalTimeMap.from_bpm(120, duration_sec=8)
    notes = []
    idx = 0
    for bar in range(4):
        base = bar * 1.5
        for offset, pitch, vel in ((0.0, 48, 96), (0.5, 64, 70), (1.0, 67, 70)):
            notes.append(_note(pitch, base + offset, base + offset + 0.45, f"n{idx:04d}", vel))
            idx += 1
    snapshot = [source_identity(n) for n in notes]
    candidates = evaluate_candidates(notes, time_map)
    _assert_identity(notes, snapshot)
    scale_one = [c for c in candidates if abs(c.tempo_scale - 1.0) < 1e-9]
    waltz = next(c for c in scale_one if c.meter == "3/4")
    compound = next(c for c in scale_one if c.meter == "6/8")
    assert waltz.total < compound.total
    assert waltz.grouping_cost <= compound.grouping_cost + 1e-9


def test_f_compound_grouping_prefers_6_8_over_3_4():
    time_map = MusicalTimeMap.from_bpm(120, duration_sec=8)
    notes = []
    idx = 0
    for bar in range(4):
        base = bar * 1.5
        notes.append(_note(48, base, base + 0.7, f"n{idx:04d}", 96))
        idx += 1
        notes.append(_note(48, base + 0.75, base + 1.45, f"n{idx:04d}", 90))
        idx += 1
        for k, pitch in enumerate((72, 74, 76, 77, 79, 81)):
            start = base + k * 0.25
            notes.append(_note(pitch, start, start + 0.22, f"n{idx:04d}", 75))
            idx += 1
    snapshot = [source_identity(n) for n in notes]
    candidates = evaluate_candidates(notes, time_map)
    _assert_identity(notes, snapshot)
    scale_one = [c for c in candidates if abs(c.tempo_scale - 1.0) < 1e-9]
    compound = next(c for c in scale_one if c.meter == "6/8")
    waltz = next(c for c in scale_one if c.meter == "3/4")
    assert compound.total < waltz.total
    chosen = choose_candidate(candidates)
    assert chosen.tempo_scale == 1.0
    assert chosen.meter == "6/8"


def test_g_half_double_tempo_candidates_compare_musically():
    slow_map = MusicalTimeMap.from_bpm(60, duration_sec=8)
    notes = [
        _note(72, i * 0.5, i * 0.5 + 0.4, f"n{i:04d}") for i in range(8)
    ]
    snapshot = [source_identity(n) for n in notes]
    candidates = evaluate_candidates(notes, slow_map)
    _assert_identity(notes, snapshot)
    chosen = choose_candidate(candidates)
    double = next(
        c for c in candidates if abs(c.tempo_scale - 2.0) < 1e-9 and c.meter == "4/4"
    )
    normal = next(
        c for c in candidates if abs(c.tempo_scale - 1.0) < 1e-9 and c.meter == "4/4"
    )
    assert double.total < normal.total
    assert chosen.tempo_scale == 2.0
    assert chosen.meter in ("4/4", "2/4")
    fast_map = MusicalTimeMap.from_bpm(120, duration_sec=8)
    halves = [
        _note(72, i * 1.0, i * 1.0 + 0.85, f"h{i:04d}") for i in range(8)
    ]
    snapshot = [source_identity(n) for n in halves]
    half_candidates = evaluate_candidates(halves, fast_map)
    _assert_identity(halves, snapshot)
    half = next(
        c for c in half_candidates if abs(c.tempo_scale - 0.5) < 1e-9 and c.meter == "4/4"
    )
    ones = next(
        c for c in half_candidates if abs(c.tempo_scale - 1.0) < 1e-9 and c.meter == "4/4"
    )
    assert half.total < ones.total


def test_h_pickup_requires_downbeat_evidence():
    assert infer_pickup(1.0, 4.0, downbeat_beats=[])["pickup_inferred"] is False
    inferred = infer_pickup(3.0, 4.0, downbeat_beats=[4.0, 8.0])
    assert inferred["pickup_inferred"] is True
    assert inferred["pickup_beats"] == 3.0
    assert infer_pickup(0.0, 4.0, downbeat_beats=[0.0, 4.0])["pickup_inferred"] is False


def test_i_pedal_like_releases_write_quarters_without_changing_raw():
    raw = [_event(48, float(i), 1.8, f"p{i}", Hand.LEFT) for i in range(4)]
    before = deepcopy(raw)
    out, decisions, report = quantize_notation(
        raw, METER_44, config=type("C", (), {"max_onset_move": 0.18})()
    )
    assert raw == before
    notes = {n.source_id: n for n in report.notes}
    for i in range(3):
        assert notes[f"p{i}"].duration == 1
    assert decisions[0]["performed_duration"] > decisions[0]["written_duration"]
    assert source_identity_preserved(raw, out)


def test_j_two_independent_voices_remain_independent():
    events = []
    for i in range(4):
        events.append(_event(76, float(i), 1.0, f"m{i}", Hand.RIGHT, voice=0))
        events.append(_event(60, float(i) + 0.5, 1.0, f"i{i}", Hand.RIGHT, voice=0))
    unlabeled = [
        MusicalEvent(
            e.pitch,
            e.start_beat,
            e.duration_beats,
            note_id=e.note_id,
            velocity=80,
            hand=Hand.RIGHT,
            hand_locked=True,
        )
        for e in events
    ]
    out = assign_pipeline_layout(
        unlabeled, score_profile(unlabeled), HandSeparator(), VoiceSeparator()
    )
    rh = [e for e in out if e.hand == Hand.RIGHT]
    assert len({e.voice for e in rh}) == 2


def test_k_hand_crossing_is_allowed_and_summarized():
    from mir.score_interpretation import summarize_hand_decisions

    events = []
    for i in range(4):
        events.append(
            MusicalEvent(67 + i, float(i), 0.5, note_id=f"lh{i}", role="bass", velocity=80)
        )
        events.append(
            MusicalEvent(55 + i, float(i), 0.5, note_id=f"rh{i}", role="melody", velocity=80)
        )
    out = HandSeparator().separate(events)
    assert {e.hand for e in out} <= {Hand.LEFT, Hand.RIGHT, Hand.AMBIGUOUS}
    summary = summarize_hand_decisions(out, source="viterbi")
    assert summary["source"] == "viterbi"
    assert "crossings" in summary
    pitches = {e.note_id: e.pitch for e in out}
    assert pitches["lh0"] == 67
    assert pitches["rh0"] == 55


def test_l_sustained_barline_note_keeps_source_and_ties():
    raw = [_event(72, 3, 6, "sustain"), _event(60, 3, 0.5, "inner"), _event(62, 4, 0.5, "inner2")]
    before = deepcopy(raw)
    plan, _ = NotationPlanner().build(
        raw, meta=ScoreMeta(time_sig_hint="4/4"), quantization_mode="performance"
    )
    assert raw == before
    sustained = [
        n
        for m in plan.measures
        for s in m.staves
        for v in s.voices
        for n in v.elements
        if isinstance(n, PlannedNote) and "sustain" in n.event_ids
    ]
    assert sum(n.duration_q for n in sustained) == 6
    assert any(n.tie == "start" for n in sustained)
    metrics = metrics_from_plan(plan, source_notes=raw, quantized=raw)
    assert metrics["source_identity_preserved"] is True
    assert metrics["source_note_count"] == 3


def test_candidate_evaluation_never_mutates_source_seconds():
    time_map = MusicalTimeMap.from_bpm(88, duration_sec=6)
    notes = [_note(60 + i, 0.17 * i, 0.17 * i + 0.11, f"n{i:04d}") for i in range(12)]
    snapshot = [source_identity(n) for n in notes]
    evaluate_candidates(notes, time_map)
    _assert_identity(notes, snapshot)
    scaled = time_map.with_subdivisions(2).with_stride(2)
    assert [source_identity(n) for n in notes] == snapshot
    assert abs(scaled.beats_to_seconds(scaled.seconds_to_beats(1.3)) - 1.3) < 1e-4
