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


def test_simultaneous_unison_keeps_independent_attacks():
    """Overlapping same-pitch attacks are two lines; monophonic repeats stay one."""
    events = [_ev(60, 0.0, 1.0, "x0"), _ev(60, 0.0, 1.0, "x1")]
    groups = _musical_groups(events)
    assert groups["x0"] != groups["x1"]
    mono = _musical_groups([_ev(72, float(i), 0.5, f"m{i}") for i in range(4)])
    assert len(set(mono.values())) == 1


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


def _tick_tol_sec(tempo: float = 120.0, ticks_per_beat: int = 480, ticks: float = 1.5) -> float:
    """MIDI tick tolerance at constant tempo (seconds)."""
    return max(0.001, (60.0 / tempo) / float(ticks_per_beat) * ticks)


def _musicxml_attack_spans(xml_text: str, path: Path):
    """Independent MusicXML decode via notation_engine.integrity.score_attacks."""
    from tests.test_performance_score import _musicxml_attack_spans as _spans

    path.write_text(xml_text, encoding="utf-8")
    return _spans(path)


def _decode_score_midi(midi_bytes: bytes, path: Path):
    path.write_bytes(midi_bytes)
    pm = pretty_midi.PrettyMIDI(str(path))
    return sorted(
        (
            int(n.pitch),
            float(n.start),
            float(n.end),
            int(n.velocity),
        )
        for inst in pm.instruments
        for n in inst.notes
    )


def _assert_score_midi_matches(midi_bytes: bytes, path: Path, intended, *, tempo: float = 120.0):
    """Compare exported score MIDI to independently specified (pitch,start,end,vel)."""
    rows = [(int(r[0]), float(r[1]), float(r[2]), int(r[3])) for r in intended]
    decoded = _decode_score_midi(midi_bytes, path)
    expected = sorted(rows)
    assert len(decoded) == len(expected), (decoded, expected)
    tol = _tick_tol_sec(tempo)
    for actual, want in zip(decoded, expected):
        assert actual[0] == want[0]
        assert actual[3] == want[3]
        assert actual[1] == pytest.approx(want[1], abs=tol)
        assert actual[2] == pytest.approx(want[2], abs=tol)


def _assert_musicxml_attacks_match(
    xml_text: str,
    path: Path,
    intended_sec,
    *,
    tempo: float = 120.0,
):
    """Assert MusicXML attack multiplicity/pitch/onset/release in beats.

    ``intended_sec`` rows are (pitch, start_sec, end_sec, velocity[, channel]).
    Sustained notes must keep full release; interrupters stay distinct attacks.
    Ties may join written pieces of one source note only — collapsed spans must
    still match the intended attack inventory one-for-one.
    """
    beat = 60.0 / tempo
    expected = sorted(
        (
            int(r[0]),
            float(r[1]) / beat,
            float(r[2]) / beat,
        )
        for r in intended_sec
    )
    spans = _musicxml_attack_spans(xml_text, path)
    decoded = sorted((int(s[0]), float(s[1]), float(s[1]) + float(s[2])) for s in spans)
    assert len(decoded) == len(expected), (decoded, expected, spans)
    for actual, want in zip(decoded, expected):
        assert actual[0] == want[0]
        assert actual[1] == pytest.approx(want[1], abs=1e-6)
        assert actual[2] == pytest.approx(want[2], abs=1e-6)
    # Repeated same-pitch attacks remain distinct (no silent merge).
    assert len(spans) == len(intended_sec)
    # Ties, if any, only join pieces within one collapsed attack — never absorb
    # an independent interrupter into the sustained span.
    for span in spans:
        _pitch, onset, dur, pieces, tied, *_ = span
        if tied or pieces > 1:
            # Tied chain must still equal exactly one intended release.
            end = onset + dur
            matches = [
                row
                for row in expected
                if row[0] == int(_pitch)
                and abs(row[1] - onset) < 1e-6
                and abs(row[2] - end) < 1e-6
            ]
            assert len(matches) == 1, (span, expected)


def _editor_velocity_by_id(result) -> dict[str, int]:
    out = {}
    for row in result.editor_model["notes"]:
        sid = row.get("source_note_id") or row["id"]
        out[sid] = int(row["velocity"])
    return out


