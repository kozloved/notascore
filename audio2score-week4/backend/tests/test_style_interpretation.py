"""Style-aware interpretation: swing mapping, identity, and conservative fallback."""

from __future__ import annotations

import hashlib
from collections import Counter
from fractions import Fraction
from xml.etree import ElementTree as ET

import pretty_midi
import pytest
from music21 import converter

from evaluation.swing_fixtures import SWING_FIXTURES
from mir.models import MeterHypothesis
from mir.notation_settings import NotationSettings
from mir.performance_cli import convert
from mir.performance_score import quantize_notation
from mir.quantizer import QuantizerConfig
from mir.interpretation_profile import SourceStyle, STYLE_PRIORS
from mir.swing import (
    apply_playback_timing,
    apply_written_timing,
    infer_interpretation_spans,
    map_pair_fraction,
    performed_offbeat_fraction,
    span_at,
)
from mir.style_interpretation import interpret_for_notation
from mir.types import Hand, MusicalEvent
from notation_engine.swing_export import (
    assert_swing_metadata_placement,
    inject_swing_metadata,
)

METER_44 = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
METER_68 = MeterHypothesis("6/8", 6, 8, 3.0, 1.0, 1.0)
CONFIG = QuantizerConfig()


def _event(pitch, start, duration, ident, hand=Hand.RIGHT, **extra):
    return MusicalEvent(
        pitch,
        start,
        duration,
        note_id=ident,
        hand=hand,
        velocity=80,
        start_time_sec=float(start) * 0.5,
        end_time_sec=(float(start) + float(duration)) * 0.5,
        **extra,
    )


def _swing_pair_events(bars=2, ratio=2.0, *, start_id=0):
    f = performed_offbeat_fraction(ratio)
    events = []
    n = 0
    for beat in range(bars * 4):
        events.append(_event(72, float(beat), f, f"d{start_id + n}"))
        n += 1
        events.append(_event(74, float(beat) + f, 1.0 - f, f"o{start_id + n}"))
        n += 1
    return events


def _midi_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(path):
    midi = pretty_midi.PrettyMIDI(str(path))
    return Counter(
        (int(note.pitch), round(note.start, 6))
        for inst in midi.instruments
        for note in inst.notes
    )


def _tuplet_count(xml: str) -> int:
    return xml.lower().count("<time-modification>")


def test_mapping_is_reversible_for_supported_ratios():
    for ratio in (1.5, 2.0, 3.0):
        f_p = performed_offbeat_fraction(ratio)
        assert abs(map_pair_fraction(f_p, ratio) - 0.5) < 1e-9
        assert abs(map_pair_fraction(0.0, ratio) - 0.0) < 1e-9
        written = map_pair_fraction(f_p, ratio)
        assert abs(map_pair_fraction(written, ratio, reverse=True) - f_p) < 1e-9


def test_straight_eighths_with_jitter_stay_straight():
    events = [
        _event(72, i * 0.5 + (0.02 if i % 2 else -0.015), 0.42, f"n{i}")
        for i in range(16)
    ]
    out, spans, summary = interpret_for_notation(events, METER_44, NotationSettings())
    assert summary["rhythmic_feel"] in {"straight", "mixed"}
    swing = [s for s in spans if s.feel.startswith("swing") or s.feel == "shuffle"]
    assert not swing
    assert [e.pitch for e in out] == [e.pitch for e in events]
    assert [e.note_id for e in out] == [e.note_id for e in events]


def test_repeated_2_to_1_swing_writes_eighths():
    events = _swing_pair_events(bars=2, ratio=2.0)
    settings = NotationSettings.from_dict({"source_style": "jazz"})
    out, spans, summary = interpret_for_notation(events, METER_44, settings)
    assert summary["rhythmic_feel"] == "swing_eighths"
    assert any(s.feel == "swing_eighths" for s in spans)
    quantized, _dec, report = quantize_notation(
        events, METER_44, config=CONFIG, settings=settings
    )
    onsets = sorted({Fraction(ev.start_beat).limit_denominator(16) for ev in quantized})
    eighths = [o for o in onsets if o.denominator <= 2]
    assert len(eighths) >= 12
    families = [row["rhythm_family"] for row in report.decisions]
    assert families.count("triplet") <= 2
    assert report.summary["source_notes"] == len(events)
    ids = [e.note_id for e in quantized]
    assert ids == [e.note_id for e in events]
    assert {e.pitch for e in quantized} == {e.pitch for e in events}


