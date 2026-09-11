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
    score = writer._score_via_plan_or_legacy(
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
