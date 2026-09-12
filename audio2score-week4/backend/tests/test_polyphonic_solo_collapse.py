"""Polyphonic MT3 multi-program MIDI must still produce solo notation."""

from __future__ import annotations

from mir.models import MeterHypothesis
from mir.performance_score import quantize_notation
from mir.score_profile import collapse_for_solo_notation, score_profile
from mir.types import Hand, InstrumentKind, MusicalEvent


def test_score_profile_still_rejects_raw_ensemble():
    events = [
        MusicalEvent(60, 0, 1, source_program=0, instrument=InstrumentKind.PIANO, note_id="a"),
        MusicalEvent(72, 1, 1, source_program=40, instrument=InstrumentKind.STRINGS, note_id="b"),
    ]
    try:
        score_profile(events)
        raise AssertionError("expected ensemble rejection")
    except ValueError as exc:
        assert "Ensemble" in str(exc)


def test_collapse_keeps_all_attacks_and_unifies_program():
    events = [
        MusicalEvent(60, 0, 1, source_program=0, instrument=InstrumentKind.PIANO, note_id="a"),
        MusicalEvent(72, 1, 1, source_program=40, instrument=InstrumentKind.STRINGS, note_id="b"),
        MusicalEvent(64, 2, 1, source_program=0, instrument=InstrumentKind.PIANO, note_id="c"),
    ]
    collapsed, profile, warning = collapse_for_solo_notation(events)
    assert warning
    assert len(collapsed) == 3
    assert {e.source_program for e in collapsed} == {0}
    assert profile.grand_staff is True
    assert "solo_collapse" in profile.evidence


def test_quantize_notation_accepts_collapsed_ensemble():
    events = [
        MusicalEvent(
            60,
            0.0,
            1.0,
            velocity=80,
            source_program=0,
            instrument=InstrumentKind.PIANO,
            note_id="n0",
            hand=Hand.RIGHT,
            hand_locked=True,
        ),
        MusicalEvent(
            67,
            1.0,
            1.0,
            velocity=80,
            source_program=48,
            instrument=InstrumentKind.STRINGS,
            note_id="n1",
            hand=Hand.RIGHT,
            hand_locked=True,
        ),
    ]
    meter = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
    out, decisions, report = quantize_notation(
        events, meter, config=type("C", (), {"max_onset_move": 0.18})()
    )
    assert len(out) == 2
    assert len(report.notes) == 2
    assert report.summary.get("solo_collapse_warning")
    assert {row["source_program"] for row in decisions} == {0, 48}
