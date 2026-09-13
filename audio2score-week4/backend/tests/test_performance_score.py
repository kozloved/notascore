from copy import deepcopy
from fractions import Fraction

import pytest
from music21 import converter

from mir.models import MeterHypothesis, PlannedNote
from mir.pipeline_config import QuantizationMode, parse_quantization_mode
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.plan import NotationPlanner, validate_voice_timeline
from notation_engine.writer import NotationWriter


METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)


def event(pitch, start, duration, ident, hand=Hand.RIGHT):
    return MusicalEvent(pitch, start, duration, note_id=ident, hand=hand,
                        hand_locked=True, velocity=83)


def quantize(events):
    quantizer = MeasureQuantizer(mode="performance")
    output, decisions = quantizer.quantize(events, METER)
    return output, quantizer.last_report


def test_performance_is_default_and_adaptive_remains_available():
    assert parse_quantization_mode("performance") == QuantizationMode.PERFORMANCE
    assert parse_quantization_mode(None) == QuantizationMode.PERFORMANCE
    assert parse_quantization_mode("") == QuantizationMode.PERFORMANCE
    assert parse_quantization_mode("adaptive") == QuantizationMode.ADAPTIVE
    assert MeasureQuantizer().mode == QuantizationMode.PERFORMANCE


def test_public_writer_uses_performance_by_default(tmp_path):
    writer = NotationWriter()
    xml = writer.write_musicxml(
        [event(72, 0, 1, "default")], ScoreMeta(time_sig_hint="4/4"),
        "default", tmp_path / "source.mid",
    )
    assert "score-partwise" in xml
    assert writer.last_quantization_mode == QuantizationMode.PERFORMANCE
    assert writer.last_quantization_summary["engine"] == "performance"
    assert not writer.last_fallback_used


def test_raw_identity_and_exact_timing():
    raw = [event(72 + i, i * 0.5 + 0.01, 0.49, str(i)) for i in range(8)]
    before = deepcopy(raw)
    out, report = quantize(raw)
    assert raw == before
    assert {e.note_id: (e.pitch, e.velocity) for e in out} == {
        e.note_id: (e.pitch, e.velocity) for e in raw}
    assert [n.onset for n in report.notes] == [Fraction(i, 2) for i in range(8)]
    assert all(isinstance(n.duration, Fraction) for n in report.notes)


def test_simultaneous_binary_and_triplet_voices():
    raw = [event(48 + i, i / 2, 0.5, f"bass{i}", Hand.LEFT) for i in range(8)]
    raw += [event(72 + i % 3, i / 3 + 0.004, 1 / 3, f"melody{i}") for i in range(12)]
    out, report = quantize(raw)
    notes = {n.source_id: n for n in report.notes}
    for i in range(12):
        assert notes[f"melody{i}"].onset == Fraction(i, 3)
        assert notes[f"melody{i}"].duration == Fraction(1, 3)
    for i in range(8):
        assert notes[f"bass{i}"].onset == Fraction(i, 2)


def test_sixteenth_triplet_durations():
    raw = [event(72 + i % 3, i / 6, 1 / 6, str(i)) for i in range(12)]
    _, report = quantize(raw)
    assert [n.onset for n in report.notes] == [Fraction(i, 6) for i in range(12)]
    assert all(n.duration == Fraction(1, 6) for n in report.notes)


def test_cross_bar_sustain_preserves_lane_and_total_duration():
    raw = [event(72, 3, 6, "sustain"), event(60, 3, 0.5, "inner"),
           event(62, 4, 0.5, "inner2")]
    plan, _ = NotationPlanner().build(raw, meta=ScoreMeta(time_sig_hint="4/4"),
                                    quantization_mode="performance")
    sustained = [(v.voice_id, n) for m in plan.measures for s in m.staves
                 for v in s.voices for n in v.elements
                 if isinstance(n, PlannedNote) and "sustain" in n.event_ids]
    assert len({vid for vid, _ in sustained}) == 1
    assert sum(n.duration_q for _, n in sustained) == 6
    assert sustained[0][1].tie == "start"
    assert sustained[-1][1].tie == "stop"
    for m in plan.measures:
        for s in m.staves:
            for v in s.voices:
                assert not validate_voice_timeline(v.elements, m.duration_beats)
                assert sum(n.duration_q for n in v.elements) == m.duration_beats


def test_musicxml_roundtrip_preserves_attacks_and_triplet_timing(tmp_path):
    raw = [event(72 + i % 3, i / 3, 1 / 3, str(i)) for i in range(12)]
    writer = NotationWriter()
    score, _result = writer._score_via_plan_or_legacy(
        raw, ScoreMeta(time_sig_hint="4/4"), quantize_divisors=(4, 3),
        fallback_bpm=120, quantization_mode="performance")
    path = tmp_path / "score.musicxml"
    writer._export_musicxml(score, path)
    parsed = converter.parse(path)
    notes = list(parsed.parts[0].flatten().notes)
    assert len(notes) == len(raw)
    for i, note in enumerate(notes):
        assert float(note.offset) == pytest.approx(i / 3)
        assert float(note.quarterLength) == pytest.approx(1 / 3)
        assert note.pitch.midi == raw[i].pitch
    assert writer.last_fit_trim_count == 0
    assert not writer.last_fallback_used
    assert "<time-modification>" in path.read_text()


def test_duplicates_and_invalid_timing_fail_without_legacy_fallback():
    with pytest.raises(ValueError, match="Duplicate"):
        quantize([event(72, 0, 1, "x"), event(74, 1, 1, "x")])
    writer = NotationWriter()
    with pytest.raises(ValueError, match="timing"):
        writer._score_via_plan_or_legacy(
            [event(72, 0, float("nan"), "x")], ScoreMeta(time_sig_hint="4/4"),
            quantize_divisors=(4, 3), fallback_bpm=120, quantization_mode="performance")
    assert not writer.last_fallback_used


def test_missing_ids_are_generated_without_mutating_source():
    raw = [event(72, 0, 1, ""), event(74, 1, 1, "performance:0")]
    out, _ = quantize(raw)
    assert len({e.note_id for e in out}) == 2
    assert raw[0].note_id == ""


def test_empty_performance_exports_empty_grand_staff():
    plan, _ = NotationPlanner().build([], meta=ScoreMeta(time_sig_hint="4/4"),
                                    quantization_mode="performance")
    assert len(plan.measures) == 1
    assert len(plan.measures[0].staves) == 2


def test_public_writer_does_not_fallback_on_invalid_performance(tmp_path):
    writer = NotationWriter()
    with pytest.raises(ValueError, match="timing"):
        writer.write_musicxml([event(72, 0, -1, "bad")], ScoreMeta(time_sig_hint="4/4"),
                              "invalid", tmp_path / "source.mid", quantization_mode="performance")
    assert not writer.last_fallback_used


