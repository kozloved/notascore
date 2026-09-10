"""Notation integrity: voice timelines, ties, music21 boundary, layout."""

from __future__ import annotations

import re

from music21 import chord as m21chord
from music21 import note as m21note
from music21 import stream
from music21.base import Music21Object

from mir.models import PlannedNote, PlannedRest
from mir.quantizer import MeasureQuantizer, VOICE_SUM_TOLERANCE
from mir.types import Hand, MusicalEvent, ScoreMeta, copy_event
from notation_engine.plan import NotationPlanner, validate_voice_timeline
from notation_engine.writer import (
    NotationWriter,
    _strip_forced_musicxml_layout,
    iter_invalid_stream_objects,
)


def _ev(pitch, start, dur, hand=Hand.RIGHT, voice=0, **kwargs) -> MusicalEvent:
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        hand=hand,
        voice=voice,
        velocity=kwargs.get("velocity", 80),
        note_id=kwargs.get("note_id", ""),
    )


def _meta(ts="4/4", bpm=120) -> ScoreMeta:
    return ScoreMeta(display_tempo_bpm=bpm, time_sig_hint=ts)


def _build(events, ts="4/4"):
    return NotationPlanner().build(events, meta=_meta(ts), quantization_mode="adaptive")


def _voice_notes(plan, staff_id=0, voice_id=None):
    out = []
    for measure in plan.measures:
        for staff in measure.staves:
            if staff.staff_id != staff_id:
                continue
            for voice in staff.voices:
                if voice_id is not None and voice.voice_id != voice_id:
                    continue
                for el in voice.elements:
                    if isinstance(el, PlannedNote):
                        out.append((measure.number, voice.voice_id, el))
    return out


def _assert_plan_timelines(plan):
    for measure in plan.measures:
        for staff in measure.staves:
            for voice in staff.voices:
                issues = validate_voice_timeline(
                    voice.elements, measure.duration_beats
                )
                serious = [
                    i
                    for i in issues
                    if i["reason"]
                    in (
                        "overlap",
                        "ends_after_measure",
                        "negative_duration",
                        "zero_duration",
                        "starts_before_zero",
                        "sum_mismatch",
                    )
                ]
                assert not serious, (measure.number, staff.staff_id, voice.voice_id, serious)
                total = sum(el.duration_q for el in voice.elements)
                assert abs(total - measure.duration_beats) <= VOICE_SUM_TOLERANCE


def _assert_no_printed_rest_over_notes(plan):
    for measure in plan.measures:
        for staff in measure.staves:
            notes = []
            rests = []
            for voice in staff.voices:
                for el in voice.elements:
                    if isinstance(el, PlannedNote):
                        notes.append((voice.voice_id, el.start_q, el.start_q + el.duration_q))
                    elif isinstance(el, PlannedRest) and not el.hidden:
                        rests.append((voice.voice_id, el.start_q, el.start_q + el.duration_q))
            for rv, rs, re in rests:
                for nv, ns, ne in notes:
                    if rv == nv:
                        continue
                    overlap = min(re, ne) - max(rs, ns)
                    assert overlap <= 1e-6, (
                        f"printed rest voice {rv} overlaps note voice {nv} "
                        f"in measure {measure.number} staff {staff.staff_id}"
                    )


def _assert_score_in_bars(score):
    for part in score.parts:
        for meas in part.getElementsByClass(stream.Measure):
            try:
                mql = float(meas.barDuration.quarterLength)
            except Exception:
                mql = float(getattr(meas.duration, "quarterLength", 4.0) or 4.0)
            assert float(meas.highestTime) <= mql + 1e-5, (
                part.id,
                meas.number,
                meas.highestTime,
                mql,
            )
            for voice in meas.getElementsByClass(stream.Voice):
                assert float(voice.highestTime) <= mql + 1e-5, (
                    part.id,
                    meas.number,
                    voice.id,
                    voice.highestTime,
                    mql,
                )


def test_a_four_quarters_fill_bar_without_rests():
    events = [_ev(60 + i, float(i), 1.0, note_id=f"q{i}") for i in range(4)]
    plan, _ = _build(events)
    _assert_plan_timelines(plan)
    notes = [el for _, _, el in _voice_notes(plan, 0)]
    assert len(notes) == 4
    assert all(isinstance(el, PlannedNote) for _, _, el in _voice_notes(plan, 0, 0))
    rh = plan.measures[0].staves[0].voices[0]
    assert not any(isinstance(el, PlannedRest) for el in rh.elements)
    writer = NotationWriter()
    score = writer.score_from_plan(plan, meta=_meta())
    _assert_score_in_bars(score)
    assert writer.last_fit_trim_count == 0


