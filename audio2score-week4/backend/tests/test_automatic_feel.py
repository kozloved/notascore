"""Automatic feel inference with default settings (no genre or feel overrides)."""

from __future__ import annotations

from collections import defaultdict
from xml.etree import ElementTree as ET

import pretty_midi
import pytest

from evaluation.swing_fixtures import SWING_FIXTURES
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.models import MeterHypothesis
from mir.notation_settings import NotationSettings
from mir.performance_cli import convert
from mir.performance_score import quantize_notation
from mir.quantizer import QuantizerConfig
from mir.style_interpretation import interpret_for_notation
from mir.types import Hand, MusicalEvent

METER_44 = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
CONFIG = QuantizerConfig()
DEFAULT = NotationSettings()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _xml_words(xml: str) -> list[str]:
    root = ET.fromstring(xml)
    return [
        (elem.text or "").strip()
        for elem in root.iter()
        if _local(elem.tag) == "words" and (elem.text or "").strip()
    ]


def _measure_words(xml: str) -> dict[str, list[str]]:
    root = ET.fromstring(xml)
    found = defaultdict(list)
    for part in root:
        if _local(part.tag) != "part":
            continue
        for measure in part:
            if _local(measure.tag) != "measure":
                continue
            number = measure.attrib.get("number") or ""
            for elem in measure.iter():
                if _local(elem.tag) == "words" and (elem.text or "").strip():
                    found[number].append(elem.text.strip())
    return dict(found)


def _convert(tmp_path, name, meter="4/4"):
    source = tmp_path / f"{name}.mid"
    digest = SWING_FIXTURES[name](source)
    original = source.read_bytes()
    output = tmp_path / f"{name}.musicxml"
    report = convert(source, output, meter=meter, settings=DEFAULT)
    assert source.read_bytes() == original
    assert digest
    return source, output, report


def _quantize_fixture(source, meter="4/4"):
    ingested = ingest_midi(source)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    hypothesis = (
        METER_44
        if meter == "4/4"
        else MeterHypothesis(meter, 6, 8, 3.0, 1.0, 1.0)
    )
    quantized, _dec, report = quantize_notation(
        events, hypothesis, config=CONFIG, settings=DEFAULT
    )
    return quantized, report


def _score_onsets(path):
    midi = pretty_midi.PrettyMIDI(str(path))
    return sorted(note.start for inst in midi.instruments for note in inst.notes)


def _raw_onsets(path):
    return _score_onsets(path)


def _by_id(events):
    return {e.note_id: e for e in events}


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


def test_defaults_do_not_require_genre_or_feel():
    assert DEFAULT.interpretation_profile.source_style.value == "auto"
    assert DEFAULT.interpretation_profile.rhythmic_feel.value == "auto"
    assert DEFAULT.interpretation_profile.swing_ratio is None


def test_clear_2_to_1_swing_writes_eighths_and_swings_playback(tmp_path):
    source, output, _report = _convert(tmp_path, "swing_2_to_1")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "swing_eighths"
    assert detected["maps_written_timing"] is True
    assert detected["user_summary"] == (
        "Swing detected — shown using conventional eighth-note notation."
    )
    assert 1.8 <= float(detected["ratio"]) <= 2.2
    by_start = sorted({round(float(e.start_beat), 4) for e in quantized})
    assert by_start[:6] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)
    assert "Swing 16ths" not in _xml_words(xml)
    assert "<swing>" in xml
    assert xml.lower().count("<time-modification>") == 0
    raw = _raw_onsets(source)
    score = _score_onsets(output.with_suffix(".score.mid"))
    assert raw[1] == pytest.approx(1.0 / 3.0, abs=0.03)
    assert score[0] == pytest.approx(0.0, abs=0.02)
    assert score[1] == pytest.approx(1.0 / 3.0, abs=0.03)
    assert score[2] == pytest.approx(0.5, abs=0.03)


def test_light_3_to_2_swing_estimates_ratio_and_writes_eighths(tmp_path):
    source, output, _report = _convert(tmp_path, "swing_3_to_2")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "swing_eighths"
    assert 1.3 <= float(detected["ratio"]) <= 1.8
    by_start = sorted({round(float(e.start_beat), 4) for e in quantized})
    assert by_start[:4] == [0.0, 0.5, 1.0, 1.5]
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)
    assert xml.lower().count("<time-modification>") == 0
    score = _score_onsets(output.with_suffix(".score.mid"))
    assert score[1] == pytest.approx(0.3, abs=0.03)
    assert score[2] == pytest.approx(0.5, abs=0.03)


