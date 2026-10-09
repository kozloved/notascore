"""Automatic feel inference with default settings (no genre or feel overrides)."""

from __future__ import annotations

import json
from collections import defaultdict
from xml.etree import ElementTree as ET

import pretty_midi
import pytest

from evaluation.swing_fixtures import SWING_FIXTURES
from mir.cmr_builder import notes_to_events
from mir.interpretation_profile import InterpretationProfile
from mir.midi_ingest import ingest_midi
from mir.models import MeterHypothesis
from mir.notation_settings import NotationSettings
from mir.performance_cli import convert
from mir.performance_score import quantize_notation
from mir.quantizer import QuantizerConfig
from mir.style_interpretation import interpret_for_notation
from mir.swing import (
    InterpretationSpan,
    _merge_windows,
    _ratio_from_fraction,
    _stabilize_windows,
    apply_playback_timing,
    feel_user_summary,
    infer_interpretation_spans,
    summarize_spans,
)
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
    kwargs = {"settings": DEFAULT}
    if meter is not None:
        kwargs["meter"] = meter
    report = convert(source, output, **kwargs)
    assert source.read_bytes() == original
    assert digest
    return source, output, report


def _detected(output):
    payload = json.loads(output.with_suffix(".notation_settings.json").read_text())
    return payload["detected_interpretation"]


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


def _span_feels(detected):
    return [
        (
            round(float(row["start_beat"]), 4),
            round(float(row["end_beat"]), 4),
            row["feel"],
            bool(row.get("maps_written_timing")),
        )
        for row in detected["spans"]
    ]


def test_even_sixteenths_do_not_invent_light_swing():
    assert _ratio_from_fraction(0.5) == 1.0
    events = [_event(60, i * 0.25, 0.22, f"e{i}") for i in range(32)]
    spans = infer_interpretation_spans(events, METER_44, InterpretationProfile())
    assert all(span.feel == "straight" for span in spans)
    assert all(not span.maps_written_timing or span.feel == "straight" for span in spans)


def test_stabilize_keeps_positive_contrast_and_absorbs_sparse_only():
    swing = {
        "start": 0.0,
        "end": 4.0,
        "feel": "swing_eighths",
        "ratio": 2.0,
        "subdivision_unit": 0.5,
        "confidence": 0.9,
        "evidence_count": 8,
        "origin": "inferred",
        "unmapped_streams": (),
    }
    convincing = {
        "start": 4.0,
        "end": 8.0,
        "feel": "straight",
        "ratio": None,
        "subdivision_unit": 0.5,
        "confidence": 0.82,
        "evidence_count": 8,
        "origin": "inferred",
        "unmapped_streams": (),
    }
    kept = _stabilize_windows(
        [swing, convincing, {**swing, "start": 8.0, "end": 12.0}]
    )
    assert kept[1]["feel"] == "straight"
    assert kept[1]["evidence_count"] == 8

    sparse = {
        "start": 4.0,
        "end": 8.0,
        "feel": "straight",
        "ratio": None,
        "subdivision_unit": 0.5,
        "confidence": 0.12,
        "evidence_count": 0,
        "origin": "inferred",
        "unmapped_streams": (),
    }
    absorbed = _stabilize_windows(
        [swing, sparse, {**swing, "start": 8.0, "end": 12.0}]
    )
    assert absorbed[1]["feel"] == "swing_eighths"
    assert absorbed[1]["evidence_count"] == 0
    merged = _merge_windows(absorbed)
    assert len(merged) == 1
    assert merged[0].feel == "swing_eighths"
    assert merged[0].confidence == pytest.approx(0.9)
    assert merged[0].evidence_count == 16


def test_merge_does_not_promote_weak_confidence_with_max():
    windows = [
        {
            "start": 0.0,
            "end": 4.0,
            "feel": "swing_eighths",
            "ratio": 2.0,
            "subdivision_unit": 0.5,
            "confidence": 0.9,
            "evidence_count": 8,
            "origin": "inferred",
            "unmapped_streams": (),
        },
        {
            "start": 4.0,
            "end": 8.0,
            "feel": "swing_eighths",
            "ratio": 2.0,
            "subdivision_unit": 0.5,
            "confidence": 0.4,
            "evidence_count": 2,
            "origin": "inferred",
            "unmapped_streams": (),
        },
    ]
    merged = _merge_windows(windows)
    assert len(merged) == 1
    assert merged[0].confidence == pytest.approx((0.9 * 8 + 0.4 * 2) / 10)
    assert merged[0].evidence_count == 10