def test_b_eight_eighths_no_accidental_rests():
    events = [_ev(72, i * 0.5, 0.5, note_id=f"e{i}") for i in range(8)]
    plan, _ = _build(events)
    _assert_plan_timelines(plan)
    notes = [el for _, _, el in _voice_notes(plan, 0, 0)]
    assert len(notes) == 8
    rh = [el for el in plan.measures[0].staves[0].voices[0].elements]
    assert not any(isinstance(el, PlannedRest) for el in rh)
    assert abs(sum(el.duration_q for el in rh) - 4.0) <= VOICE_SUM_TOLERANCE


def test_c_simultaneous_chord_is_one_event():
    events = [
        _ev(60, 0.0, 1.0, note_id="c"),
        _ev(64, 0.0, 1.0, note_id="e"),
        _ev(67, 0.0, 1.0, note_id="g"),
    ]
    plan, _ = _build(events)
    _assert_plan_timelines(plan)
    notes = [el for _, _, el in _voice_notes(plan, 0)]
    chords = [el for el in notes if set(el.pitches) == {60, 64, 67}]
    assert chords
    assert abs(chords[0].duration_q - 1.0) < 0.13
    score = NotationWriter().score_from_plan(plan)
    xml = score.write("musicxml")
    text = xml.read_text(encoding="utf-8") if hasattr(xml, "read_text") else open(xml).read()
    assert "<chord" in text.lower()
    m21_chords = list(score.recurse().getElementsByClass(m21chord.Chord))
    assert m21_chords


def test_d_different_duration_same_onset_not_merged():
    events = [
        _ev(60, 0.0, 1.0, voice=0, note_id="short"),
        _ev(64, 0.0, 2.0, voice=0, note_id="long"),
    ]
    plan, _ = _build(events)
    _assert_plan_timelines(plan)
    notes = [el for _, vid, el in _voice_notes(plan, 0)]
    merged = [el for el in notes if set(el.pitches) == {60, 64} and abs(el.duration_q - 2.0) < 1e-6]
    assert not merged
    by_pitch = {el.pitches[0]: el for el in notes if len(el.pitches) == 1}
    assert 60 in by_pitch and 64 in by_pitch
    assert abs(by_pitch[60].duration_q - 1.0) < 0.13
    assert abs(by_pitch[64].duration_q - 2.0) < 0.13
    assert {vid for _, vid, _ in _voice_notes(plan, 0)} >= {0}


def test_e_genuine_polyphony_overlap_across_voices_only():
    events = [
        _ev(76, 0.0, 1.0, voice=0, note_id="m1"),
        _ev(77, 1.0, 1.0, voice=0, note_id="m2"),
        _ev(79, 2.0, 1.0, voice=0, note_id="m3"),
        _ev(81, 3.0, 1.0, voice=0, note_id="m4"),
        _ev(60, 0.0, 4.0, voice=1, note_id="hold"),
    ]
    plan, _ = _build(events)
    _assert_plan_timelines(plan)
    _assert_no_printed_rest_over_notes(plan)
    rh = plan.measures[0].staves[0]
    assert len(rh.voices) >= 2
    melody = [el for _, _, el in _voice_notes(plan, 0, 0)]
    held = [el for _, _, el in _voice_notes(plan, 0, 1)]
    assert [el.pitches for el in melody] == [[76], [77], [79], [81]]
    assert held and held[0].pitches == [60]
    secondary_rests = [
        el
        for voice in rh.voices
        if voice.voice_id != 0
        for el in voice.elements
        if isinstance(el, PlannedRest)
    ]
    assert all(el.hidden for el in secondary_rests)