def test_long_triplet_line_does_not_create_float_drift_voices():
    raw = [event(72 + i % 3, i / 3, 1 / 3, str(i)) for i in range(60)]
    _, report = quantize(raw)
    assert report.summary["voice_count"] == 1


def test_unlabelled_piano_separates_bass_and_melody_hands():
    raw = [MusicalEvent(pitch, i / 2, 0.5, note_id=f"{pitch}:{i}")
           for i in range(8) for pitch in (40 + i % 3, 76 + i % 3)]
    out, _ = quantize(raw)
    assert all(e.hand == Hand.LEFT for e in out if e.pitch < 50)
    assert all(e.hand == Hand.RIGHT for e in out if e.pitch > 70)
    assert {e.role for e in out} == {"bass", "melody"}


def test_melody_hypothesis_can_choose_line_below_high_repeated_chord():
    from mir.performance_score import _phrase_roles

    line = [event(64 + i % 5, i / 2, 0.5, f"m{i}") for i in range(8)]
    chords = [event(pitch, i / 2, 0.5, f"c{pitch}:{i}")
              for i in range(8) for pitch in (79, 83, 86)]
    roles = _phrase_roles({(0, 0): line, (0, 1): chords}, 4)
    assert all(roles[e.note_id][0] == "melody" for e in line)


def test_compound_meter_and_dotted_duration_are_exact():
    raw = [event(72, 0, 1.5, "dotted"), event(74, 1.5, 0.5, "a"),
           event(76, 2, 0.5, "b"), event(77, 2.5, 0.5, "c")]
    plan, _ = NotationPlanner().build(raw, meta=ScoreMeta(time_sig_hint="6/8"),
                                    quantization_mode="performance")
    assert len(plan.measures) == 1
    assert plan.measures[0].duration_beats == 3
    notes = [n for s in plan.measures[0].staves for v in s.voices for n in v.elements
             if isinstance(n, PlannedNote)]
    assert notes[0].duration_q == Fraction(3, 2)


def test_second_compound_beat_is_one_dotted_note_without_ties():
    raw = [event(72, 0, 1.5, "a"), event(74, 1.5, 1.5, "b")]
    plan, _ = NotationPlanner().build(raw, meta=ScoreMeta(time_sig_hint="6/8"),
                                    quantization_mode="performance")
    notes = [n for s in plan.measures[0].staves for v in s.voices for n in v.elements
             if isinstance(n, PlannedNote)]
    assert len(notes) == 2
    assert all(n.duration_q == Fraction(3, 2) and n.tie is None for n in notes)


def test_compound_beams_are_planned_in_groups_of_three(tmp_path):
    raw = [event(72 + i, i / 2, 0.5, str(i)) for i in range(6)]
    writer = NotationWriter()
    score = writer.write_from_events_direct(raw, ScoreMeta(time_sig_hint="6/8"),
                                            quantization_mode="performance")
    notes = [n for s in writer.last_plan.measures[0].staves for v in s.voices for n in v.elements
             if isinstance(n, PlannedNote)]
    assert [n.beams[0][0] for n in notes] == ["start", "continue", "stop"] * 2
    path = tmp_path / "beams.musicxml"
    writer._export_musicxml(score, path)
    parsed = converter.parse(path)
    assert [n.beams.getByNumber(1).type for n in parsed.parts[0].flatten().notes] == ["start", "continue", "stop"] * 2


def test_tuplets_have_explicit_distinct_groups_and_export_boundaries(tmp_path):
    raw = [event(72 + i % 3, i / 3, 1 / 3, str(i)) for i in range(6)]
    writer = NotationWriter()
    score = writer.write_from_events_direct(raw, ScoreMeta(time_sig_hint="2/4"),
                                            quantization_mode="performance")
    notes = [n for s in writer.last_plan.measures[0].staves for v in s.voices for n in v.elements
             if isinstance(n, PlannedNote)]
    assert [n.tuplet.boundary for n in notes] == ["start", None, "stop"] * 2
    assert len({n.tuplet.group_id for n in notes}) == 2
    assert all((n.tuplet.actual, n.tuplet.normal) == (3, 2) for n in notes)
    path = tmp_path / "tuplets.musicxml"
    writer._export_musicxml(score, path)
    import xml.etree.ElementTree as ET
    xml = ET.parse(path)
    boundaries = [el.attrib["type"] for el in xml.findall(".//tuplet")]
    assert boundaries == ["start", "stop", "start", "stop"]


def test_unlabeled_piano_still_infers_layout():
    raw = [
        MusicalEvent(48, 0, 1, note_id="lh", velocity=80),
        MusicalEvent(72, 0, 1, note_id="rh", velocity=80),
    ]
    out, report = quantize(raw)
    assert report.summary["layout_source"] == "inferred"
    by_id = {e.note_id: e.hand for e in out}
    assert by_id["lh"] == Hand.LEFT
    assert by_id["rh"] == Hand.RIGHT


def test_does_not_recompute_assigned_pipeline_layout(monkeypatch):
    def boom(self, events):
        raise AssertionError("quantizer must not recompute assigned hands/voices")

    monkeypatch.setattr("mir.performance_score.HandSeparator.separate", boom)
    monkeypatch.setattr("mir.performance_score.VoiceSeparator.separate", boom)
    raw = [
        MusicalEvent(48, 0, 1, note_id="lh", hand=Hand.LEFT, voice=0, velocity=80),
        MusicalEvent(72, 0, 1, note_id="rh", hand=Hand.RIGHT, voice=1, velocity=80),
    ]
    out, report = quantize(raw)
    assert report.summary["layout_source"] == "pipeline"
    assert {e.note_id: e.hand for e in out} == {"lh": Hand.LEFT, "rh": Hand.RIGHT}


def test_keeps_pipeline_hand_that_viterbi_would_reassign():
    from mir.hand_separator import HandSeparator

    raw = []
    for i in range(4):
        raw.extend([
            MusicalEvent(36, float(i), 1, note_id=f"bass{i}", hand=Hand.LEFT, voice=0, velocity=80),
            MusicalEvent(48, float(i), 1, note_id=f"acc1{i}", hand=Hand.LEFT, voice=0, velocity=70),
            MusicalEvent(55, float(i), 1, note_id=f"acc2{i}", hand=Hand.LEFT, voice=0, velocity=70),
            MusicalEvent(60, float(i), 1, note_id=f"inner{i}", hand=Hand.RIGHT, voice=1, velocity=70),
            MusicalEvent(76, float(i), 1, note_id=f"mel{i}", hand=Hand.RIGHT, voice=0, velocity=80),
        ])
    unlabeled = [
        MusicalEvent(e.pitch, e.start_beat, e.duration_beats, note_id=e.note_id, velocity=e.velocity)
        for e in raw
    ]
    viterbi = {e.note_id: e.hand for e in HandSeparator().separate(unlabeled)}
    assert viterbi["inner0"] == Hand.LEFT
    out, report = quantize(raw)
    assert report.summary["layout_source"] == "pipeline"
    assert all(e.hand == Hand.RIGHT for e in out if e.note_id.startswith("inner"))


