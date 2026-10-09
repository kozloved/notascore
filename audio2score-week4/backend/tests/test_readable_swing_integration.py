"""Readable v3 + automatic swing interactions. Synthetic fixtures, not performances."""

from __future__ import annotations

import io
import json
from xml.etree import ElementTree as ET

import pretty_midi
import pytest

from evaluation.swing_fixtures import SWING_FIXTURES
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.models import MeterHypothesis
from mir.notation_settings import ALGORITHM_VERSION_READABLE, NotationSettings
from mir.notation_regen import editor_model_from_events
from mir.performance_cli import convert
from mir.performance_score import quantize_notation
from mir.quantizer import QuantizerConfig
from mir.swing import apply_playback_timing
from mir.types import Hand, MusicalEvent
from notation_engine.playback import playback_duration_beats
from score_edits import ALLOWED_ARTICULATIONS, validate_notes

METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
DEFAULT = NotationSettings()
LEGACY = NotationSettings.legacy_readable()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _xml_words(xml: str) -> list[str]:
    root = ET.fromstring(xml)
    return [
        (elem.text or "").strip()
        for elem in root.iter()
        if _local(elem.tag) == "words" and (elem.text or "").strip()
    ]


def _convert(tmp_path, name, settings=None):
    source = tmp_path / f"{name}.mid"
    SWING_FIXTURES[name](source)
    original = source.read_bytes()
    output = tmp_path / f"{name}.musicxml"
    convert(source, output, settings=settings or DEFAULT, meter="4/4")
    assert source.read_bytes() == original
    return source, output, original


def _onsets(path):
    midi = pretty_midi.PrettyMIDI(str(path) if not isinstance(path, (bytes, bytearray)) else io.BytesIO(path))
    return sorted(note.start for inst in midi.instruments for note in inst.notes)


def _quantize(source, settings):
    ingested = ingest_midi(source)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    return quantize_notation(events, METER, config=QuantizerConfig(), settings=settings)


def test_new_scores_default_to_v3_with_auto_feel():
    assert DEFAULT.algorithm_version == ALGORITHM_VERSION_READABLE
    assert DEFAULT.algorithm_version == "performance-score-3"
    assert DEFAULT.interpretation.value == "readable"
    assert DEFAULT.interpretation_profile.rhythmic_feel.value == "auto"
    assert DEFAULT.interpretation_profile.source_style.value == "auto"


def test_swing_plus_inferred_staccato_keeps_conventional_notation_and_swung_playback(tmp_path):
    """A. Conventional eighths + Swing; staccato shortens sounded length after mapping."""
    source, output, original = _convert(tmp_path, "swing_2_to_1")
    assert source.read_bytes() == original
    settings = json.loads(output.with_suffix(".notation_settings.json").read_text())
    assert settings["algorithm_version"] == "performance-score-3"
    detected = settings["detected_interpretation"]
    assert detected["rhythmic_feel"] == "swing_eighths"
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)
    quantized, _dec, report = _quantize(source, DEFAULT)
    starts = sorted({round(float(e.start_beat), 4) for e in quantized})
    assert starts[:4] == [0.0, 0.5, 1.0, 1.5]
    score = _onsets(output.with_suffix(".score.mid"))
    assert score[1] == pytest.approx(1.0 / 3.0, abs=0.05)

    offbeat = next(e for e in quantized if abs(float(e.start_beat) - 0.5) < 1e-6)
    marked = MusicalEvent(
        offbeat.pitch,
        offbeat.start_beat,
        offbeat.duration_beats,
        note_id="stacc",
        hand=offbeat.hand,
        voice=offbeat.voice,
        articulation="staccato",
        articulation_source="inferred",
        performed_start_beat=offbeat.performed_start_beat,
        performed_duration_beats=offbeat.performed_duration_beats,
        stream_key=offbeat.stream_key,
    )
    spans = report.summary["interpretation_spans"]
    sounded = apply_playback_timing([marked], spans)[0]
    assert sounded.start_beat == pytest.approx(2.0 / 3.0, abs=0.04)
    assert playback_duration_beats(sounded) == pytest.approx(sounded.duration_beats * 0.5, abs=1e-6)
    assert playback_duration_beats(sounded) < sounded.duration_beats