def test_lighter_3_to_2_swing_estimates_ratio():
    events = _swing_pair_events(bars=2, ratio=1.5)
    settings = NotationSettings.from_dict({"source_style": "jazz"})
    _out, spans, summary = interpret_for_notation(events, METER_44, settings)
    swing = [s for s in spans if s.feel == "swing_eighths"]
    assert swing
    ratio = swing[0].ratio
    assert ratio is not None
    assert 1.3 <= ratio <= 1.8
    assert summary["rhythmic_feel"] == "swing_eighths"


def test_genuine_triplets_inside_swing_are_preserved():
    events = _swing_pair_events(bars=1, ratio=2.0)
    events += [
        _event(76, 4.0, 1.0 / 3.0, "t0"),
        _event(77, 4.0 + 1.0 / 3.0, 1.0 / 3.0, "t1"),
        _event(79, 4.0 + 2.0 / 3.0, 1.0 / 3.0, "t2"),
    ]
    f = performed_offbeat_fraction(2.0)
    for beat in range(5, 8):
        events.append(_event(72, float(beat), f, f"d5{beat}"))
        events.append(_event(74, float(beat) + f, 1.0 - f, f"o5{beat}"))
    settings = NotationSettings.from_dict({"source_style": "jazz"})
    quantized, _dec, report = quantize_notation(
        events, METER_44, config=CONFIG, settings=settings
    )
    by_id = {e.note_id: e for e in quantized}
    assert abs(by_id["t1"].start_beat - (4.0 + 1.0 / 3.0)) < 0.05
    assert any(
        d["rhythm_family"] == "triplet"
        for d in report.decisions
        if d["note_id"].startswith("t")
    )
    assert report.summary["detected_interpretation"]["rhythmic_feel"] in {
        "swing_eighths",
        "mixed",
    }


def test_dotted_rhythms_remain_dotted():
    events = []
    for beat in range(8):
        events.append(_event(67, float(beat), 0.75, f"long{beat}"))
        events.append(_event(69, float(beat) + 0.75, 0.25, f"short{beat}"))
    for settings in (
        NotationSettings(),
        NotationSettings.from_dict({"source_style": "jazz"}),
    ):
        _out, spans, summary = interpret_for_notation(events, METER_44, settings)
        assert summary["rhythmic_feel"] == "straight"
        assert all(s.feel == "straight" for s in spans)
    quantized, _dec, report = quantize_notation(
        events, METER_44, config=CONFIG, settings=NotationSettings()
    )
    shorts = [e for e in quantized if e.note_id.startswith("short")]
    assert all(abs(e.start_beat - (int(e.start_beat) + 0.75)) < 0.08 for e in shorts)
    assert report.summary["source_notes"] == 16


def test_rubato_without_swing_stays_conservative():
    t = 0.0
    events = []
    for i in range(8):
        events.append(_event(60 + i, t, 0.9, f"r{i}"))
        t += 1.0 + i * 0.06
    _out, spans, summary = interpret_for_notation(events, METER_44, NotationSettings())
    assert summary["rhythmic_feel"] == "straight"
    assert all(s.feel == "straight" for s in spans)


def test_compound_6_8_is_not_swing():
    events = [_event(64, i * 0.5, 0.45, f"c{i}") for i in range(12)]
    jazz = NotationSettings.from_dict({"source_style": "jazz", "rhythmic_feel": "swing_eighths"})
    _out, spans, summary = interpret_for_notation(events, METER_68, jazz)
    assert all(s.feel == "straight" for s in spans)
    assert summary["rhythmic_feel"] == "straight"


