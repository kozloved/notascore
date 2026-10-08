"""Paired Readable onset-alignment and ornament counterexamples."""

from __future__ import annotations

from fractions import Fraction

from mir.models import MeterHypothesis
from mir.notation_settings import NotationSettings
from mir.performance_score import _onset_candidates, quantize_notation
from mir.quantizer import QuantizerConfig
from mir.types import Hand, MusicalEvent

METER = MeterHypothesis("3/4", 3, 4, 3.0, 1.0, 1.0)
LITERAL = NotationSettings.from_dict(
    {"interpretation": "literal", "algorithm_version": "performance-score-1"}
)
READABLE = NotationSettings.from_dict(
    {"interpretation": "readable", "algorithm_version": "performance-score-1"}
)
CONFIG = QuantizerConfig()


def _ev(pitch, start, dur, ident, hand=Hand.RIGHT):
    return MusicalEvent(
        pitch, start, dur, note_id=ident, hand=hand, hand_locked=True, velocity=80,
        source_backend="midi",
    )


def test_exact_fine_onset_stays_exclusive_in_literal_but_opens_in_readable():
    literal = _onset_candidates(3.125, 0.22, LITERAL)
    readable = _onset_candidates(3.125, 0.22, READABLE)
    assert len(literal) == 1 and float(literal[0][0]) == 3.125
    assert any(float(onset) == 3.0 for onset, _family, _cost in readable)
    assert any(float(onset) == 3.125 for onset, _family, _cost in readable)


def test_exact_sixteenth_and_tuplet_remain_exclusive_in_readable():
    sixteenth = _onset_candidates(1.25, 0.22, READABLE)
    assert len(sixteenth) == 1 and float(sixteenth[0][0]) == 1.25
    triplet = _onset_candidates(1 / 3, 0.22, READABLE)
    assert len(triplet) == 1 and abs(float(triplet[0][0]) - 1 / 3) < 1e-9


def test_readable_aligns_delayed_melody_to_bass_beat():
    # Autumn Walks-shaped opening: bass slightly early of the half-beat, RH late.
    events = [
        _ev(42, 0.40, 3.5, "bass", Hand.LEFT),
        _ev(77, 0.4604, 3.5, "melody", Hand.RIGHT),
    ]
    lit_out, lit_dec, _ = quantize_notation(events, METER, config=CONFIG, settings=LITERAL)
    read_out, read_dec, _ = quantize_notation(events, METER, config=CONFIG, settings=READABLE)
    lit = {e.note_id: e for e in lit_out}
    read = {e.note_id: e for e in read_out}
    # Literal keeps the performed delay on the page.
    assert lit["melody"].start_beat != lit["bass"].start_beat
    assert abs(lit["melody"].start_beat - lit["bass"].start_beat) >= 0.04
    assert read["bass"].start_beat == read["melody"].start_beat
    assert abs(read["melody"].start_beat - 0.5) < 1e-9
    # Prefer-beat candidate costs may already agree; shared-beat realignment is
    # the fallback when search leaves a residual 32nd (see exact 3.125 case).
    assert all(abs(d["quantized_start"] - 0.5) < 1e-9 for d in read_dec)


def test_literal_preserves_opening_thirty_second_against_bass():
    events = [
        _ev(42, 3.0, 2.0, "bass", Hand.LEFT),
        _ev(77, 3.125, 2.0, "melody", Hand.RIGHT),
    ]
    out, _dec, _ = quantize_notation(events, METER, config=CONFIG, settings=LITERAL)
    by_id = {e.note_id: e for e in out}
    assert by_id["bass"].start_beat == 3.0
    assert by_id["melody"].start_beat == 3.125


def test_readable_aligns_exact_thirty_second_melody_to_bass():
    events = [
        _ev(42, 3.0, 2.0, "bass", Hand.LEFT),
        _ev(77, 3.125, 2.0, "melody", Hand.RIGHT),
    ]
    out, dec, _ = quantize_notation(events, METER, config=CONFIG, settings=READABLE)
    by_id = {e.note_id: e for e in out}
    assert by_id["bass"].start_beat == by_id["melody"].start_beat == 3.0
    assert any(d.get("reason") == "readable_shared_beat" for d in dec)


def test_readable_preserves_isolated_syncopation_without_accompaniment():
    events = [
        _ev(72, 1.125, 0.5, "offbeat", Hand.RIGHT),
        _ev(74, 2.0, 0.5, "onbeat", Hand.RIGHT),
    ]
    out, _dec, _ = quantize_notation(events, METER, config=CONFIG, settings=READABLE)
    by_id = {e.note_id: e for e in out}
    assert abs(by_id["offbeat"].start_beat - 1.125) < 1e-9


