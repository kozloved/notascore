"""Construction-labeled pairs challenging same-pitch voice continuity (P2b).

These tests document expected musical_voice grouping with observable context
or supplied assignments. Ambiguous unlabeled cases are marked and not used
as proof of musician-validated quality.
"""

from __future__ import annotations

import pytest

from evaluation.readable_v2_rollout import _assignments, compare_staff_voice
from mir.midi_ingest import ingest_midi
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings
from mir.types import Hand, MusicalEvent
from mir.voice_separator import VoiceSeparator
from tests.test_shared_engraving import _context_for, _write_midi


def _ev(pitch, start, dur, note_id, **kwargs):
    return MusicalEvent(
        pitch,
        start,
        dur,
        note_id=note_id,
        hand=Hand.RIGHT,
        velocity=kwargs.pop("velocity", 80),
        **kwargs,
    )


def _musical_groups(events) -> dict[str, int]:
    out = VoiceSeparator().separate(list(events))
    return {e.note_id: int(e.musical_voice) for e in out}


def _same_group(groups: dict[str, int], *note_ids: str) -> bool:
    ids = list(note_ids)
    return len({groups[n] for n in ids}) == 1


def test_sustained_line_resumes_after_same_pitch_interruption():
    """Construction: hold s0; short t0/t1 interrupters; s1 reattack continues s0."""
    events = [
        _ev(60, 0.0, 2.0, "s0"),
        _ev(60, 0.5, 0.5, "t0"),
        _ev(60, 1.5, 0.5, "t1"),
        _ev(60, 2.0, 1.0, "s1"),
    ]
    groups = _musical_groups(events)
    assert _same_group(groups, "s0", "s1")
    assert _same_group(groups, "t0", "t1")
    assert groups["s0"] != groups["t0"]


def test_short_repeating_line_continues_when_sustained_hold_ends():
    """Construction: short st* line must not lose st3 to the ending hold.

    PR #87 regression: st3 incorrectly joined hold (musical_voice 0) because
    the sustained-length bonus ignored duration mismatch.
    """
    events = [
        _ev(60, 0.0, 2.0, "hold"),
        _ev(60, 0.5, 0.5, "st0"),
        _ev(60, 1.0, 0.5, "st1"),
        _ev(60, 1.5, 0.5, "st2"),
        _ev(60, 2.0, 0.5, "st3"),
    ]
    groups = _musical_groups(events)
    assert _same_group(groups, "st0", "st1", "st2", "st3")
    assert groups["hold"] != groups["st3"]
    # Parent (pre PR #87 bonus): st3 stayed with st* — st3=1.
    # PR #87 without guard: st3=0 (wrong). After guard: st3=1.


def test_both_lines_resume_independently_after_gap():
    events = [
        _ev(72, 0.0, 1.0, "a0"),
        _ev(60, 0.0, 1.0, "b0"),
        _ev(72, 2.0, 1.0, "a1"),
        _ev(60, 2.0, 1.0, "b1"),
    ]
    groups = _musical_groups(events)
    assert _same_group(groups, "a0", "a1")
    assert _same_group(groups, "b0", "b1")
    assert groups["a0"] != groups["b0"]


def test_returning_line_after_rest_keeps_identity():
    events = [
        _ev(72, 0.0, 1.0, "r0"),
        _ev(74, 1.0, 1.0, "r1"),
        _ev(55, 2.0, 1.0, "c0"),
        _ev(57, 3.0, 1.0, "c1"),
        _ev(72, 4.0, 1.0, "r2"),
        _ev(74, 5.0, 1.0, "r3"),
    ]
    groups = _musical_groups(events)
    assert _same_group(groups, "r0", "r2")
    assert _same_group(groups, "r1", "r3")
    assert groups["r0"] != groups["c0"]