def test_straight_to_swing_section_transition():
    events = [_event(72, i * 0.5, 0.42, f"s{i}") for i in range(8)]
    f = performed_offbeat_fraction(2.0)
    n = 0
    for beat in range(4, 8):
        events.append(_event(76, float(beat), f, f"swd{n}"))
        n += 1
        events.append(_event(77, float(beat) + f, 1.0 - f, f"swo{n}"))
        n += 1
    settings = NotationSettings.from_dict({"source_style": "jazz"})
    spans = infer_interpretation_spans(events, METER_44, settings.interpretation_profile)
    feels = [s.feel for s in spans]
    assert "straight" in feels
    assert "swing_eighths" in feels
    assert spans[0].start_beat < spans[-1].start_beat


def test_sparse_evidence_falls_back():
    events = [_event(72, float(i), 0.9, f"q{i}") for i in range(8)]
    events.append(_event(74, 2.0 + 2.0 / 3.0, 0.3, "lonely"))
    _out, spans, summary = interpret_for_notation(events, METER_44, NotationSettings())
    assert summary["rhythmic_feel"] == "straight"
    assert all(s.feel == "straight" for s in spans)


def test_chords_voices_and_barline_sustain_keep_identity():
    events = []
    f = performed_offbeat_fraction(2.0)
    for beat in range(8):
        for pitch in (60, 64, 67):
            events.append(_event(pitch, float(beat), f, f"c{pitch}-{beat}", hand=Hand.LEFT))
            events.append(
                _event(pitch + 12, float(beat) + f, 1.0 - f, f"m{pitch}-{beat}", hand=Hand.RIGHT)
            )
    events.append(_event(48, 0.0, 6.2, "pedal", hand=Hand.LEFT))
    before = [(e.note_id, e.pitch, e.start_time_sec, e.end_time_sec) for e in events]
    settings = NotationSettings.from_dict({"source_style": "jazz"})
    out, spans, _summary = interpret_for_notation(events, METER_44, settings)
    assert [(e.note_id, e.pitch, e.start_time_sec, e.end_time_sec) for e in out] == before
    assert len(out) == len(events)
    assert any(s.feel == "swing_eighths" for s in spans)
    quantized, _dec, report = quantize_notation(
        events, METER_44, config=CONFIG, settings=settings
    )
    assert len(quantized) == len(events)
    assert {e.note_id for e in quantized} == {e.note_id for e in events}
    pedal = next(e for e in quantized if e.note_id == "pedal")
    assert pedal.duration_beats >= 6.0
    assert report.summary["source_notes"] == len(events)


def test_user_override_forces_swing_and_old_defaults_do_not():
    events = _swing_pair_events(bars=2, ratio=2.0)
    auto = interpret_for_notation(events, METER_44, NotationSettings())[2]
    forced = NotationSettings.from_dict({"rhythmic_feel": "swing_eighths", "swing_ratio": 2.0})
    _out, spans, summary = interpret_for_notation(events, METER_44, forced)
    assert all(s.origin == "user_override" for s in spans)
    assert summary["origin"] == "user_override"
    straight = NotationSettings.from_dict({"rhythmic_feel": "straight"})
    _o2, spans2, summary2 = interpret_for_notation(events, METER_44, straight)
    assert summary2["rhythmic_feel"] == "straight"
    assert all(s.origin == "user_override" for s in spans2)
    # Defaults remain a valid empty request.
    assert auto["profile"]["rhythmic_feel"] == "auto"


def test_long_notes_are_not_shortened_to_swing_slots():
    events = [
        _event(72, 0.0, 3.67, "held"),
        _event(76, 2.0 / 3.0, 1.0 / 3.0, "off"),
        _event(76, 1.0 + 2.0 / 3.0, 1.0 / 3.0, "off2"),
        _event(76, 2.0 + 2.0 / 3.0, 1.0 / 3.0, "off3"),
        _event(76, 3.0 + 2.0 / 3.0, 1.0 / 3.0, "off4"),
    ]
    settings = NotationSettings.from_dict({"rhythmic_feel": "swing_eighths", "swing_ratio": 2.0})
    out, _spans, _summary = interpret_for_notation(events, METER_44, settings)
    held = next(e for e in out if e.note_id == "held")
    assert held.duration_beats >= 3.6
    assert held.start_time_sec == events[0].start_time_sec