def test_keeps_pipeline_voices_that_separator_would_chord():
    from mir.voice_separator import VoiceSeparator

    raw = [
        MusicalEvent(60, 0.00, 1.0, note_id="a", hand=Hand.RIGHT, voice=0, velocity=80),
        MusicalEvent(64, 0.02, 1.0, note_id="b", hand=Hand.RIGHT, voice=1, velocity=80),
    ]
    merged = VoiceSeparator().separate(raw)
    assert len({e.voice for e in merged}) == 1
    _, report = quantize(raw)
    notes = {n.source_id: n for n in report.notes}
    assert notes["a"].voice != notes["b"].voice
    assert notes["a"].staff == notes["b"].staff
    assert report.summary["layout_source"] == "pipeline"


def test_near_boundary_releases_prefer_simple_written_values():
    from mir.performance_score import _duration, _fragment_count

    cases = {
        0.94: Fraction(1),
        1.17: Fraction(1),
        1.94: Fraction(2),
        2.21: Fraction(2),
        2.94: Fraction(3),
        3.14: Fraction(3),
        5.28: Fraction(5),
    }
    for raw, expected in cases.items():
        chosen = _duration(raw, Fraction(0), None, False, "binary")
        assert chosen == expected, (raw, chosen, expected)
        assert _fragment_count(Fraction(0), chosen) <= 2


def test_binary_phrase_rejects_tail_only_tuplets():
    from mir.performance_score import _duration

    # Near a binary pulse without triplet evidence must stay binary.
    chosen = _duration(0.94, Fraction(0), None, False, "binary")
    assert chosen.denominator in (1, 2, 4, 8, 16)
    assert chosen != Fraction(1, 3)
    chosen = _duration(1.17, Fraction(0), Fraction(2), False, "binary")
    assert chosen.denominator in (1, 2, 4, 8, 16)


def test_pedal_tails_do_not_force_extra_voice_before_releases():
    from mir.hand_separator import HandSeparator
    from mir.performance_score import assign_pipeline_layout
    from mir.score_profile import score_profile
    from mir.voice_separator import VoiceSeparator

    raw = [
        MusicalEvent(48, float(i), 1.8, note_id=f"p{i}", velocity=80)
        for i in range(4)
    ]
    out = assign_pipeline_layout(
        raw, score_profile(raw), HandSeparator(), VoiceSeparator()
    ).events
    assert len({e.voice for e in out}) == 1
    assert all(e.duration_beats == 1.8 for e in out)


def test_stamped_layout_authority_survives_quantization(monkeypatch):
    from mir.layout import LayoutAuthority
    from mir.performance_score import assign_pipeline_layout
    from mir.score_profile import score_profile
    from mir.voice_separator import VoiceSeparator
    from mir.hand_separator import HandSeparator

    raw = [
        MusicalEvent(48, 0, 1, note_id="lh", velocity=80),
        MusicalEvent(72, 0, 1, note_id="rh", velocity=80),
    ]
    laid = assign_pipeline_layout(
        raw, score_profile(raw), HandSeparator(), VoiceSeparator()
    )
    assert laid.authority is LayoutAuthority.INFERRED
    assert all(e.layout_authority == "inferred" for e in laid.events)

    def boom(*_a, **_k):
        raise AssertionError("quantize must not reconstruct layout from labels")

    monkeypatch.setattr("mir.performance_score.HandSeparator.separate", boom)
    monkeypatch.setattr("mir.performance_score.VoiceSeparator.separate", boom)
    out, report = quantize(laid.events)
    assert report.summary["layout_authority"] == "inferred"
    assert report.summary["layout_source"] == "inferred"
    assert {e.note_id: e.hand for e in out} == {
        e.note_id: e.hand for e in laid.events
    }


def test_release_scoring_uses_meter_barlines_not_unit_pulse():
    from mir.performance_score import _duration, _engraved_release_stats

    # In 3/4, a release that ends just past a barline should prefer a simpler
    # spelling when the fine-grid match creates an extra tiny tied fragment.
    onset = Fraction(2, 1)  # beat 2 in a 3-beat bar
    raw = 1.17
    chosen = _duration(
        raw,
        onset,
        None,
        False,
        "binary",
        measure_length=Fraction(3),
        beat_length=Fraction(1),
    )
    frags, ties, tiny = _engraved_release_stats(
        onset, chosen, measure_length=Fraction(3), beat_length=Fraction(1)
    )
    assert chosen == Fraction(1)
    assert frags <= 2
    assert tiny == 0


def test_overlapping_repeated_pitch_is_not_clipped_for_voice_search():
    from mir.performance_score import _release_hypothesis, _voice_search_events

    held = MusicalEvent(60, 0.0, 4.0, note_id="hold", hand=Hand.RIGHT, velocity=80)
    repeat = MusicalEvent(60, 1.0, 3.0, note_id="rep", hand=Hand.RIGHT, velocity=80)
    ordered = [held, repeat]
    assert _release_hypothesis(held, ordered)[1] == "overlapping_repeat"
    search = _voice_search_events(ordered)
    assert {e.note_id: e.duration_beats for e in search} == {
        "hold": 4.0,
        "rep": 3.0,
    }


def test_genuine_multi_attack_hold_is_not_clipped_for_voice_search():
    from mir.performance_score import _release_hypothesis

    hold = MusicalEvent(48, 0.0, 5.0, note_id="hold", hand=Hand.LEFT, velocity=80)
    a = MusicalEvent(55, 1.0, 0.5, note_id="a", hand=Hand.LEFT, velocity=70)
    b = MusicalEvent(58, 2.0, 0.5, note_id="b", hand=Hand.LEFT, velocity=70)
    assert _release_hypothesis(hold, [hold, a, b])[1] == "multi_attack_hold"