def test_f_barline_crossing_is_tied_and_inside_bars():
    events = [_ev(72, 3.5, 2.0, note_id="cross")]
    plan, _ = _build(events)
    _assert_plan_timelines(plan)
    notes = _voice_notes(plan, 0, 0)
    first = [el for meas, _, el in notes if meas == 1]
    second = [el for meas, _, el in notes if meas == 2]
    assert first and second
    assert abs(first[0].start_q - 3.5) < 0.13
    assert abs(first[0].duration_q - 0.5) < 0.13
    assert abs(second[0].start_q) < 0.13
    assert abs(second[0].duration_q - 1.5) < 0.13
    assert first[0].tie == "start"
    assert second[0].tie == "stop"
    for measure in plan.measures:
        for staff in measure.staves:
            for voice in staff.voices:
                for el in voice.elements:
                    assert el.start_q + el.duration_q <= measure.duration_beats + 1e-6
    writer = NotationWriter()
    score = writer.score_from_plan(plan)
    _assert_score_in_bars(score)
    xml = score.write("musicxml")
    text = xml.read_text(encoding="utf-8") if hasattr(xml, "read_text") else open(xml).read()
    assert 'type="start"' in text
    assert 'type="stop"' in text


def test_f_sustain_ending_exactly_at_barline_has_no_tie():
    events = [_ev(72, 0.0, 4.0, note_id="exact")]
    plan, _ = _build(events)
    _assert_plan_timelines(plan)
    notes = [el for meas, _, el in _voice_notes(plan, 0) if meas == 1]
    assert notes
    assert notes[0].tie is None
    assert len(plan.measures) == 1


def test_f_note_crossing_multiple_bars():
    events = [_ev(72, 3.0, 6.0, note_id="long")]
    plan, _ = NotationPlanner().build(
        events, meta=_meta(), quantization_mode="off"
    )
    _assert_plan_timelines(plan)
    notes = _voice_notes(plan, 0)
    assert len(plan.measures) >= 3
    ties = [el.tie for _, _, el in notes]
    assert "start" in ties
    assert "stop" in ties
    assert "continue" in ties or len([t for t in ties if t]) >= 2
    writer = NotationWriter()
    score = writer.score_from_plan(plan)
    _assert_score_in_bars(score)


def test_f_tied_chord_crossing_barline():
    events = [
        _ev(60, 3.5, 2.0, note_id="c"),
        _ev(64, 3.5, 2.0, note_id="e"),
        _ev(67, 3.5, 2.0, note_id="g"),
    ]
    plan, _ = _build(events)
    _assert_plan_timelines(plan)
    first = [el for meas, _, el in _voice_notes(plan, 0) if meas == 1]
    second = [el for meas, _, el in _voice_notes(plan, 0) if meas == 2]
    assert first and second
    assert set(first[0].pitches) == {60, 64, 67}
    assert first[0].tie == "start"
    assert second[0].tie == "stop"


def test_g_tiny_gap_does_not_create_pathological_rest():
    planner = NotationPlanner()
    items = [
        (_ev(72, 0.0, 1.0, note_id="a"), 0.0, 1.0, None),
        (_ev(74, 1.04, 0.96, note_id="b"), 1.04, 0.96, None),
    ]
    elements = planner._fill_voice(items, 4.0, voice_id=0, measure_number=1, staff_id=0)
    tiny = [
        el
        for el in elements
        if isinstance(el, PlannedRest) and el.duration_q < 0.0625
    ]
    assert not tiny
    issues = [
        i
        for i in validate_voice_timeline(elements, 4.0)
        if i["reason"] in ("overlap", "ends_after_measure", "zero_duration")
    ]
    assert not issues


def test_h_compound_meter_six_eight():
    events = [_ev(72, i * 0.5, 0.5, note_id=f"s{i}") for i in range(6)]
    plan, _ = _build(events, ts="6/8")
    _assert_plan_timelines(plan)
    assert plan.time_signature == "6/8"
    assert abs(plan.measures[0].duration_beats - 3.0) < 1e-6
    notes = [el for _, _, el in _voice_notes(plan, 0, 0)]
    assert len(notes) == 6


def test_i_validation_independent_of_list_order():
    good = [
        PlannedNote(pitches=[60], start_q=0.0, duration_q=1.0, voice=0),
        PlannedRest(start_q=1.0, duration_q=1.0, voice=0),
        PlannedNote(pitches=[62], start_q=2.0, duration_q=2.0, voice=0),
    ]
    shuffled = list(reversed(good))
    a = validate_voice_timeline(good, 4.0)
    b = validate_voice_timeline(shuffled, 4.0)
    assert {i["reason"] for i in a} == {i["reason"] for i in b}
    overlap = [
        PlannedNote(pitches=[60], start_q=0.0, duration_q=2.0, voice=0),
        PlannedNote(pitches=[64], start_q=1.0, duration_q=2.0, voice=0),
    ]
    issues = validate_voice_timeline(list(reversed(overlap)), 4.0)
    assert any(i["reason"] == "overlap" for i in issues)