def test_musicxml_swing_metadata_is_injected_without_music21():
    from mir.swing import InterpretationSpan

    xml = """<?xml version="1.0"?><score-partwise version="4.0">
    <part-list><score-part id="P1"/><score-part id="P2"/></part-list>
    <part id="P1"><measure number="X1"><attributes><divisions>24</divisions>
    <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>5</octave></pitch><duration>24</duration></note>
    </measure></part>
    <part id="P2"><measure number="X1"><attributes><divisions>24</divisions>
    <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>3</octave></pitch><duration>24</duration></note>
    </measure></part></score-partwise>"""
    span = InterpretationSpan(
        start_beat=0.0,
        end_beat=4.0,
        feel="swing_eighths",
        subdivision_unit=0.5,
        ratio=1.5,
        confidence=0.9,
        evidence_count=8,
        origin="inferred",
    )
    out = inject_swing_metadata(xml, [span])
    nodes = assert_swing_metadata_placement(out)
    assert len(nodes) == 2
    assert {node["part_id"] for node in nodes} == {"P1", "P2"}
    assert all(node["first"] == "3" and node["second"] == "2" for node in nodes)
    assert all(node["swing_type"] == "eighth" for node in nodes)
    assert all(node["swing_in_sound"] and node["words_in_direction_type"] for node in nodes)
    assert "direction-type" not in out.split("<sound>", 1)[1].split("</sound>")[0]


def test_musicxml_offset_uses_inherited_divisions_not_beat_times_eight():
    from mir.swing import InterpretationSpan

    xml = """<?xml version="1.0"?><score-partwise version="4.0">
    <part id="P1"><measure number="1"><attributes><divisions>24</divisions>
    <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>96</duration></note>
    </measure></part></score-partwise>"""
    span = InterpretationSpan(
        start_beat=1.0,
        end_beat=4.0,
        feel="swing_eighths",
        subdivision_unit=0.5,
        ratio=2.0,
        confidence=1.0,
        evidence_count=4,
        origin="inferred",
    )
    out = inject_swing_metadata(xml, [span])
    nodes = assert_swing_metadata_placement(out)
    assert nodes[0]["offset"] == "24"


@pytest.mark.parametrize("name", list(SWING_FIXTURES))
def test_midi_fixtures_preserve_source_bytes_and_note_count(tmp_path, name):
    source = tmp_path / f"{name}.mid"
    digest = SWING_FIXTURES[name](source)
    original = source.read_bytes()
    assert _midi_hash(source) == digest
    output = tmp_path / f"{name}.musicxml"
    settings = NotationSettings.from_dict({"source_style": "jazz"}) if "swing" in name or name == "polyphony_chords_ties" else NotationSettings()
    report = convert(source, output, meter="6/8" if "6_8" in name else "4/4", settings=settings)
    assert source.read_bytes() == original
    midi_notes = _inventory(source)
    import json

    payload = json.loads(report.read_text())
    assert payload["quantization_summary"]["source_notes"] == len(midi_notes)
    assert len(payload["quantization_decisions"]) == len(midi_notes)
    xml = output.read_text(encoding="utf-8")
    assert "score-partwise" in xml.lower()
    score = converter.parse(output)
    assert list(score.flatten().notes)