def test_held_c_with_inner_e_survives_quantize_and_musicxml(tmp_path):
    """End-to-end: assigned MT3 voice-0 pair must keep the independent hold."""
    raw = [
        MusicalEvent(
            60, 0.0, 2.0, note_id="c", hand=Hand.RIGHT, voice=0,
            voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3",
        ),
        MusicalEvent(
            64, 1.0, 1.0, note_id="e", hand=Hand.RIGHT, voice=0,
            voice_assigned=True, hand_locked=True, velocity=70, source_backend="mt3",
        ),
    ]
    before = [(e.note_id, e.start_beat, e.duration_beats, e.pitch) for e in raw]
    out, report = quantize(raw)
    assert [(e.note_id, e.start_beat, e.duration_beats, e.pitch) for e in raw] == before
    notes = {n.source_id: n for n in report.notes}
    assert notes["c"].duration == Fraction(2)
    assert notes["e"].duration == Fraction(1)
    assert {n.source_id for n in report.notes} == {"c", "e"}
    # Overlap is resolved by lanes, not by shortening the hold.
    assert notes["c"].voice != notes["e"].voice
    c_decision = next(d for d in report.decisions if d["note_id"] == "c")
    assert c_decision["release_reason"] == "no_line"
    assert c_decision["release_target_id"] is None
    assert c_decision["performed_duration"] == 2.0
    assert c_decision["written_duration"] == 2.0

    writer = NotationWriter()
    xml = writer.write_musicxml(
        out, ScoreMeta(time_sig_hint="4/4"), "hold_c_e", tmp_path / "src.mid"
    )
    path = tmp_path / "hold_c_e.musicxml"
    path.write_text(xml)
    parsed = list(converter.parse(path).flatten().notes)
    by_midi = {}
    for note in parsed:
        midi = int(note.pitch.midi)
        by_midi.setdefault(midi, []).append(note)
    assert 60 in by_midi and 64 in by_midi
    assert sum(float(n.quarterLength) for n in by_midi[60]) == pytest.approx(2.0)
    assert sum(float(n.quarterLength) for n in by_midi[64]) == pytest.approx(1.0)


def test_same_pitch_pulse_still_caps_pedal_tail_for_voice_search():
    from mir.performance_score import _release_hypothesis, _voice_search_events

    a = MusicalEvent(48, 0.0, 1.8, note_id="a", hand=Hand.LEFT, velocity=80)
    b = MusicalEvent(48, 1.0, 1.8, note_id="b", hand=Hand.LEFT, velocity=80)
    assert _release_hypothesis(a, [a, b]) == ("b", "pedal_tail")
    search = _voice_search_events([a, b])
    assert {e.note_id: e.duration_beats for e in search}["a"] == 1.0
    assert {e.note_id: e.duration_beats for e in search}["b"] == 1.8
    assert a.duration_beats == 1.8 and b.duration_beats == 1.8


def _mt3_left(pitch, start, duration, ident, *, voice=0):
    return MusicalEvent(
        pitch,
        start,
        duration,
        note_id=ident,
        hand=Hand.LEFT,
        voice=voice,
        voice_assigned=True,
        hand_locked=True,
        velocity=80,
        source_backend="mt3",
    )


def _musicxml_attack_spans(path):
    """Collapse MusicXML notes into attacks via per part/staff/voice/pitch ties.

    Joins only contiguous tie chains. Independent unisons (same pitch, different
    voice) remain separate. Orphan continuations and unfinished chains raise.
    """
    from music21 import converter
    from notation_engine.integrity import NotationIntegrityError, score_attacks

    try:
        attacks = score_attacks(converter.parse(path, forceSource=True))
    except NotationIntegrityError as exc:
        raise ValueError(str(exc)) from exc
    return [
        (a.pitch, a.start, a.end - a.start, a.pieces, a.tied, a.track, a.voice, a.staff)
        for a in attacks
    ]


def _assert_exported_attacks(xml: str, path, expected_by_id: dict[str, tuple[int, float, float]]):
    """Verify exact attack inventory: multiplicity, pitch, onset, written duration."""
    path.write_text(xml)
    spans = _musicxml_attack_spans(path)
    remaining = list(spans)
    for note_id, (midi, onset, dur) in expected_by_id.items():
        match_i = None
        for i, (m, o, d, *_rest) in enumerate(remaining):
            if m == midi and abs(o - onset) < 1e-6 and abs(d - dur) < 1e-6:
                match_i = i
                break
        assert match_i is not None, (note_id, (midi, onset, dur), spans)
        remaining.pop(match_i)
    assert remaining == [], f"extra exported attacks: {remaining}; expected {expected_by_id}"
    assert len(spans) == len(expected_by_id)
    assert sum(s[2] for s in spans) == pytest.approx(
        sum(dur for _m, _o, dur in expected_by_id.values())
    )


def _write_fixture_musicxml(path, body: str):
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN"'
        ' "http://www.musicxml.org/dtds/partwise.dtd">'
        '<score-partwise version="3.1">'
        "<part-list><score-part id=\"P1\"><part-name>Music</part-name></score-part></part-list>"
        f"<part id=\"P1\">{body}</part></score-partwise>"
    )
    return path


def _note_xml(
    *,
    step,
    octave,
    duration,
    voice=1,
    staff=1,
    tie=None,
    chord=False,
    alter=None,
):
    alter_xml = f"<alter>{alter}</alter>" if alter is not None else ""
    tie_xml = ""
    if tie:
        tie_xml = f'<tie type="{tie}"/>'
        notations = f'<notations><tied type="{tie}"/></notations>'
    else:
        notations = ""
    chord_xml = "<chord/>" if chord else ""
    return (
        f"<note>{chord_xml}<pitch><step>{step}</step>{alter_xml}"
        f"<octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration><voice>{voice}</voice>"
        f"<type>quarter</type>{tie_xml}<staff>{staff}</staff>{notations}</note>"
    )


def test_musicxml_attack_spans_tied_c_with_interleaved_e(tmp_path):
    """Tied C must survive an interleaved E on another voice."""
    body = (
        '<measure number="1"><attributes><divisions>1</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        + _note_xml(step="C", octave=4, duration=4, voice=1, tie="start")
        + "<backup><duration>3</duration></backup>"
        + _note_xml(step="E", octave=4, duration=1, voice=2)
        + "</measure>"
        '<measure number="2">'
        + _note_xml(step="C", octave=4, duration=4, voice=1, tie="stop")
        + "</measure>"
    )
    path = _write_fixture_musicxml(tmp_path / "tied_c_e.xml", body)
    spans = _musicxml_attack_spans(path)
    assert len(spans) == 2
    c = next(s for s in spans if s[0] == 60)
    e = next(s for s in spans if s[0] == 64)
    assert c[1] == pytest.approx(0.0)
    assert c[2] == pytest.approx(8.0)
    assert c[3] == 2 and c[4]
    assert e[1] == pytest.approx(1.0)
    assert e[2] == pytest.approx(1.0)
    assert sum(s[2] for s in spans) == pytest.approx(9.0)