def test_mixed_summary_does_not_call_sixteenths_swing_eighths():
    sixteenth = InterpretationSpan(
        start_beat=4.0,
        end_beat=8.0,
        feel="swing_sixteenths",
        subdivision_unit=0.25,
        ratio=2.0,
        confidence=0.9,
        evidence_count=8,
        origin="inferred",
        maps_written_timing=True,
    )
    straight = InterpretationSpan(
        start_beat=0.0,
        end_beat=4.0,
        feel="straight",
        subdivision_unit=0.5,
        ratio=None,
        confidence=0.8,
        evidence_count=8,
        origin="inferred",
        maps_written_timing=False,
    )
    mixed_16 = summarize_spans([straight, sixteenth])
    assert mixed_16["rhythmic_feel"] == "mixed"
    assert mixed_16["user_summary"] == (
        "Swing 16ths detected — shown using conventional sixteenth-note notation."
    )
    assert "eighth" not in mixed_16["user_summary"].lower()

    eighth = InterpretationSpan(
        start_beat=8.0,
        end_beat=12.0,
        feel="swing_eighths",
        subdivision_unit=0.5,
        ratio=2.0,
        confidence=0.9,
        evidence_count=8,
        origin="inferred",
        maps_written_timing=True,
    )
    mixed_both = summarize_spans([sixteenth, eighth])
    assert mixed_both["rhythmic_feel"] == "mixed"
    assert mixed_both["user_summary"] == (
        "Mixed subdivision feel detected — shown using conventional notation."
    )
    assert "eighth-note" not in mixed_both["user_summary"]
    assert feel_user_summary({**mixed_16, "rhythmic_feel": "mixed"}) == mixed_16["user_summary"]


def test_swing_straight_swing_keeps_the_intentional_straight_bar(tmp_path):
    source, output, _report = _convert(tmp_path, "swing_straight_swing")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "mixed"
    feels = [row["feel"] for row in detected["spans"]]
    assert "straight" in feels
    assert "swing_eighths" in feels
    early = sorted(round(float(e.start_beat), 4) for e in quantized if e.start_beat < 4.0)
    middle = sorted(
        round(float(e.start_beat), 4) for e in quantized if 4.0 <= e.start_beat < 8.0
    )
    late = sorted(round(float(e.start_beat), 4) for e in quantized if e.start_beat >= 8.0)
    assert early[:4] == [0.0, 0.5, 1.0, 1.5]
    assert middle[:4] == [4.0, 4.5, 5.0, 5.5]
    assert late[:4] == [8.0, 8.5, 9.0, 9.5]
    xml = output.read_text(encoding="utf-8")
    words = _xml_words(xml)
    assert "Swing" in words
    assert "Straight" in words
    by_measure = _measure_words(xml)
    first = by_measure.get("1") or by_measure.get("X1") or []
    assert "Swing" in first
    assert any("Straight" in labels for labels in by_measure.values())
    score = pretty_midi.PrettyMIDI(str(output.with_suffix(".score.mid")))
    onsets = sorted(n.start for inst in score.instruments for n in inst.notes)
    assert onsets[1] == pytest.approx(1.0 / 3.0, abs=0.04)
    mid = [t for t in onsets if 2.0 <= t < 4.0]
    assert mid[1] == pytest.approx(2.25, abs=0.05)
    late_onsets = [t for t in onsets if t >= 4.0]
    assert late_onsets[1] == pytest.approx(4.0 + 1.0 / 3.0, abs=0.05)


def test_straight_swing_straight_keeps_the_clear_swing_passage(tmp_path):
    source, output, _report = _convert(tmp_path, "straight_swing_straight")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "mixed"
    feels = [row["feel"] for row in detected["spans"]]
    assert feels.count("swing_eighths") >= 1
    assert feels[0] == "straight" or detected["spans"][0]["start_beat"] < 4.0
    early = sorted(round(float(e.start_beat), 4) for e in quantized if e.start_beat < 4.0)
    middle = sorted(
        round(float(e.start_beat), 4) for e in quantized if 4.0 <= e.start_beat < 8.0
    )
    late = sorted(round(float(e.start_beat), 4) for e in quantized if e.start_beat >= 8.0)
    assert early[:4] == [0.0, 0.5, 1.0, 1.5]
    assert middle[:4] == [4.0, 4.5, 5.0, 5.5]
    assert late[:4] == [8.0, 8.5, 9.0, 9.5]
    xml = output.read_text(encoding="utf-8")
    words = _xml_words(xml)
    assert "Swing" in words
    assert "Straight" in words
    by_measure = _measure_words(xml)
    first = by_measure.get("1") or by_measure.get("X1") or []
    assert "Swing" not in first
    score = pretty_midi.PrettyMIDI(str(output.with_suffix(".score.mid")))
    onsets = sorted(n.start for inst in score.instruments for n in inst.notes)
    assert onsets[1] == pytest.approx(0.25, abs=0.05)
    swung = [t for t in onsets if 2.0 <= t < 4.0]
    assert swung[1] == pytest.approx(2.0 + 1.0 / 3.0, abs=0.05)
    late_onsets = [t for t in onsets if t >= 4.0]
    assert late_onsets[1] == pytest.approx(4.25, abs=0.05)