def test_swing_fixture_has_fewer_tuplets_than_unmapped_literal(tmp_path):
    source = tmp_path / "swing.mid"
    SWING_FIXTURES["swing_2_to_1"](source)
    original = source.read_bytes()
    swing_out = tmp_path / "swing.musicxml"
    literal_out = tmp_path / "literal.musicxml"
    convert(
        source,
        swing_out,
        settings=NotationSettings.from_dict(
            {"source_style": "jazz", "rhythmic_feel": "swing_eighths", "swing_ratio": 2.0}
        ),
    )
    convert(
        source,
        literal_out,
        settings=NotationSettings.from_dict({"rhythmic_feel": "straight", "interpretation": "literal"}),
    )
    assert source.read_bytes() == original
    swing_xml = swing_out.read_text(encoding="utf-8")
    literal_xml = literal_out.read_text(encoding="utf-8")
    assert _tuplet_count(swing_xml) < _tuplet_count(literal_xml)
    assert "Swing" in swing_xml or "<swing>" in swing_xml


def test_apply_written_timing_does_not_drop_or_duplicate_notes():
    events = _swing_pair_events(bars=1, ratio=2.0)
    spans = infer_interpretation_spans(
        events,
        METER_44,
        NotationSettings.from_dict({"rhythmic_feel": "swing_eighths", "swing_ratio": 2.0}).interpretation_profile,
    )
    mapped = apply_written_timing(events, spans)
    assert [e.note_id for e in mapped] == [e.note_id for e in events]
    assert [e.pitch for e in mapped] == [e.pitch for e in events]
    off = next(e for e in mapped if e.note_id.startswith("o"))
    assert abs((off.start_beat % 1.0) - 0.5) < 0.08


def test_literal_auto_detects_swing_without_rewriting_onsets():
    events = _swing_pair_events(bars=2, ratio=2.0)
    settings = NotationSettings.from_dict({"interpretation": "literal", "source_style": "jazz"})
    out, spans, summary = interpret_for_notation(events, METER_44, settings)
    assert summary["rhythmic_feel"] == "swing_eighths"
    assert summary["maps_written_timing"] is False
    assert all(s.maps_written_timing is False for s in spans)
    off = next(e for e in out if e.note_id.startswith("o"))
    assert abs((off.start_beat % 1.0) - (2.0 / 3.0)) < 0.04


def test_clear_swing_detected_under_every_source_style():
    events = _swing_pair_events(bars=2, ratio=2.0)
    for style in SourceStyle:
        settings = NotationSettings.from_dict({"source_style": style.value})
        _out, spans, summary = interpret_for_notation(events, METER_44, settings)
        assert summary["rhythmic_feel"] in {"swing_eighths", "shuffle"}, style.value
        assert any(s.feel in {"swing_eighths", "shuffle"} for s in spans), style.value


def test_cross_voice_thirds_are_not_a_triplet():
    events = [
        _event(72, 0.0, 0.6, "a0", hand=Hand.RIGHT, voice=1),
        _event(74, 2.0 / 3.0, 0.3, "a1", hand=Hand.RIGHT, voice=1),
        _event(60, 1.0 / 3.0, 0.3, "b0", hand=Hand.LEFT, voice=1),
    ]
    for beat in range(1, 8):
        events.append(_event(72, float(beat), 0.6, f"a{beat}d", hand=Hand.RIGHT, voice=1))
        events.append(
            _event(74, float(beat) + 2.0 / 3.0, 0.3, f"a{beat}o", hand=Hand.RIGHT, voice=1)
        )
    settings = NotationSettings.from_dict({"source_style": "jazz"})
    _out, spans, summary = interpret_for_notation(events, METER_44, settings)
    assert summary["rhythmic_feel"] in {"swing_eighths", "mixed"}
    assert not any(span.triplet_exception_at(0.0) for span in spans)
    assert any(span.feel == "swing_eighths" for span in spans)


def test_triplet_in_one_hand_does_not_block_swing_in_the_other():
    events = _swing_pair_events(bars=2, ratio=2.0)
    events += [
        _event(48, 0.0, 1.0 / 3.0, "t0", hand=Hand.LEFT),
        _event(50, 1.0 / 3.0, 1.0 / 3.0, "t1", hand=Hand.LEFT),
        _event(52, 2.0 / 3.0, 1.0 / 3.0, "t2", hand=Hand.LEFT),
    ]
    settings = NotationSettings.from_dict({"source_style": "jazz"})
    out, spans, summary = interpret_for_notation(events, METER_44, settings)
    assert summary["rhythmic_feel"] in {"swing_eighths", "mixed"}
    right_off = next(e for e in out if e.note_id.startswith("o"))
    assert abs((right_off.start_beat % 1.0) - 0.5) < 0.08
    left_mid = next(e for e in out if e.note_id == "t1")
    assert abs(left_mid.start_beat - (1.0 / 3.0)) < 0.05