def test_j_music21_object_integrity(tmp_path):
    events = [
        _ev(72, 0.0, 1.0, Hand.RIGHT, note_id="r"),
        _ev(76, 0.0, 1.0, Hand.RIGHT, note_id="r2"),
        _ev(48, 0.0, 4.0, Hand.LEFT, note_id="l"),
        _ev(67, 2.0, 3.0, Hand.RIGHT, note_id="tie"),
    ]
    writer = NotationWriter()
    score = writer.write_from_events_direct(events, _meta())
    assert iter_invalid_stream_objects(score) == []
    for site in [score, *score.recurse()]:
        try:
            children = list(site)
        except Exception:
            continue
        for child in children:
            assert isinstance(child, Music21Object)
    xml = writer.write_musicxml(
        events, _meta(), job_id="integrity", audio_path=tmp_path / "clip.wav"
    )
    assert "score-partwise" in xml.lower()
    assert writer.last_fallback_used is False
    payload = writer.notation_debug_payload()
    assert payload["notation_plan_success"] is True
    assert payload["notation_plan_failure"] is False
    assert payload["legacy_fallback_used"] is False
    assert payload["music21_conversion_failure"] is False
    assert payload["musicxml_export_failure"] is False


def test_k_multimeasure_musicxml_has_no_forced_breaks(tmp_path):
    events = []
    for i in range(32):
        events.append(_ev(72 + (i % 4), float(i), 1.0, Hand.RIGHT, note_id=f"r{i}"))
        events.append(_ev(48, float(i), 1.0, Hand.LEFT, note_id=f"l{i}"))
    writer = NotationWriter()
    xml = writer.write_musicxml(
        events, _meta(), job_id="layout", audio_path=tmp_path / "clip.wav"
    )
    assert xml.lower().count("<measure") >= 8
    assert "new-system" not in xml.lower()
    assert "new-page" not in xml.lower()
    assert "<system-layout>" not in xml.lower()
    assert "<page-layout>" not in xml.lower()
    assert not re.search(r"<measure\b[^>]*\swidth=", xml)
    assert writer.last_fallback_used is False
    assert (tmp_path / "bp_layout" / "layout.score.mid").exists()
    _assert_plan_timelines(writer.last_plan)
    _assert_no_printed_rest_over_notes(writer.last_plan)


def test_grand_staff_measures_stay_synchronized():
    events = [
        _ev(72, 0.0, 1.0, Hand.RIGHT, note_id="r1"),
        _ev(48, 0.0, 4.0, Hand.LEFT, note_id="l1"),
        _ev(74, 4.0, 1.0, Hand.RIGHT, note_id="r2"),
    ]
    plan, _ = _build(events)
    _assert_plan_timelines(plan)
    for measure in plan.measures:
        staff_ids = {s.staff_id for s in measure.staves}
        assert staff_ids == {0, 1}
        assert len({s.clef for s in measure.staves}) >= 1
        for staff in measure.staves:
            assert staff.voices
            for voice in staff.voices:
                assert abs(sum(el.duration_q for el in voice.elements) - 4.0) <= VOICE_SUM_TOLERANCE


def test_empty_staff_measure_has_visible_rest():
    events = [_ev(72, 0.0, 4.0, Hand.RIGHT, note_id="solo")]
    plan, _ = _build(events)
    lh = next(s for s in plan.measures[0].staves if s.staff_id == 1)
    rests = [el for v in lh.voices for el in v.elements if isinstance(el, PlannedRest)]
    assert rests
    assert any(not el.hidden for el in rests)


def test_valid_plan_is_not_trimmed_by_writer():
    events = [_ev(60 + i, float(i), 1.0, note_id=f"n{i}") for i in range(4)]
    writer = NotationWriter()
    plan, _ = writer.planner.build(events, meta=_meta())
    writer.last_fit_trim_count = 0
    writer.score_from_plan(plan)
    assert writer.last_fit_trim_count == 0


def test_fit_stream_logs_but_valid_voice_untouched():
    writer = NotationWriter()
    voice = stream.Voice(id="1")
    for i in range(4):
        voice.append(m21note.Note(midi=72, quarterLength=1.0))
    assert writer._fit_stream_to_quarter_length(voice, 4.0) == 0
    assert float(voice.highestTime) == 4.0