def test_musicxml_attack_spans_simultaneous_tied_voices(tmp_path):
    body = (
        '<measure number="1"><attributes><divisions>1</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        + _note_xml(step="C", octave=4, duration=4, voice=1, tie="start")
        + "<backup><duration>4</duration></backup>"
        + _note_xml(step="G", octave=4, duration=4, voice=2, tie="start")
        + "</measure>"
        '<measure number="2">'
        + _note_xml(step="C", octave=4, duration=4, voice=1, tie="stop")
        + "<backup><duration>4</duration></backup>"
        + _note_xml(step="G", octave=4, duration=4, voice=2, tie="stop")
        + "</measure>"
    )
    path = _write_fixture_musicxml(tmp_path / "sim_ties.xml", body)
    spans = _musicxml_attack_spans(path)
    assert len(spans) == 2
    assert {s[0] for s in spans} == {60, 67}
    assert all(abs(s[2] - 8.0) < 1e-6 and s[3] == 2 for s in spans)
    assert {s[6] for s in spans} == {"1", "2"}


def test_musicxml_attack_spans_chord_ties(tmp_path):
    body = (
        '<measure number="1"><attributes><divisions>1</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        + _note_xml(step="C", octave=4, duration=4, voice=1, tie="start")
        + _note_xml(step="E", octave=4, duration=4, voice=1, tie="start", chord=True)
        + "</measure>"
        '<measure number="2">'
        + _note_xml(step="C", octave=4, duration=4, voice=1, tie="stop")
        + _note_xml(step="E", octave=4, duration=4, voice=1, tie="stop", chord=True)
        + "</measure>"
    )
    path = _write_fixture_musicxml(tmp_path / "chord_ties.xml", body)
    spans = _musicxml_attack_spans(path)
    assert len(spans) == 2
    assert {s[0] for s in spans} == {60, 64}
    assert all(abs(s[2] - 8.0) < 1e-6 and s[3] == 2 and s[4] for s in spans)
    assert sum(s[2] for s in spans) == pytest.approx(16.0)


def test_musicxml_attack_spans_repeated_same_pitch_attacks(tmp_path):
    body = (
        '<measure number="1"><attributes><divisions>1</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        + _note_xml(step="C", octave=4, duration=1, voice=1)
        + _note_xml(step="C", octave=4, duration=1, voice=1)
        + "<backup><duration>2</duration></backup>"
        + _note_xml(step="C", octave=4, duration=1, voice=2)
        + "</measure>"
    )
    path = _write_fixture_musicxml(tmp_path / "reattacks.xml", body)
    spans = _musicxml_attack_spans(path)
    assert len(spans) == 3
    assert all(s[0] == 60 and abs(s[2] - 1.0) < 1e-6 and s[3] == 1 for s in spans)
    assert sum(s[2] for s in spans) == pytest.approx(3.0)
    assert sorted(s[1] for s in spans if s[6] == "1") == pytest.approx([0.0, 1.0])
    assert any(s[6] == "2" and abs(s[1] - 0.0) < 1e-6 for s in spans)


def test_musicxml_attack_spans_rejects_orphan_continue(tmp_path):
    body = (
        '<measure number="1"><attributes><divisions>1</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        + _note_xml(step="C", octave=4, duration=1, voice=1, tie="stop")
        + "</measure>"
    )
    path = _write_fixture_musicxml(tmp_path / "orphan.xml", body)
    with pytest.raises(ValueError, match="Orphan|non-contiguous"):
        _musicxml_attack_spans(path)


def test_musicxml_attack_spans_rejects_unfinished_chain(tmp_path):
    body = (
        '<measure number="1"><attributes><divisions>1</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        + _note_xml(step="C", octave=4, duration=4, voice=1, tie="start")
        + "</measure>"
    )
    path = _write_fixture_musicxml(tmp_path / "unfinished.xml", body)
    with pytest.raises(ValueError, match="Unclosed"):
        _musicxml_attack_spans(path)


def test_musicxml_attack_spans_rejects_noncontiguous_continue(tmp_path):
    body = (
        '<measure number="1"><attributes><divisions>1</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        + _note_xml(step="C", octave=4, duration=1, voice=1, tie="start")
        + '<note><rest/><duration>3</duration><voice>1</voice><staff>1</staff></note>'
        + "</measure>"
        '<measure number="2">'
        + '<note><rest/><duration>1</duration><voice>1</voice><staff>1</staff></note>'
        + _note_xml(step="C", octave=4, duration=1, voice=1, tie="stop")
        + "</measure>"
    )
    path = _write_fixture_musicxml(tmp_path / "gap.xml", body)
    with pytest.raises(ValueError, match="Orphan|non-contiguous"):
        _musicxml_attack_spans(path)


def test_pedal_release_targets_resolve_early_jitter_through_export(tmp_path):
    """Raw 0.99/2.01 onsets must not feed Fraction(float) into duration spelling."""
    raw = [
        _mt3_left(48, 0.0, 1.8, "a"),
        _mt3_left(48, 0.99, 1.8, "b"),
        _mt3_left(48, 2.01, 1.8, "c"),
    ]
    before = [(e.note_id, e.start_beat, e.duration_beats) for e in raw]
    out, report = quantize(raw)
    assert [(e.note_id, e.start_beat, e.duration_beats) for e in raw] == before
    notes = {n.source_id: n for n in report.notes}
    assert notes["a"].onset == Fraction(0) and notes["a"].duration == Fraction(1)
    assert notes["b"].onset == Fraction(1) and notes["b"].duration == Fraction(1)
    assert notes["c"].onset == Fraction(2)
    by_decision = {d["note_id"]: d for d in report.decisions}
    assert by_decision["a"]["release_reason"] == "pedal_tail"
    assert by_decision["a"]["release_target_id"] == "b"
    assert by_decision["a"]["release_at"] == pytest.approx(1.0)
    assert by_decision["a"]["performed_duration"] == pytest.approx(1.8)
    assert by_decision["b"]["release_target_id"] == "c"
    assert {e.note_id for e in out} == {"a", "b", "c"}

    writer = NotationWriter()
    xml = writer.write_musicxml(
        out, ScoreMeta(time_sig_hint="4/4"), "pedal_early", tmp_path / "src.mid"
    )
    _assert_exported_attacks(
        xml,
        tmp_path / "pedal_early.musicxml",
        {
            "a": (48, 0.0, 1.0),
            "b": (48, 1.0, 1.0),
            "c": (48, 2.0, float(notes["c"].duration)),
        },
    )


