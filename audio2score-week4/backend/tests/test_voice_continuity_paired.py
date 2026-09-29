"""Construction-labeled pairs challenging same-pitch voice continuity (P2b).

Inferred-voice continuity uses canonical MusicalEvent lists or multi-channel
MIDI that round-trips overlapping same-pitch notes. Supplied-voice
preservation is a separate test. Ambiguous unlabeled cases are documented
and are not treated as musician-validated quality.
"""

from __future__ import annotations

from pathlib import Path

import mido
import pretty_midi
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
    return len({groups[n] for n in note_ids}) == 1


def _write_multichannel_midi(path: Path, notes, *, tempo: float = 120) -> bytes:
    """Write notes as (pitch, start, end, velocity, channel).

    Overlapping same-pitch unisons must use distinct channels; a single
    SMF channel cannot round-trip independent overlapping unisons.
    """
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=int(60_000_000 / tempo), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    events = []
    for pitch, start, end, velocity, channel in notes:
        events.append((float(start), 0, "on", int(pitch), int(velocity), int(channel)))
        events.append((float(end), 1, "off", int(pitch), 0, int(channel)))
    events.sort()
    last_tick = 0
    ticks_per_sec = (tempo / 60.0) * 480
    for time_sec, _order, kind, pitch, velocity, channel in events:
        tick = int(round(time_sec * ticks_per_sec))
        delta = max(0, tick - last_tick)
        last_tick = tick
        if kind == "on":
            track.append(
                mido.Message(
                    "note_on",
                    note=pitch,
                    velocity=velocity,
                    channel=channel,
                    time=delta,
                )
            )
        else:
            track.append(
                mido.Message(
                    "note_off",
                    note=pitch,
                    velocity=0,
                    channel=channel,
                    time=delta,
                )
            )
    mid.save(str(path))
    return path.read_bytes()


def _assert_decoded_matches(path: Path, intended, *, tol: float = 1e-3):
    """Assert pretty_midi + ingest preserve intended note multiplicity and times.

    ``intended`` rows are (pitch, start, end, velocity[, channel]).
    """
    rows = [(int(r[0]), float(r[1]), float(r[2]), int(r[3])) for r in intended]
    pm = pretty_midi.PrettyMIDI(str(path))
    decoded = sorted(
        (
            int(n.pitch),
            float(n.start),
            float(n.end),
            int(n.velocity),
        )
        for inst in pm.instruments
        for n in inst.notes
    )
    expected = sorted(rows)
    assert len(decoded) == len(expected), (decoded, expected)
    for actual, want in zip(decoded, expected):
        assert actual[0] == want[0]
        assert actual[3] == want[3]
        assert actual[1] == pytest.approx(want[1], abs=tol)
        assert actual[2] == pytest.approx(want[2], abs=tol)

    ingested = ingest_midi(path)
    assert len(ingested.notes) == len(expected)
    ids = [n.note_id for n in ingested.notes]
    assert all(ids) and len(set(ids)) == len(ids)
    by_time = sorted(
        ((n.pitch, n.start_time, n.end_time, n.velocity) for n in ingested.notes),
        key=lambda row: (row[1], row[3], row[0]),
    )
    want_by_time = sorted(expected, key=lambda row: (row[1], row[3], row[0]))
    for actual, want in zip(by_time, want_by_time):
        assert actual[0] == want[0]
        assert actual[3] == want[3]
        assert actual[1] == pytest.approx(want[1], abs=tol)
        assert actual[2] == pytest.approx(want[2], abs=tol)
    return ingested


def test_single_channel_overlapping_unison_does_not_preserve_hold(tmp_path):
    """Document the fixture defect: one-channel overlap truncates the hold."""
    path = tmp_path / "voice_fixture_bad_same_pitch.mid"
    # Intended hold 0.0–1.0; short note 0.25–0.5 on the same channel/pitch.
    intended = [
        (60, 0.0, 1.0, 80),
        (60, 0.25, 0.5, 70),
    ]
    _write_midi(path, intended, tempo=120)
    pm = pretty_midi.PrettyMIDI(str(path))
    decoded = sorted(
        (round(n.start, 4), round(n.end, 4), n.velocity) for n in pm.instruments[0].notes
    )
    # Hold ends at 0.5, not 1.0 — this is why multi-channel fixtures are required.
    assert decoded[0] == (0.0, 0.5, 80)
    assert (0.0, 1.0, 80) not in decoded


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
    """Construction: short st* line must not lose st3 to the ending hold."""
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
    """Supplied-voice preservation is separate from unlabeled inference."""
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


def _partition_by_id(assign: dict) -> dict[str, int]:
    return {row["id"]: int(row["musical_voice"]) for row in assign["notes"]}