def test_strip_forced_layout_removes_breaks_and_widths():
    raw = """<measure number="1" width="999">
      <print new-system="yes" new-page="yes">
        <system-layout><system-margins></system-margins></system-layout>
        <page-layout><page-height>100</page-height></page-layout>
      </print>
    </measure>"""
    cleaned = _strip_forced_musicxml_layout(raw)
    assert "new-system" not in cleaned
    assert "new-page" not in cleaned
    assert "system-layout" not in cleaned
    assert "page-layout" not in cleaned
    assert "width=" not in cleaned


def test_raw_events_unchanged_through_notation_write(tmp_path):
    events = [
        _ev(72, 0.03, 0.91, Hand.RIGHT, velocity=71, note_id="a"),
        _ev(48, 0.50, 1.40, Hand.LEFT, velocity=90, note_id="b"),
        _ev(64, 1.10, 0.40, Hand.RIGHT, velocity=64, note_id="c"),
    ]
    snapshot = [
        (
            e.note_id,
            e.pitch,
            e.velocity,
            e.start_beat,
            e.duration_beats,
            id(e),
        )
        for e in events
    ]
    writer = NotationWriter()
    writer.write_musicxml(events, _meta(), job_id="raw", audio_path=tmp_path / "clip.wav")
    after = [
        (
            e.note_id,
            e.pitch,
            e.velocity,
            e.start_beat,
            e.duration_beats,
            id(e),
        )
        for e in events
    ]
    assert after == snapshot
    q = writer.planner.quantizer
    assert isinstance(q, MeasureQuantizer)
    raw = q.last_raw_events
    assert len(raw) == 3
    by_id = {e.note_id: e for e in raw}
    assert by_id["a"].pitch == 72 and by_id["a"].velocity == 71
    assert abs(by_id["a"].start_beat - 0.03) < 1e-9
    assert abs(by_id["a"].duration_beats - 0.91) < 1e-9
    assert by_id["b"].pitch == 48 and by_id["c"].pitch == 64


def test_planner_failure_is_classified_separately_from_conversion(tmp_path):
    writer = NotationWriter()

    def boom(*_args, **_kwargs):
        raise RuntimeError("planner exploded")

    writer.planner.build = boom
    xml = writer.write_musicxml(
        [_ev(72, 0.0, 1.0)],
        _meta(),
        job_id="plan-fail",
        quantization_mode="adaptive",
        audio_path=tmp_path / "clip.wav",
    )
    payload = writer.notation_debug_payload()
    assert payload["notation_plan_failure"] is True
    assert payload["legacy_fallback_used"] is True
    assert payload["notation_plan_success"] is False
    assert "planner exploded" in (payload["notation_fallback_error"] or "")
    assert "score-partwise" in xml.lower()


def test_conversion_failure_does_not_look_like_planner_failure(tmp_path):
    writer = NotationWriter()
    original = writer.score_from_plan

    def boom(*_args, **_kwargs):
        raise RuntimeError("music21 exploded")

    writer.score_from_plan = boom
    xml = writer.write_musicxml(
        [_ev(72, 0.0, 1.0, Hand.RIGHT), _ev(48, 0.0, 1.0, Hand.LEFT)],
        _meta(),
        job_id="conv-fail",
        quantization_mode="adaptive",
        audio_path=tmp_path / "clip.wav",
    )
    payload = writer.notation_debug_payload()
    assert payload["notation_plan_failure"] is False
    assert payload["music21_conversion_failure"] is True
    assert payload["legacy_fallback_used"] is True
    assert "music21 exploded" in (payload["notation_fallback_error"] or "")
    writer.score_from_plan = original
    assert "score-partwise" in xml.lower()


def test_hidden_secondary_rests_export_print_object_no(tmp_path):
    events = [
        _ev(76, 0.0, 1.0, voice=0, note_id="m1"),
        _ev(77, 1.0, 1.0, voice=0, note_id="m2"),
        _ev(79, 2.0, 1.0, voice=0, note_id="m3"),
        _ev(81, 3.0, 1.0, voice=0, note_id="m4"),
        _ev(60, 0.0, 1.0, voice=1, note_id="short-hold"),
    ]
    writer = NotationWriter()
    xml = writer.write_musicxml(
        events, _meta(), job_id="hidden-rest", audio_path=tmp_path / "clip.wav",
        quantization_mode="adaptive",
    )
    _assert_no_printed_rest_over_notes(writer.last_plan)
    assert "print-object=\"no\"" in xml or "print-object='no'" in xml