def test_pedal_release_targets_resolve_late_jitter_through_export(tmp_path):
    raw = [
        _mt3_left(48, 0.01, 1.8, "a"),
        _mt3_left(48, 1.01, 1.8, "b"),
        _mt3_left(48, 2.01, 1.8, "c"),
    ]
    before = [(e.note_id, e.start_beat, e.duration_beats) for e in raw]
    out, report = quantize(raw)
    assert [(e.note_id, e.start_beat, e.duration_beats) for e in raw] == before
    notes = {n.source_id: n for n in report.notes}
    assert notes["a"].onset == Fraction(0) and notes["a"].duration == Fraction(1)
    assert notes["b"].onset == Fraction(1) and notes["b"].duration == Fraction(1)
    assert notes["c"].onset == Fraction(2)
    assert {d["release_target_id"] for d in report.decisions if d["note_id"] == "a"} == {"b"}

    writer = NotationWriter()
    xml = writer.write_musicxml(
        out, ScoreMeta(time_sig_hint="4/4"), "pedal_late", tmp_path / "src.mid"
    )
    _assert_exported_attacks(
        xml,
        tmp_path / "pedal_late.musicxml",
        {
            "a": (48, 0.0, 1.0),
            "b": (48, 1.0, 1.0),
            "c": (48, 2.0, float(notes["c"].duration)),
        },
    )


def test_cross_bar_pedal_release_uses_quantized_target_onset(tmp_path):
    raw = [
        _mt3_left(48, 2.99, 1.8, "a"),
        _mt3_left(48, 4.01, 1.8, "b"),
    ]
    before = [(e.note_id, e.start_beat, e.duration_beats) for e in raw]
    out, report = quantize(raw)
    assert [(e.note_id, e.start_beat, e.duration_beats) for e in raw] == before
    notes = {n.source_id: n for n in report.notes}
    assert notes["a"].onset == Fraction(3)
    assert notes["b"].onset == Fraction(4)
    assert notes["a"].duration == Fraction(1)
    decision = next(d for d in report.decisions if d["note_id"] == "a")
    assert decision["release_reason"] == "pedal_tail"
    assert decision["release_target_id"] == "b"
    assert decision["release_at"] == pytest.approx(4.0)

    writer = NotationWriter()
    xml = writer.write_musicxml(
        out, ScoreMeta(time_sig_hint="4/4"), "pedal_crossbar", tmp_path / "src.mid"
    )
    _assert_exported_attacks(
        xml,
        tmp_path / "pedal_crossbar.musicxml",
        {
            "a": (48, 3.0, 1.0),
            "b": (48, 4.0, float(notes["b"].duration)),
        },
    )


def test_release_target_in_other_voice_resolves_to_quantized_onset():
    """Pedal target may live in another written voice after lane allocation."""
    raw = [
        _mt3_left(48, 0.0, 1.8, "a", voice=0),
        _mt3_left(48, 0.99, 1.8, "b", voice=1),
        # Inner different pitch forces a second lane while a→b remains pedal_tail.
        _mt3_left(52, 0.99, 0.5, "inner", voice=1),
    ]
    before = [(e.note_id, e.start_beat, e.duration_beats) for e in raw]
    out, report = quantize(raw)
    assert [(e.note_id, e.start_beat, e.duration_beats) for e in raw] == before
    notes = {n.source_id: n for n in report.notes}
    assert notes["a"].duration == Fraction(1)
    assert notes["b"].onset == Fraction(1)
    decision = next(d for d in report.decisions if d["note_id"] == "a")
    assert decision["release_target_id"] == "b"
    assert decision["release_at"] == pytest.approx(1.0)
    assert {e.note_id for e in out} == {"a", "b", "inner"}


def test_accepted_release_ignores_earlier_same_voice_neighbor(tmp_path):
    """Pedal A→B must not truncate to an inner same-voice attack before B."""
    raw = [
        _mt3_left(48, 0.0, 1.8, "a", voice=0),
        _mt3_left(55, 0.5, 0.25, "inner", voice=0),
        _mt3_left(48, 0.99, 1.8, "b", voice=1),
    ]
    before = [(e.note_id, e.start_beat, e.duration_beats, e.pitch) for e in raw]
    out, report = quantize(raw)
    assert [(e.note_id, e.start_beat, e.duration_beats, e.pitch) for e in raw] == before
    notes = {n.source_id: n for n in report.notes}
    assert notes["a"].onset == Fraction(0)
    assert notes["a"].duration == Fraction(1)
    assert notes["inner"].onset == Fraction(1, 2)
    assert notes["inner"].duration == Fraction(1, 4)
    assert notes["b"].onset == Fraction(1)
    decision = next(d for d in report.decisions if d["note_id"] == "a")
    assert decision["release_reason"] == "pedal_tail"
    assert decision["release_target_id"] == "b"
    assert decision["release_at"] == pytest.approx(1.0)
    assert decision["written_duration"] == pytest.approx(1.0)
    assert decision["performed_duration"] == pytest.approx(1.8)
    # Inner overlap is a separate written lane, not a release cutoff.
    assert notes["a"].voice != notes["inner"].voice
    assert {e.note_id for e in out} == {"a", "inner", "b"}

    writer = NotationWriter()
    xml = writer.write_musicxml(
        out, ScoreMeta(time_sig_hint="4/4"), "release_vs_inner", tmp_path / "src.mid"
    )
    path = tmp_path / "release_vs_inner.musicxml"
    _assert_exported_attacks(
        xml,
        path,
        {
            "a": (48, 0.0, 1.0),
            "inner": (55, 0.5, 0.25),
            "b": (48, 1.0, float(notes["b"].duration)),
        },
    )
    # a and b are distinct reattacks (not one tied sustain through beat 1).
    spans = _musicxml_attack_spans(path)
    pitch48 = [s for s in spans if s[0] == 48]
    assert len(pitch48) >= 2
    assert abs(pitch48[0][1] - 0.0) < 1e-6 and abs(pitch48[0][2] - 1.0) < 1e-6
    assert abs(pitch48[1][1] - 1.0) < 1e-6


def test_cross_bar_written_release_exports_necessary_ties(tmp_path):
    """Accepted pedal release spanning a barline exports tied pieces, not one float."""
    raw = [
        _mt3_left(48, 3.01, 2.8, "hold", voice=0),
        _mt3_left(48, 5.01, 1.8, "next", voice=1),
    ]
    before = [(e.note_id, e.start_beat, e.duration_beats) for e in raw]
    out, report = quantize(raw)
    assert [(e.note_id, e.start_beat, e.duration_beats) for e in raw] == before
    notes = {n.source_id: n for n in report.notes}
    assert notes["hold"].onset == Fraction(3)
    assert notes["next"].onset == Fraction(5)
    decision = next(d for d in report.decisions if d["note_id"] == "hold")
    assert decision["release_reason"] == "pedal_tail"
    assert decision["release_target_id"] == "next"
    assert notes["hold"].duration == Fraction(2)
    assert {e.note_id for e in out} == {"hold", "next"}

    writer = NotationWriter()
    xml = writer.write_musicxml(
        out, ScoreMeta(time_sig_hint="4/4"), "release_crossbar_ties", tmp_path / "src.mid"
    )
    path = tmp_path / "release_crossbar_ties.musicxml"
    _assert_exported_attacks(
        xml,
        path,
        {
            "hold": (48, 3.0, 2.0),
            "next": (48, 5.0, float(notes["next"].duration)),
        },
    )
    spans = _musicxml_attack_spans(path)
    hold_span = next(s for s in spans if s[0] == 48 and abs(s[1] - 3.0) < 1e-6)
    assert hold_span[3] > 1 and hold_span[4], "barline crossing must export ties"
    assert "<tie" in xml.lower()