def test_long_tied_offbeat_with_moving_inner_voice_keeps_attacks(tmp_path):
    """B. Long swung offbeat plus a held inner voice: attacks and releases survive v3."""
    source, output, original = _convert(tmp_path, "long_swung_offbeat")
    ingested = ingest_midi(source)
    quantized, _dec, report = _quantize(source, DEFAULT)
    assert source.read_bytes() == original
    assert len(quantized) == len(ingested.notes)
    held = [e for e in quantized if e.pitch == 67]
    assert held
    assert max(float(e.duration_beats) for e in held) >= 2.5
    long_off = next(
        e for e in quantized if e.pitch == 74 and abs(float(e.start_beat) - 0.5) < 1e-6
    )
    assert float(long_off.duration_beats) >= 3.0
    inner_moving = [e for e in quantized if e.pitch in {60, 62, 72, 76}]
    assert inner_moving
    assert all(e.duration_beats <= 1.0 + 1e-9 for e in inner_moving)
    assert any(e.musical_voice != held[0].musical_voice for e in quantized if e.pitch == 76)
    xml = output.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(xml)
    assert xml.lower().count("<tie ") + xml.lower().count("<tied ") >= 1
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "swing_eighths"


def test_straight_syncopation_under_v3_has_no_false_swing(tmp_path):
    """C. Offbeats stay offbeats; no Swing label."""
    source, output, original = _convert(tmp_path, "straight_syncopation")
    quantized, _dec, report = _quantize(source, DEFAULT)
    assert source.read_bytes() == original
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "straight"
    assert "Swing" not in _xml_words(output.read_text(encoding="utf-8"))
    starts = sorted({round(float(e.start_beat), 4) for e in quantized})
    assert 0.5 in starts and 1.5 in starts
    score = _onsets(output.with_suffix(".score.mid"))
    assert score[1] == pytest.approx(0.25, abs=0.05)


def test_triplets_and_even_exceptions_inside_swing_survive_v3(tmp_path):
    """D. Tuplets and a printed even exception stay in score and export MIDI."""
    _source, trip_out, _orig = _convert(tmp_path, "triplets_inside_swing")
    trip_xml = trip_out.read_text(encoding="utf-8")
    assert "Swing" in _xml_words(trip_xml)
    assert trip_xml.lower().count("<time-modification>") >= 3

    source, even_out, original = _convert(tmp_path, "swing_with_even_exception")
    xml = even_out.read_text(encoding="utf-8")
    words = _xml_words(xml)
    assert "Swing" in words
    assert "even" in words
    score = _onsets(even_out.with_suffix(".score.mid"))
    assert score[1] == pytest.approx(1.0 / 3.0, abs=0.05)
    even = next(t for t in score if 0.65 < t < 0.85)
    assert even == pytest.approx(0.75, abs=0.04)
    assert source.read_bytes() == original


def test_raw_midi_stays_byte_identical_across_v3_swing_and_legacy(tmp_path):
    """H. Source MIDI is immutable through default v3, legacy v1, and Literal."""
    source, output, original = _convert(tmp_path, "swing_2_to_1")
    assert source.read_bytes() == original
    convert(source, tmp_path / "legacy.musicxml", settings=LEGACY, meter="4/4")
    assert source.read_bytes() == original
    convert(
        source,
        tmp_path / "literal.musicxml",
        settings=NotationSettings.literal(),
        meter="4/4",
    )
    assert source.read_bytes() == original
    assert output.with_suffix(".score.mid").is_file()


def test_editor_model_omits_internal_ornament_marks():
    """Internal Readable ornament tags are not editor articulations."""
    events = [
        MusicalEvent(
            72,
            0.0,
            0.25,
            note_id="n-orn",
            hand=Hand.RIGHT,
            voice=1,
            articulation="ornament",
            articulation_source="inferred",
        ),
        MusicalEvent(
            60,
            0.5,
            0.5,
            note_id="n-stac",
            hand=Hand.RIGHT,
            voice=1,
            articulation="staccato",
            articulation_source="inferred",
        ),
    ]
    model = editor_model_from_events(events, tempo_bpm=120, time_signature="4/4")
    validate_notes(model["notes"])
    by_id = {n["id"]: n for n in model["notes"]}
    assert by_id["n-orn"].get("articulation") is None
    assert by_id["n-orn"].get("articulation_source") is None
    assert by_id["n-stac"]["articulation"] == "staccato"
    assert by_id["n-stac"]["articulation_source"] == "inferred"
    assert all(
        n.get("articulation") in (None, *ALLOWED_ARTICULATIONS) for n in model["notes"]
    )