def test_straight_syncopation_keeps_offbeats_without_swing(tmp_path):
    source, output, _report = _convert(tmp_path, "straight_syncopation")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "straight"
    assert detected["maps_written_timing"] is False
    assert detected.get("user_summary") in (None, "")
    starts = sorted(round(float(e.start_beat), 4) for e in quantized)
    assert 0.5 in starts
    assert 1.5 in starts
    assert 2.5 in starts
    assert 3.5 in starts
    assert 1.0 not in starts
    assert 2.0 not in starts
    xml = output.read_text(encoding="utf-8")
    assert "Swing" not in _xml_words(xml)
    assert "<swing>" not in xml
    score = _score_onsets(output.with_suffix(".score.mid"))
    assert score[1] == pytest.approx(0.25, abs=0.04)


def test_swing_plus_syncopation_keeps_written_offbeats(tmp_path):
    source, output, _report = _convert(tmp_path, "swing_plus_syncopation")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "swing_eighths"
    starts = sorted(round(float(e.start_beat), 4) for e in quantized)
    assert starts[0] == 0.0
    assert 0.5 in starts
    assert 1.5 in starts
    assert 2.5 in starts
    assert 3.5 in starts
    assert 1.0 not in starts
    assert 2.0 not in starts
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)
    assert xml.lower().count("<time-modification>") == 0


def test_genuine_triplets_are_not_relabeled_swing(tmp_path):
    source, output, _report = _convert(tmp_path, "genuine_triplets")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "straight"
    assert detected["maps_written_timing"] is False
    thirds = [
        e
        for e in quantized
        if abs((float(e.start_beat) % 1.0) - (1.0 / 3.0)) < 0.05
    ]
    assert len(thirds) >= 6
    xml = output.read_text(encoding="utf-8")
    assert "Swing" not in _xml_words(xml)
    assert xml.lower().count("<time-modification>") >= 6
    families = [row["rhythm_family"] for row in report.decisions]
    assert families.count("triplet") >= 8


def test_dotted_figures_inside_swing_stay_dotted(tmp_path):
    source, output, _report = _convert(tmp_path, "dotted_inside_swing")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "swing_eighths"
    dotted = [e for e in quantized if int(e.pitch) in {67, 69}]
    by_pitch = {e.pitch: round(float(e.start_beat), 4) for e in dotted}
    assert by_pitch[67] == 4.0
    assert by_pitch[69] == 4.75
    eighths = sorted(
        round(float(e.start_beat), 4)
        for e in quantized
        if e.start_beat < 4.0
    )
    assert eighths[:4] == [0.0, 0.5, 1.0, 1.5]
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)


def test_expressive_straight_playing_is_not_swing(tmp_path):
    source, output, _report = _convert(tmp_path, "straight_eighths_jitter")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "straight"
    assert detected.get("user_summary") in (None, "")
    by_start = sorted({round(float(e.start_beat), 4) for e in quantized})
    assert by_start[:4] == [0.0, 0.5, 1.0, 1.5]
    xml = output.read_text(encoding="utf-8")
    assert "Swing" not in _xml_words(xml)
    score = _score_onsets(output.with_suffix(".score.mid"))
    assert score[1] == pytest.approx(0.25, abs=0.04)


def test_independent_voices_keep_separate_rhythms(tmp_path):
    source, output, _report = _convert(tmp_path, "independent_voices")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "swing_eighths"
    bass = sorted(round(float(e.start_beat), 4) for e in quantized if e.pitch == 48)
    treble_off = sorted(
        round(float(e.start_beat), 4) for e in quantized if e.pitch == 74
    )
    assert bass[:4] == [0.0, 1.0, 2.0, 3.0]
    assert treble_off[:4] == [0.5, 1.5, 2.5, 3.5]
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)
    assert xml.lower().count("<time-modification>") == 0