def test_crossing_lines_keep_two_streams():
    """Crossing is ambiguous by pitch alone; expect two voices, not one merged line."""
    events = [
        _ev(72, 0.0, 1.0, "u0"),
        _ev(48, 0.0, 1.0, "l0"),
        _ev(60, 1.0, 1.0, "u1"),
        _ev(67, 1.0, 1.0, "l1"),
        _ev(72, 2.0, 1.0, "u2"),
        _ev(48, 2.0, 1.0, "l2"),
    ]
    groups = _musical_groups(events)
    assert len(set(groups.values())) >= 2


def test_simultaneous_unison_has_no_unique_line_identity():
    """Ambiguous: two unlabeled same-pitch attacks at once — any single voice is valid."""
    events = [_ev(60, 0.0, 1.0, "x0"), _ev(60, 0.0, 1.0, "x1")]
    groups = _musical_groups(events)
    # Documented outcome: merged to one voice; not proof of correct musical reading.
    assert groups["x0"] == groups["x1"]


def test_user_voice_lock_survives_competing_duration_preference():
    events = [
        _ev(60, 0.0, 2.0, "s0"),
        _ev(60, 0.5, 0.5, "t0"),
        _ev(60, 1.5, 0.5, "t1"),
        _ev(
            60,
            2.0,
            1.0,
            "s1",
            voice=1,
            voice_assigned=True,
            voice_provenance="user_edit",
        ),
    ]
    out = VoiceSeparator().separate(events)
    by_id = {e.note_id: e for e in out}
    assert by_id["s1"].musical_voice == 1
    assert by_id["s1"].voice_provenance == "user_edit"


def test_monophonic_repeat_counterexample_stays_one_voice():
    events = [_ev(72, float(i), 0.5, f"m{i}") for i in range(8)]
    groups = _musical_groups(events)
    assert len(set(groups.values())) == 1


def _write_same_pitch_midi(path, *, tempo=120):
    """MIDI for sustained+interrupter pattern at 120 bpm (0.5s per beat).

    Uses pretty_midi so overlapping same-pitch attacks coexist in one track
    (construction-labeled; not a claim about MIDI polyphony semantics).
    """
    notes = [
        (60, 0.0, 1.0, 80),   # hold
        (60, 0.25, 0.5, 70),  # t0
        (60, 0.75, 1.0, 70),  # t1
        (60, 1.0, 1.5, 80),   # s1 resume
    ]
    _write_midi(path, notes, tempo=tempo)


def test_same_pitch_continuity_survives_regen_and_unrelated_edit(tmp_path):
    """E2E: separator → regen → editor; musical grouping stable on velocity edit."""
    source = tmp_path / "same_pitch.mid"
    _write_same_pitch_midi(source)
    original = source.read_bytes()
    ingested = ingest_midi(source)
    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    notes = auto.editor_model["notes"]
    assert notes, "expected editor notes from regen"
    sid = notes[0].get("source_note_id") or notes[0]["id"]
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": sid, "velocity": 105}],
    )
    assert source.read_bytes() == original
    compared = compare_staff_voice(_assignments(auto), _assignments(edited))
    assert compared["musical_grouping_equal"] is True
    assert compared["assignments_unchanged"] is True


def test_two_voice_midi_regen_preserves_musical_grouping_across_edit(tmp_path):
    """E2E: melody+inner at distinct pitches — musical groups stable on edit."""
    source = tmp_path / "two_voice.mid"
    notes = []
    for i in range(4):
        t = i * 0.5
        notes.append((76, t, t + 0.45, 85))
        notes.append((60, t, t + 0.45, 70))
    _write_midi(source, notes, tempo=120)
    original = source.read_bytes()
    ingested = ingest_midi(source)
    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    assert source.read_bytes() == original
    assign = _assignments(auto)
    assert assign["count"] == 8
    sid = assign["notes"][0]["id"]
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": sid, "velocity": 99}],
    )
    compared = compare_staff_voice(assign, _assignments(edited))
    assert compared["musical_grouping_equal"] is True
    # Printed lanes may renumber; musical partitions must stay equal.
    assert compared["kind"] in {"unchanged", "printed_lane_adjustment"}
