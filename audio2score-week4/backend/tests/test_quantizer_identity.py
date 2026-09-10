"""Adaptive quantizer identity, overlap, and barline safety."""

from __future__ import annotations

import pytest

from mir.adaptive_quantizer import (
    QuantizerIdentityError,
    restore_identity,
    validate_identity_invariants,
)
from mir.models import MeterHypothesis
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent, copy_event


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


def _by_id(events):
    return {e.note_id: e for e in events}


def test_1_identity_after_reorder():
    raw = [
        _ev(60, 0.03, 0.90, note_id="a", velocity=71),
        _ev(64, 0.50, 0.40, note_id="b", velocity=90),
    ]
    notation = [
        copy_event(raw[1], start_beat=0.50, duration_beats=0.50, pitch=11, velocity=1),
        copy_event(raw[0], start_beat=0.00, duration_beats=1.00, pitch=99, velocity=2),
    ]
    restored = restore_identity(raw, notation)
    by_id = _by_id(restored)
    assert by_id["a"].pitch == 60 and by_id["a"].velocity == 71
    assert by_id["b"].pitch == 64 and by_id["b"].velocity == 90
    assert by_id["a"].note_id == "a" and by_id["b"].note_id == "b"
    assert abs(by_id["a"].start_beat - 0.00) < 1e-9
    assert abs(by_id["b"].start_beat - 0.50) < 1e-9
    report = validate_identity_invariants(raw, restored)
    assert report["identity_valid"] is True
    assert report["pitch_mismatches"] == 0
    assert report["velocity_mismatches"] == 0


def test_2_duplicate_note_id_fails_validation():
    raw = [
        _ev(60, 0.0, 1.0, note_id="a", velocity=70),
        _ev(64, 1.0, 1.0, note_id="a", velocity=80),
    ]
    with pytest.raises(QuantizerIdentityError, match="duplicate"):
        validate_identity_invariants(raw, raw)


def test_3_missing_note_id_fails_safely():
    raw = [_ev(60, 0.0, 1.0, note_id="a", velocity=70)]
    notation = [_ev(60, 0.0, 1.0, note_id="missing", velocity=70)]
    with pytest.raises(QuantizerIdentityError, match="no matching raw note_id"):
        restore_identity(raw, notation)


def test_4_staggered_chord_shares_onset():
    events = [
        _ev(60, 0.01, 1.0, note_id="c", velocity=70),
        _ev(64, 0.04, 0.97, note_id="e", velocity=72),
        _ev(67, 0.06, 0.94, note_id="g", velocity=74),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    by_id = _by_id(notation)
    starts = {round(by_id[k].start_beat, 6) for k in ("c", "e", "g")}
    assert starts == {0.0}
    assert by_id["c"].pitch == 60 and by_id["c"].velocity == 70
    assert by_id["e"].pitch == 64 and by_id["e"].velocity == 72
    assert by_id["g"].pitch == 67 and by_id["g"].velocity == 74
    assert q.last_summary["identity_valid"] is True
    assert q.last_summary["chord_alignments"] >= 1


def test_5_genuine_overlap_is_not_cleaned_away():
    events = [
        _ev(72, 0.0, 1.0, note_id="held", velocity=80),
        _ev(76, 0.75, 0.5, note_id="entry", velocity=81),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    by_id = _by_id(notation)
    held = by_id["held"]
    entry = by_id["entry"]
    assert held.pitch == 72 and held.velocity == 80
    assert entry.pitch == 76 and entry.velocity == 81
    assert held.start_beat < entry.start_beat - 1e-9
    assert held.start_beat + held.duration_beats > entry.start_beat + 0.1
    assert abs(held.duration_beats - 1.0) <= 0.06
    assert q.last_summary["notes_shortened_for_overlap"] == 0


def test_6_legitimate_barline_sustain_is_preserved():
    events = [_ev(72, 3.0, 2.0, note_id="hold", velocity=88)]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    hold = notation[0]
    assert hold.note_id == "hold"
    assert hold.pitch == 72 and hold.velocity == 88
    assert abs(hold.start_beat - 3.0) < 0.02
    assert hold.duration_beats >= 1.9
    assert hold.start_beat + hold.duration_beats > 4.0 + 1e-9
    assert q.last_summary["barline_splits_required"] >= 1


def test_7_non_crossing_note_does_not_invent_a_barline_tie():
    events = [
        _ev(72, 3.0, 0.75, note_id="inside", velocity=80),
        _ev(74, 4.0, 1.0, note_id="downbeat", velocity=81),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    by_id = _by_id(notation)
    inside = by_id["inside"]
    assert inside.start_beat + inside.duration_beats <= 4.0 + 1e-6
    assert inside.pitch == 72 and inside.velocity == 80


def test_8_jittered_eighths_stay_on_eighth_grid():
    raw_starts = [0.01, 0.51, 0.99, 1.49, 2.01]
    events = [_ev(72, s, 0.42, note_id=f"n{i}") for i, s in enumerate(raw_starts)]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    starts = [round(e.start_beat, 6) for e in sorted(notation, key=lambda e: e.start_beat)]
    assert starts == [0.0, 0.5, 1.0, 1.5, 2.0]
    assert q.last_summary.get("triplet_decisions", 0) == 0
    assert q.last_summary["identity_valid"] is True


def test_9_genuine_triplets_use_triplet_grid():
    events = [_ev(72, i / 3.0, 1.0 / 3.0, note_id=f"t{i}") for i in range(6)]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    third_like = sum(
        1 for e in notation if abs((e.start_beat * 3) - round(e.start_beat * 3)) < 0.05
    )
    assert third_like >= 5
    assert q.last_summary.get("triplet_groups", 0) >= 1
    assert {e.note_id for e in notation} == {f"t{i}" for i in range(6)}


def test_10_binary_passage_with_one_outlier_stays_binary():
    events = [
        _ev(72, 0.0, 0.5, note_id="a"),
        _ev(74, 0.5, 0.5, note_id="b"),
        _ev(76, 1.0, 0.5, note_id="c"),
        _ev(77, 1.58, 0.5, note_id="d"),
        _ev(79, 2.0, 0.5, note_id="e"),
        _ev(81, 2.5, 0.5, note_id="f"),
        _ev(83, 3.0, 0.5, note_id="g"),
        _ev(84, 3.5, 0.5, note_id="h"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    by_id = _by_id(notation)
    assert round(by_id["a"].start_beat, 3) == 0.0
    assert round(by_id["c"].start_beat, 3) == 1.0
    assert round(by_id["d"].start_beat, 3) in (1.5, 1.75)
    assert q.last_summary.get("triplet_decisions", 0) == 0
    assert {e.pitch for e in notation} == {e.pitch for e in events}