def test_straight_swing_transition_marks_are_stable(tmp_path):
    source, output, _report = _convert(tmp_path, "straight_to_swing")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "mixed"
    early = sorted(
        round(float(e.start_beat), 4) for e in quantized if e.start_beat < 4.0
    )
    late = sorted(
        round(float(e.start_beat), 4) for e in quantized if e.start_beat >= 4.0
    )
    assert early[:4] == [0.0, 0.5, 1.0, 1.5]
    assert late[:4] == [4.0, 4.5, 5.0, 5.5]
    xml = output.read_text(encoding="utf-8")
    words = _xml_words(xml)
    assert words.count("Swing") >= 1
    by_measure = _measure_words(xml)
    first = by_measure.get("1") or by_measure.get("X1") or []
    assert "Swing" not in first
    later = [w for num, labels in by_measure.items() if num not in {"1", "X1"} for w in labels]
    assert "Swing" in later

    source2, output2, _r2 = _convert(tmp_path, "swing_then_straight")
    quantized2, report2 = _quantize_fixture(source2)
    assert report2.summary["detected_interpretation"]["rhythmic_feel"] == "mixed"
    xml2 = output2.read_text(encoding="utf-8")
    words2 = _xml_words(xml2)
    assert "Swing" in words2
    assert "Straight" in words2
    late2 = [
        round(float(e.start_beat), 4)
        for e in quantized2
        if e.start_beat >= 4.0
    ]
    assert late2[:4] == [4.0, 4.5, 5.0, 5.5]


def test_sparse_and_ambiguous_input_stays_conservative(tmp_path):
    source, output, _report = _convert(tmp_path, "sparse_swing")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "straight"
    assert detected["maps_written_timing"] is False
    assert detected.get("user_summary") in (None, "")
    xml = output.read_text(encoding="utf-8")
    assert "Swing" not in _xml_words(xml)
    lonely = next(e for e in quantized if abs(float(e.start_beat) - (2.0 + 2.0 / 3.0)) < 0.08)
    assert abs(float(lonely.start_beat) - (2.0 + 2.0 / 3.0)) < 0.08

    _source_r, output_r, _ = _convert(tmp_path, "rubato_no_swing")
    xml_r = output_r.read_text(encoding="utf-8")
    assert "Swing" not in _xml_words(xml_r)


def test_swing_sixteenths_use_conventional_sixteenths(tmp_path):
    source, output, _report = _convert(tmp_path, "swing_sixteenths")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "swing_sixteenths"
    assert detected["user_summary"] == (
        "Swing 16ths detected — shown using conventional sixteenth-note notation."
    )
    by_start = sorted({round(float(e.start_beat), 4) for e in quantized})
    assert by_start[:4] == [0.0, 0.25, 0.5, 0.75]
    xml = output.read_text(encoding="utf-8")
    assert "Swing 16ths" in _xml_words(xml)
    assert xml.lower().count("<time-modification>") == 0
    score = _score_onsets(output.with_suffix(".score.mid"))
    assert score[1] == pytest.approx((2.0 / 3.0) * 0.25, abs=0.03)


def test_syncopated_offbeat_is_not_moved_to_a_downbeat():
    events = [
        _event(72, 0.0, 2.0 / 3.0, "d0"),
        _event(74, 2.0 / 3.0, 1.0, "sync"),
        _event(76, 1.0 + 2.0 / 3.0, 1.0 / 3.0, "o1"),
        _event(72, 2.0, 2.0 / 3.0, "d2"),
        _event(74, 2.0 + 2.0 / 3.0, 1.0 / 3.0, "o2"),
        _event(72, 3.0, 2.0 / 3.0, "d3"),
        _event(74, 3.0 + 2.0 / 3.0, 1.0 / 3.0, "o3"),
        _event(72, 4.0, 2.0 / 3.0, "d4"),
        _event(74, 4.0 + 2.0 / 3.0, 1.0 / 3.0, "o4"),
        _event(72, 5.0, 2.0 / 3.0, "d5"),
        _event(74, 5.0 + 2.0 / 3.0, 1.0 / 3.0, "o5"),
        _event(72, 6.0, 2.0 / 3.0, "d6"),
        _event(74, 6.0 + 2.0 / 3.0, 1.0 / 3.0, "o6"),
        _event(72, 7.0, 2.0 / 3.0, "d7"),
        _event(74, 7.0 + 2.0 / 3.0, 1.0 / 3.0, "o7"),
    ]
    out, _spans, summary = interpret_for_notation(events, METER_44, DEFAULT)
    assert summary["rhythmic_feel"] == "swing_eighths"
    by_id = _by_id(out)
    assert abs(by_id["sync"].start_beat - 0.5) < 0.04
    assert by_id["sync"].start_beat < 1.0
    assert abs(by_id["o1"].start_beat - 1.5) < 0.04


def test_compound_meter_has_no_swing_indication(tmp_path):
    _source, output, _report = _convert(tmp_path, "compound_6_8", meter="6/8")
    xml = output.read_text(encoding="utf-8")
    assert "Swing" not in _xml_words(xml)
    assert "<swing>" not in xml