def _assert_expected_partitions(assign: dict, expected_groups: list[set[str]]):
    """expected_groups: sets of source_note_id that must share musical_voice."""
    parts = _partition_by_id(assign)
    for group in expected_groups:
        voices = {parts[sid] for sid in group}
        assert len(voices) == 1, (group, parts)
    # Distinct groups must not share a musical_voice label.
    labels = []
    for group in expected_groups:
        labels.append(next(iter({parts[sid] for sid in group})))
    assert len(set(labels)) == len(labels), parts


def test_sustained_resume_e2e_partitions_survive_regen_and_edit(tmp_path, monkeypatch):
    """E2E: multi-channel hold/interrupter/resume with expected partitions."""
    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
    source = tmp_path / "sustained_resume.mid"
    # At 120 bpm, 1 beat = 0.5 s. Hold 0–2 beats; shorts at 0.5 and 1.5; resume at 2.
    intended = [
        (60, 0.0, 1.0, 80, 0),   # s0
        (60, 0.25, 0.5, 70, 1),  # t0
        (60, 0.75, 1.0, 70, 1),  # t1
        (60, 1.0, 1.5, 80, 0),   # s1
    ]
    original = _write_multichannel_midi(source, intended, tempo=120)
    ingested = _assert_decoded_matches(source, intended)

    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    assert source.read_bytes() == original
    assign = _assignments(auto)
    assert assign["count"] == 4
    by_start = sorted(assign["notes"], key=lambda r: (r["start"], -r.get("duration", 0)))
    ids = [row["id"] for row in by_start]
    # Order: s0, t0, t1, s1
    s0, t0, t1, s1 = ids
    _assert_expected_partitions(assign, [{s0, s1}, {t0, t1}])
    assert assign["notes"][0]["duration"] >= 1.9  # independent hold release (~2 beats)

    sid = s0
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": sid, "velocity": 105}],
    )
    assert source.read_bytes() == original
    edit_assign = _assignments(edited)
    _assert_expected_partitions(edit_assign, [{s0, s1}, {t0, t1}])
    compared = compare_staff_voice(assign, edit_assign)
    assert compared["musical_grouping_equal"] is True
    assert compared["kind"] in {"unchanged", "printed_lane_adjustment"}


def test_short_line_e2e_partitions_survive_regen(tmp_path):
    """E2E: short repeating line continues after hold ends — by source_note_id."""
    source = tmp_path / "short_line.mid"
    intended = [
        (60, 0.0, 1.0, 80, 0),    # hold 0–2 beats
        (60, 0.25, 0.5, 70, 1),   # st0
        (60, 0.5, 0.75, 70, 1),   # st1
        (60, 0.75, 1.0, 70, 1),   # st2
        (60, 1.0, 1.25, 70, 1),   # st3 after hold
    ]
    original = _write_multichannel_midi(source, intended, tempo=120)
    ingested = _assert_decoded_matches(source, intended)
    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    assert source.read_bytes() == original
    assign = _assignments(auto)
    assert assign["count"] == 5
    by_start = sorted(assign["notes"], key=lambda r: r["start"])
    hold_id = by_start[0]["id"]
    short_ids = [row["id"] for row in by_start[1:]]
    _assert_expected_partitions(assign, [{hold_id}, set(short_ids)])
    assert len(assign["musical_voices"]) >= 2


def test_held_bass_and_melody_split_by_staff_not_musical_voice(tmp_path):
    """Register-separated hold+melody: staff/hand split, not same-staff musical_voice.

    VoiceSeparator runs per hand. After hand assignment, bass is left and
    melody right, so each hand's musical_voice can be 0 while staff differs.
    Same-staff multi-voice evidence lives in the multi-channel same-pitch E2E
    tests above — do not claim ≥2 musical_voices for this piano split.
    """
    source = tmp_path / "held_staff_split.mid"
    notes = [
        (48, 0.0, 2.0, 75),
        (76, 0.0, 0.45, 90),
        (77, 0.5, 0.95, 90),
        (79, 1.0, 1.45, 90),
        (81, 1.5, 1.95, 90),
    ]
    original = _write_midi(source, notes, tempo=120)
    ingested = _assert_decoded_matches(source, notes)
    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    assert source.read_bytes() == original
    assign = _assignments(auto)
    assert assign["count"] == 5
    hold = next(row for row in assign["notes"] if row["pitch"] == 48)
    tops = [row for row in assign["notes"] if row["pitch"] >= 76]
    assert hold["staff"] != tops[0]["staff"]
    assert all(row["staff"] == tops[0]["staff"] for row in tops)

    sid = tops[0]["id"]
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": sid, "velocity": 99}],
    )
    compared = compare_staff_voice(assign, _assignments(edited))
    assert compared["musical_grouping_equal"] is True
    assert compared["kind"] in {"unchanged", "printed_lane_adjustment"}