def test_sparse_ambiguous_bridge_follows_surrounding_swing(tmp_path):
    source, output, _report = _convert(tmp_path, "sparse_bridge")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    middle_spans = [
        row
        for row in detected["spans"]
        if row["start_beat"] < 8.0 - 1e-6 and row["end_beat"] > 4.0 + 1e-6
    ]
    assert middle_spans
    assert all(row["feel"] == "swing_eighths" for row in middle_spans)
    xml = output.read_text(encoding="utf-8")
    words = _xml_words(xml)
    assert "Swing" in words
    assert "Straight" not in words
    downbeats = sorted(
        round(float(e.start_beat), 4) for e in quantized if e.pitch == 60
    )
    assert downbeats == [4.0, 5.0, 6.0, 7.0]


def test_short_convincing_swing_is_not_absorbed_by_neighbours(tmp_path):
    source, output, _report = _convert(tmp_path, "short_convincing_swing")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "mixed"
    swing_spans = [row for row in detected["spans"] if row["feel"] in {"swing_eighths", "shuffle"}]
    assert swing_spans
    assert any(row["start_beat"] <= 8.0 + 1e-6 and row["end_beat"] >= 12.0 - 1e-6 for row in swing_spans)
    middle = sorted(
        round(float(e.start_beat), 4) for e in quantized if 8.0 <= e.start_beat < 12.0
    )
    assert middle[:4] == [8.0, 8.5, 9.0, 9.5]
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)
    score = pretty_midi.PrettyMIDI(str(output.with_suffix(".score.mid")))
    onsets = sorted(n.start for inst in score.instruments for n in inst.notes)
    swung = [t for t in onsets if 4.0 <= t < 6.0]
    assert swung[1] == pytest.approx(4.0 + 1.0 / 3.0, abs=0.05)


def test_straight_then_swing_sixteenths_summary_does_not_claim_eighths(tmp_path):
    source, output, _report = _convert(tmp_path, "straight_then_swing_sixteenths")
    quantized, report = _quantize_fixture(source)
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "mixed"
    assert "eighth-note" not in (detected.get("user_summary") or "")
    swing_feels = {
        row["feel"]
        for row in detected["spans"]
        if row["feel"] in {"swing_eighths", "swing_sixteenths", "shuffle"}
        and row.get("maps_written_timing")
    }
    assert "swing_sixteenths" in swing_feels
    late = sorted(round(float(e.start_beat), 4) for e in quantized if e.start_beat >= 4.0)
    assert late[:4] == [4.0, 4.25, 4.5, 4.75]
    xml = output.read_text(encoding="utf-8")
    assert "Swing 16ths" in _xml_words(xml)
    assert "<swing>" in xml


def test_convert_without_forced_meter_still_infers_swing(tmp_path):
    source, output, _report = _convert(tmp_path, "swing_2_to_1", meter=None)
    detected = _detected(output)
    assert detected["rhythmic_feel"] == "swing_eighths"
    assert detected["maps_written_timing"] is True
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)
    score = pretty_midi.PrettyMIDI(str(output.with_suffix(".score.mid")))
    onsets = sorted(n.start for inst in score.instruments for n in inst.notes)
    assert onsets[1] == pytest.approx(1.0 / 3.0, abs=0.03)


def test_save_reload_regeneration_keeps_automatic_feel(tmp_path):
    from mir.notation_regen import recompute_notation
    from tests.test_shared_engraving import _context_for

    source, output, _report = _convert(tmp_path, "swing_2_to_1", meter=None)
    original = source.read_bytes()
    ingested = ingest_midi(source)
    first = recompute_notation(
        midi_bytes=original,
        settings=DEFAULT,
        performance=ingested.performance,
        context=_context_for(ingested, selected_meter=ingested.time_sig_hint or "4/4"),
    )
    detected = (first.summary or {}).get("detected_interpretation") or {}
    assert detected.get("rhythmic_feel") == "swing_eighths"
    starts = sorted(round(float(n["start"]), 4) for n in first.editor_model["notes"])
    assert starts[:6] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    assert all(n.get("stream_key") for n in first.editor_model["notes"])
    assert all(n.get("performed_start_beat") is not None for n in first.editor_model["notes"])
    reloaded = recompute_notation(
        midi_bytes=original,
        settings=DEFAULT,
        performance=ingested.performance,
        context=first.context,
    )
    assert source.read_bytes() == original
    again = (reloaded.summary or {}).get("detected_interpretation") or {}
    assert again.get("rhythmic_feel") == "swing_eighths"
    assert sorted(round(float(n["start"]), 4) for n in reloaded.editor_model["notes"])[:6] == starts[:6]
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)
    assert "<swing>" in xml