def test_printed_lanes_reuse_inactive_musical_voices():
    """Distinct musical lines pack into peak concurrency, not historical IDs."""
    from mir.performance_score import _stable_lanes

    events = [
        MusicalEvent(80, 0.0, 0.375, note_id="a", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(82, 0.25, 0.25, note_id="b", hand=Hand.RIGHT, voice=1,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(80, 0.5, 0.75, note_id="c", hand=Hand.RIGHT, voice=2,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(77, 1.083, 1.0, note_id="d", hand=Hand.RIGHT, voice=3,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(75, 2.125, 0.75, note_id="e", hand=Hand.RIGHT, voice=2,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
    ]
    exact = {
        "a": (Fraction(0), Fraction(3, 8), "binary", "g"),
        "b": (Fraction(1, 4), Fraction(1, 4), "binary", "g"),
        "c": (Fraction(1, 2), Fraction(3, 4), "binary", "g"),
        "d": (Fraction(13, 12), Fraction(1), "binary", "g"),
        "e": (Fraction(17, 8), Fraction(3, 4), "binary", "g"),
    }
    # Written durations stay exactly as supplied to lane allocation.
    before_durs = {i: exact[i][1] for i in exact}
    out = _stable_lanes(events, exact)
    by_id = {e.note_id: e for e in out}
    assert max(e.voice for e in out) <= 1
    assert by_id["a"].voice != by_id["b"].voice
    assert by_id["c"].voice != by_id["d"].voice
    # Musical line 2 (c then e) prefers its home lane when free.
    assert by_id["c"].voice == by_id["e"].voice
    assert before_durs == {i: exact[i][1] for i in exact}
    assert all(e.duration_beats == dur for e, dur in zip(
        events, [0.375, 0.25, 0.75, 1.0, 0.75]
    ))


def test_crossing_lines_keep_home_lane_when_free():
    from mir.performance_score import _stable_lanes

    events = [
        MusicalEvent(72, 0.0, 1.0, note_id="hi0", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(60, 0.0, 1.0, note_id="lo0", hand=Hand.RIGHT, voice=1,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(60, 1.0, 1.0, note_id="hi1", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(72, 1.0, 1.0, note_id="lo1", hand=Hand.RIGHT, voice=1,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
    ]
    exact = {e.note_id: (Fraction(e.start_beat), Fraction(1), "binary", "g") for e in events}
    out = _stable_lanes(events, exact)
    by_id = {e.note_id: e for e in out}
    assert by_id["hi0"].voice == by_id["hi1"].voice
    assert by_id["lo0"].voice == by_id["lo1"].voice
    assert by_id["hi0"].voice != by_id["lo0"].voice


def test_chord_ties_share_lane_and_cross_bar(tmp_path):
    raw = [
        MusicalEvent(60, 3.0, 2.0, note_id="c", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(64, 3.0, 2.0, note_id="e", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
    ]
    before = [(x.note_id, x.start_beat, x.duration_beats) for x in raw]
    out, report = quantize(raw)
    assert [(x.note_id, x.start_beat, x.duration_beats) for x in raw] == before
    notes = {n.source_id: n for n in report.notes}
    assert notes["c"].voice == notes["e"].voice
    assert notes["c"].duration == Fraction(2)
    assert notes["e"].duration == Fraction(2)
    writer = NotationWriter()
    xml = writer.write_musicxml(
        out, ScoreMeta(time_sig_hint="4/4"), "chord_tie_lanes", tmp_path / "src.mid"
    )
    _assert_exported_attacks(
        xml,
        tmp_path / "chord_tie_lanes.musicxml",
        {"c": (60, 3.0, 2.0), "e": (64, 3.0, 2.0)},
    )
    assert "<tie" in xml.lower()


def test_repeated_pitch_reattacks_remain_distinct_lanes_when_overlapping():
    raw = [
        MusicalEvent(60, 0.0, 2.0, note_id="hold", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(60, 0.5, 0.5, note_id="re", hand=Hand.RIGHT, voice=1,
                     voice_assigned=True, hand_locked=True, velocity=70, source_backend="mt3"),
    ]
    out, report = quantize(raw)
    notes = {n.source_id: n for n in report.notes}
    assert notes["hold"].duration == Fraction(2)
    assert notes["re"].duration == Fraction(1, 2)
    assert notes["hold"].voice != notes["re"].voice
    assert {e.note_id for e in out} == {"hold", "re"}


def test_voice_metrics_separate_distinct_ids_from_peak_concurrency():
    from evaluation.hands_rhythm_metrics import _voice_distribution

    events = [
        MusicalEvent(80, 0.0, 0.375, note_id="a", hand=Hand.RIGHT, voice=0, velocity=80),
        MusicalEvent(82, 0.25, 0.25, note_id="b", hand=Hand.RIGHT, voice=1, velocity=80),
        MusicalEvent(80, 0.5, 0.75, note_id="c", hand=Hand.RIGHT, voice=0, velocity=80),
        MusicalEvent(77, 1.083, 1.0, note_id="d", hand=Hand.RIGHT, voice=1, velocity=80),
        # Chord on one lane while a sustain occupies another.
        MusicalEvent(48, 0.0, 2.0, note_id="bass", hand=Hand.LEFT, voice=0, velocity=80),
        MusicalEvent(55, 1.0, 1.0, note_id="c1", hand=Hand.LEFT, voice=1, velocity=70),
        MusicalEvent(60, 1.0, 1.0, note_id="c2", hand=Hand.LEFT, voice=1, velocity=70),
    ]
    probe = _voice_distribution(events, measure_quarter_length=4.0)
    assert probe["max_peak_concurrency_in_measure_staff"] == 2
    assert probe["max_peak_note_concurrency_in_measure_staff"] >= 3
    assert probe["max_distinct_voice_ids_in_measure_staff"] == 2


def test_lane_borrow_then_melody_returns_home():
    """Inner line borrows a free lane; melody returns to its home when free."""
    from mir.performance_score import _stable_lanes

    events = [
        MusicalEvent(76, 0.0, 1.0, note_id="mel0", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, velocity=80, source_backend="mt3"),
        MusicalEvent(64, 0.5, 1.0, note_id="inner", hand=Hand.RIGHT, voice=1,
                     voice_assigned=True, velocity=70, source_backend="mt3"),
        # Melody returns after inner has started; home lane 0 still occupied by
        # mel0 until beat 1, so mel1 cannot reclaim yet — place after mel0 ends.
        MusicalEvent(79, 1.0, 1.0, note_id="mel1", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, velocity=80, source_backend="mt3"),
        # Inner continues while melody is back on home; must stay independent.
        MusicalEvent(67, 1.5, 0.5, note_id="inner2", hand=Hand.RIGHT, voice=1,
                     voice_assigned=True, velocity=70, source_backend="mt3"),
    ]
    exact = {
        "mel0": (Fraction(0), Fraction(1), "binary", "g"),
        "inner": (Fraction(1, 2), Fraction(1), "binary", "g"),
        "mel1": (Fraction(1), Fraction(1), "binary", "g"),
        "inner2": (Fraction(3, 2), Fraction(1, 2), "binary", "g"),
    }
    out = _stable_lanes(events, exact)
    by_id = {e.note_id: e for e in out}
    assert by_id["mel0"].voice == by_id["mel1"].voice == 0
    assert by_id["inner"].voice == by_id["inner2"].voice
    assert by_id["mel0"].voice != by_id["inner"].voice
    assert by_id["mel0"].musical_voice == 0 and by_id["mel1"].musical_voice == 0
    assert by_id["inner"].musical_voice == 1 and by_id["inner2"].musical_voice == 1
    assert all(e.voice_provenance == "supplied" for e in out)


def test_simultaneous_returning_lines_keep_independent_homes():
    from mir.performance_score import _stable_lanes

    events = [
        MusicalEvent(72, 0.0, 1.0, note_id="a0", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, velocity=80, source_backend="mt3"),
        MusicalEvent(60, 0.0, 1.0, note_id="b0", hand=Hand.RIGHT, voice=1,
                     voice_assigned=True, velocity=80, source_backend="mt3"),
        # Temporary third line forces a borrow of capacity, then both return.
        MusicalEvent(66, 0.5, 0.5, note_id="x", hand=Hand.RIGHT, voice=2,
                     voice_assigned=True, velocity=70, source_backend="mt3"),
        MusicalEvent(74, 1.0, 1.0, note_id="a1", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, velocity=80, source_backend="mt3"),
        MusicalEvent(59, 1.0, 1.0, note_id="b1", hand=Hand.RIGHT, voice=1,
                     voice_assigned=True, velocity=80, source_backend="mt3"),
    ]
    exact = {e.note_id: (Fraction(str(e.start_beat)).limit_denominator(8),
                         Fraction(str(e.duration_beats)).limit_denominator(8),
                         "binary", "g") for e in events}
    out = _stable_lanes(events, exact)
    by_id = {e.note_id: e for e in out}
    assert by_id["a0"].voice == by_id["a1"].voice
    assert by_id["b0"].voice == by_id["b1"].voice
    assert by_id["a0"].voice != by_id["b0"].voice
    assert by_id["a0"].musical_voice == 0 and by_id["b0"].musical_voice == 1
    assert by_id["x"].musical_voice == 2
    # Independent lines are not merged onto one printed lane while overlapping.
    assert by_id["a0"].voice != by_id["x"].voice or by_id["b0"].voice != by_id["x"].voice


def test_lane_reuse_export_roundtrip_preserves_attacks_and_identity(tmp_path):
    raw = [
        MusicalEvent(76, 0.0, 1.0, note_id="mel0", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
        MusicalEvent(64, 0.5, 1.0, note_id="inner", hand=Hand.RIGHT, voice=1,
                     voice_assigned=True, hand_locked=True, velocity=70, source_backend="mt3"),
        MusicalEvent(79, 1.0, 1.0, note_id="mel1", hand=Hand.RIGHT, voice=0,
                     voice_assigned=True, hand_locked=True, velocity=80, source_backend="mt3"),
    ]
    before = [(e.note_id, e.start_beat, e.duration_beats, e.pitch, e.voice) for e in raw]
    out, report = quantize(raw)
    assert [(e.note_id, e.start_beat, e.duration_beats, e.pitch, e.voice) for e in raw] == before
    by_dec = {d["note_id"]: d for d in report.decisions}
    assert by_dec["mel0"]["musical_voice"] == 0
    assert by_dec["mel1"]["musical_voice"] == 0
    assert by_dec["inner"]["musical_voice"] == 1
    assert by_dec["mel0"]["voice_provenance"] == "supplied"
    assert by_dec["mel0"]["printed_voice"] == by_dec["mel1"]["printed_voice"]
    assert by_dec["mel0"]["printed_voice"] != by_dec["inner"]["printed_voice"]
    # Releases / attacks unchanged: three distinct attacks, performed times intact.
    assert {n.source_id for n in report.notes} == {"mel0", "inner", "mel1"}
    assert all(d["performed_duration"] == raw_dur
               for d, raw_dur in (
                   (by_dec["mel0"], 1.0), (by_dec["inner"], 1.0), (by_dec["mel1"], 1.0)
               ))
    notes = {n.source_id: n for n in report.notes}
    assert notes["mel0"].musical_voice == 0
    assert notes["inner"].musical_voice == 1

    writer = NotationWriter()
    xml = writer.write_musicxml(
        out, ScoreMeta(time_sig_hint="4/4"), "lane_roundtrip", tmp_path / "src.mid"
    )
    _assert_exported_attacks(
        xml,
        tmp_path / "lane_roundtrip.musicxml",
        {
            "mel0": (76, float(notes["mel0"].onset), float(notes["mel0"].duration)),
            "inner": (64, float(notes["inner"].onset), float(notes["inner"].duration)),
            "mel1": (79, float(notes["mel1"].onset), float(notes["mel1"].duration)),
        },
    )


def test_lane_reuse_does_not_change_downbeat_or_release_decisions():
    raw = [
        _mt3_left(48, 0.0, 1.8, "a", voice=0),
        _mt3_left(55, 0.5, 0.25, "inner", voice=0),
        _mt3_left(48, 0.99, 1.8, "b", voice=1),
    ]
    before = [(e.note_id, e.start_beat, e.duration_beats) for e in raw]
    out, report = quantize(raw)
    assert [(e.note_id, e.start_beat, e.duration_beats) for e in raw] == before
    by_dec = {d["note_id"]: d for d in report.decisions}
    assert by_dec["a"]["release_reason"] == "pedal_tail"
    assert by_dec["a"]["release_target_id"] == "b"
    assert by_dec["a"]["score_onset"] == "0"
    assert by_dec["b"]["score_onset"] == "1"
    assert by_dec["a"]["score_beat_offset"] == 0.0
    assert {n.source_id for n in report.notes} == {"a", "inner", "b"}