def test_duplicated_tracks_do_not_inflate_evidence():
    events = _swing_pair_events(bars=2, ratio=2.0)
    doubled = []
    for event in events:
        doubled.append(event)
        doubled.append(
            _event(
                event.pitch + 12,
                event.start_beat,
                event.duration_beats,
                event.note_id + "-dup",
                hand=event.hand,
                source_track_id="copy",
            )
        )
    jazz = NotationSettings.from_dict({"source_style": "jazz"}).interpretation_profile
    single = infer_interpretation_spans(events, METER_44, jazz)
    both = infer_interpretation_spans(doubled, METER_44, jazz)
    assert single[0].evidence_count == both[0].evidence_count


def test_dotted_pair_inside_swing_stays_dotted():
    events = _swing_pair_events(bars=1, ratio=2.0)
    events += [
        _event(67, 4.0, 0.75, "dot"),
        _event(69, 4.75, 0.25, "cut"),
    ]
    f = performed_offbeat_fraction(2.0)
    for beat in range(5, 8):
        events.append(_event(72, float(beat), f, f"d{beat}"))
        events.append(_event(74, float(beat) + f, 1.0 - f, f"o{beat}"))
    settings = NotationSettings.from_dict(
        {"source_style": "jazz", "rhythmic_feel": "swing_eighths", "swing_ratio": 2.0}
    )
    out, spans, summary = interpret_for_notation(events, METER_44, settings)
    assert summary["rhythmic_feel"] == "swing_eighths"
    by_id = {e.note_id: e for e in out}
    assert abs(by_id["cut"].start_beat - 4.75) < 0.04
    assert abs(by_id["dot"].duration_beats - 0.75) < 0.08
    off = next(e for e in out if e.note_id.startswith("o") and e.start_beat < 4)
    assert abs((off.start_beat % 1.0) - 0.5) < 0.08


def test_span_at_uses_half_open_boundaries():
    from mir.swing import InterpretationSpan

    spans = [
        InterpretationSpan(0.0, 4.0, "straight", 0.5, None, 1.0, 4, "inferred"),
        InterpretationSpan(4.0, 8.0, "swing_eighths", 0.5, 2.0, 1.0, 4, "inferred"),
    ]
    assert span_at(spans, 3.999).feel == "straight"
    assert span_at(spans, 4.0).feel == "swing_eighths"
    assert span_at(spans, 8.0) is None


def test_compound_override_reports_limitation():
    events = [_event(64, i * 0.5, 0.45, f"c{i}") for i in range(12)]
    jazz = NotationSettings.from_dict({"source_style": "jazz", "rhythmic_feel": "swing_eighths"})
    _out, spans, summary = interpret_for_notation(events, METER_68, jazz)
    assert all(s.feel == "straight" for s in spans)
    assert summary["limitations"]
    assert summary["limitations"][0]["kind"] == "unsupported_feel"
    assert "6/8" in summary["limitations"][0]["user_message"]


def test_style_prior_live_fields_are_the_ones_that_gate_swing():
    live = set(STYLE_PRIORS[SourceStyle.AUTO].live_fields())
    assert "min_observations" in live
    assert "tempo_flexibility" not in live
    assert "voice_independence" not in live


def test_old_output_mode_still_parses_without_changing_defaults():
    settings = NotationSettings.from_dict({"output_mode": "simplified", "interpretation": "readable"})
    assert settings.interpretation.value == "readable"
    assert settings.interpretation_profile.output_mode.value == "simplified"
    default = NotationSettings.from_dict({"interpretation": "readable"})
    assert default.interpretation_profile.output_mode.value == "faithful"