def _assert_exports_against_fixture(
    result,
    *,
    tmp_path: Path,
    label: str,
    intended,
    expected_groups: list[set[str]],
    tempo: float = 120.0,
):
    """Decode MusicXML + score MIDI and compare both to fixture expectations."""
    assign = _assignments(result)
    assert assign["count"] == len(intended)
    _assert_expected_partitions(assign, expected_groups)
    _assert_score_midi_matches(
        result.score_midi,
        tmp_path / f"{label}.score.mid",
        intended,
        tempo=tempo,
    )
    _assert_musicxml_attacks_match(
        result.musicxml,
        tmp_path / f"{label}.musicxml",
        intended,
        tempo=tempo,
    )
    return assign


def test_sustained_resume_e2e_partitions_survive_regen_and_edit(tmp_path, monkeypatch):
    """E2E: multi-channel hold/interrupter/resume with expected partitions + exports."""
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
    by_start = sorted(
        _assignments(auto)["notes"],
        key=lambda r: (r["start"], -r.get("duration", 0)),
    )
    s0, t0, t1, s1 = [row["id"] for row in by_start]
    groups = [{s0, s1}, {t0, t1}]
    assign = _assert_exports_against_fixture(
        auto,
        tmp_path=tmp_path,
        label="sustained_auto",
        intended=intended,
        expected_groups=groups,
    )
    hold_row = next(row for row in assign["notes"] if row["id"] == s0)
    assert hold_row["duration"] == pytest.approx(2.0, abs=1e-6)

    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": s0, "velocity": 105}],
    )
    assert source.read_bytes() == original
    edited_intended = [
        (60, 0.0, 1.0, 105, 0),
        (60, 0.25, 0.5, 70, 1),
        (60, 0.75, 1.0, 70, 1),
        (60, 1.0, 1.5, 80, 0),
    ]
    edit_assign = _assert_exports_against_fixture(
        edited,
        tmp_path=tmp_path,
        label="sustained_edited",
        intended=edited_intended,
        expected_groups=groups,
    )
    compared = compare_staff_voice(assign, edit_assign)
    assert compared["musical_grouping_equal"] is True
    assert compared["kind"] in {"unchanged", "printed_lane_adjustment"}

    auto_vel = _editor_velocity_by_id(auto)
    edit_vel = _editor_velocity_by_id(edited)
    assert edit_vel[s0] == 105
    for sid in (t0, t1, s1):
        assert edit_vel[sid] == auto_vel[sid]


def test_short_line_e2e_partitions_survive_regen(tmp_path, monkeypatch):
    """E2E: short repeating line continues after hold ends — exports + partitions."""
    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
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
    by_start = sorted(_assignments(auto)["notes"], key=lambda r: r["start"])
    hold_id = by_start[0]["id"]
    short_ids = [row["id"] for row in by_start[1:]]
    groups = [{hold_id}, set(short_ids)]
    assign = _assert_exports_against_fixture(
        auto,
        tmp_path=tmp_path,
        label="short_auto",
        intended=intended,
        expected_groups=groups,
    )
    assert len(assign["musical_voices"]) >= 2

    # Velocity-only edit on the first short note — compare both runs to fixture.
    st0 = short_ids[0]
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": st0, "velocity": 111}],
    )
    assert source.read_bytes() == original
    edited_intended = [
        (60, 0.0, 1.0, 80, 0),
        (60, 0.25, 0.5, 111, 1),
        (60, 0.5, 0.75, 70, 1),
        (60, 0.75, 1.0, 70, 1),
        (60, 1.0, 1.25, 70, 1),
    ]
    edit_assign = _assert_exports_against_fixture(
        edited,
        tmp_path=tmp_path,
        label="short_edited",
        intended=edited_intended,
        expected_groups=groups,
    )
    compared = compare_staff_voice(assign, edit_assign)
    assert compared["musical_grouping_equal"] is True
    assert compared["kind"] in {"unchanged", "printed_lane_adjustment"}
    auto_vel = _editor_velocity_by_id(auto)
    edit_vel = _editor_velocity_by_id(edited)
    assert edit_vel[st0] == 111
    for sid in [hold_id, *short_ids[1:]]:
        assert edit_vel[sid] == auto_vel[sid]


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