def test_readable_aligns_humanized_chord_coincidence():
    events = [
        _ev(60, 0.00, 1.9, "c"),
        _ev(64, 0.04, 1.85, "e"),
        _ev(67, 0.05, 1.88, "g"),
    ]
    out, dec, _ = quantize_notation(events, METER, config=CONFIG, settings=READABLE)
    starts = {round(e.start_beat, 4) for e in out}
    assert len(starts) == 1
    assert min(starts) <= 0.05
    reasons = {d.get("reason") for d in dec}
    assert "readable_chord_coincidence" in reasons or len(starts) == 1


def test_readable_does_not_align_deliberate_same_hand_syncopation():
    events = [
        _ev(72, 0.0, 0.5, "onbeat"),
        _ev(74, 1.125, 0.5, "offbeat"),
        _ev(76, 2.0, 0.5, "later"),
    ]
    out, _dec, _ = quantize_notation(events, METER, config=CONFIG, settings=READABLE)
    by_id = {e.note_id: e for e in out}
    assert abs(by_id["offbeat"].start_beat - 1.125) < 1e-9


def test_readable_preserves_fast_figure_against_bass():
    events = [
        _ev(42, 4.0, 1.0, "bass", Hand.LEFT),
        _ev(72, 4.04, 0.1, "a", Hand.RIGHT),
        _ev(74, 4.12, 0.1, "b", Hand.RIGHT),
        _ev(76, 4.20, 0.1, "c", Hand.RIGHT),
    ]
    out, _dec, _ = quantize_notation(events, METER, config=CONFIG, settings=READABLE)
    by_id = {e.note_id: e for e in out}
    assert by_id["bass"].start_beat == 4.0
    # Rapid RH stream must not collapse onto the bass attack.
    assert by_id["a"].start_beat != by_id["bass"].start_beat or by_id["b"].start_beat != 4.0


def test_locked_timing_is_not_realigned():
    events = [
        _ev(42, 3.0, 2.0, "bass", Hand.LEFT),
        MusicalEvent(
            77, 3.125, 2.0, note_id="melody", hand=Hand.RIGHT, hand_locked=True,
            velocity=80, source_backend="midi", score_timing_locked=True,
        ),
    ]
    out, _dec, _ = quantize_notation(events, METER, config=CONFIG, settings=READABLE)
    by_id = {e.note_id: e for e in out}
    assert by_id["melody"].start_beat == 3.125
    assert by_id["bass"].start_beat == 3.0


def test_readable_marks_short_anticipation_as_editable_ornament():
    events = [
        _ev(70, 24.0, 0.25, "bb", Hand.RIGHT),
        _ev(72, 24.2, 1.0, "c", Hand.RIGHT),
        _ev(73, 25.0, 1.0, "cs", Hand.RIGHT),
        _ev(75, 26.0, 1.0, "eb", Hand.RIGHT),
        _ev(42, 24.0, 3.0, "bass", Hand.LEFT),
    ]
    out, dec, _ = quantize_notation(events, METER, config=CONFIG, settings=READABLE)
    by_id = {e.note_id: e for e in out}
    bb_dec = next(d for d in dec if d["note_id"] == "bb")
    assert bb_dec.get("ornament", {}).get("ornament_style") == "acciaccatura"
    assert bb_dec["ornament"]["editable"] is True
    assert bb_dec["ornament"]["primary_note_id"] == "c"
    assert by_id["bb"].articulation == "ornament"
    # Source attack and positive written duration preserved for playback.
    assert by_id["bb"].duration_beats > 0
    assert abs(by_id["bb"].start_beat - 24.0) <= 0.26


def test_long_written_hold_is_not_ornamented_from_reviewer_wording_alone():
    # Mimic re-ingested score MIDI: Bb already written as 1.5 beats.
    events = [
        _ev(70, 24.125, 1.5, "bb", Hand.RIGHT),
        _ev(72, 24.25, 1.5, "c", Hand.RIGHT),
        _ev(42, 24.0, 3.0, "bass", Hand.LEFT),
    ]
    _out, dec, _ = quantize_notation(events, METER, config=CONFIG, settings=READABLE)
    bb_dec = next(d for d in dec if d["note_id"] == "bb")
    assert "ornament" not in bb_dec


def test_literal_does_not_mark_ornaments():
    events = [
        _ev(70, 24.0, 0.25, "bb", Hand.RIGHT),
        _ev(72, 24.2, 1.0, "c", Hand.RIGHT),
    ]
    _out, dec, _ = quantize_notation(events, METER, config=CONFIG, settings=LITERAL)
    assert all("ornament" not in d for d in dec)
