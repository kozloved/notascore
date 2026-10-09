"""Decoded score MIDI must swing written eighths once."""

from __future__ import annotations

import pretty_midi
import pytest

from evaluation.swing_fixtures import SWING_FIXTURES
from mir.notation_settings import NotationSettings
from mir.performance_cli import convert
from mir.swing import apply_playback_timing, map_beat_through_swing
from mir.types import Hand, MusicalEvent
from notation_engine.playback import playback_score


def _event(pitch, start, duration, ident, **extra):
    return MusicalEvent(
        pitch,
        start,
        duration,
        note_id=ident,
        hand=Hand.RIGHT,
        velocity=80,
        start_time_sec=float(start) * 0.5,
        end_time_sec=(float(start) + float(duration)) * 0.5,
        **extra,
    )


def test_playback_mapping_at_120_bpm_matches_2_to_1_slots():
    events = [
        _event(72, 0.0, 0.5, "d0"),
        _event(74, 0.5, 0.5, "o0"),
        _event(72, 1.0, 0.5, "d1"),
        _event(74, 1.5, 0.5, "o1"),
    ]
    spans = [
        {
            "start_beat": 0.0,
            "end_beat": 4.0,
            "feel": "swing_eighths",
            "subdivision_unit": 0.5,
            "ratio": 2.0,
            "confidence": 1.0,
            "evidence_count": 4,
            "origin": "user_override",
            "maps_written_timing": True,
        }
    ]
    sounded = apply_playback_timing(events, spans)
    assert abs(sounded[1].start_beat - (2.0 / 3.0)) < 1e-9
    assert abs(map_beat_through_swing(0.5, pair_length=1.0, ratio=2.0, reverse=True) - 2 / 3) < 1e-9
    score = playback_score(events, "4/4", [(0, 120)], swing_spans=spans)
    midi_path = "/tmp/swing_playback_check.mid"
    score.write("midi", fp=midi_path)
    midi = pretty_midi.PrettyMIDI(midi_path)
    onsets = sorted(note.start for inst in midi.instruments for note in inst.notes)
    assert onsets[0] == pytest.approx(0.0, abs=0.02)
    assert onsets[1] == pytest.approx(1.0 / 3.0, abs=0.02)
    assert onsets[2] == pytest.approx(0.5, abs=0.02)


def test_exported_score_midi_swings_and_raw_midi_does_not(tmp_path):
    source = tmp_path / "swing.mid"
    digest = SWING_FIXTURES["swing_2_to_1"](source)
    original = source.read_bytes()
    output = tmp_path / "swing.musicxml"
    convert(
        source,
        output,
        settings=NotationSettings(),
    )
    assert source.read_bytes() == original
    assert digest
    raw = pretty_midi.PrettyMIDI(str(source))
    score = pretty_midi.PrettyMIDI(str(output.with_suffix(".score.mid")))
    raw_onsets = sorted(n.start for inst in raw.instruments for n in inst.notes)
    score_onsets = sorted(n.start for inst in score.instruments for n in inst.notes)
    assert raw_onsets[1] == pytest.approx(1.0 / 3.0, abs=0.03)
    assert score_onsets[0] == pytest.approx(0.0, abs=0.02)
    assert score_onsets[1] == pytest.approx(1.0 / 3.0, abs=0.03)
    assert score_onsets[2] == pytest.approx(0.5, abs=0.03)
    # MusicXML stays even eighths.
    xml = output.read_text(encoding="utf-8")
    assert "<swing>" in xml
    from notation_engine.swing_export import assert_swing_metadata_placement

    nodes = assert_swing_metadata_placement(xml)
    assert nodes
    assert nodes[0]["swing_type"] == "eighth"


def test_long_sustain_is_not_reverse_mapped_into_a_later_unison():
    held = _event(59, 3.75, 5.0, "held")
    later = _event(59, 8.75, 0.25, "later")
    spans = [
        {
            "start_beat": 0.0,
            "end_beat": 16.0,
            "feel": "swing_sixteenths",
            "subdivision_unit": 0.25,
            "ratio": 1.15,
            "confidence": 0.84,
            "evidence_count": 12,
            "origin": "inferred",
            "maps_written_timing": True,
        }
    ]
    sounded = apply_playback_timing([held, later], spans)
    assert sounded[0].start_beat == pytest.approx(3.75)
    assert sounded[0].start_beat + sounded[0].duration_beats <= sounded[1].start_beat + 1e-9


def test_straight_exception_inside_swing_is_not_swung_on_playback():
    events = [
        _event(72, 0.0, 0.5, "d0", performed_start_beat=0.0, performed_duration_beats=2.0 / 3.0),
        _event(74, 0.5, 0.5, "straight", performed_start_beat=0.5, performed_duration_beats=0.5),
        _event(72, 1.0, 0.5, "d1", performed_start_beat=1.0, performed_duration_beats=2.0 / 3.0),
        _event(74, 1.5, 0.5, "o1", performed_start_beat=1.0 + 2.0 / 3.0, performed_duration_beats=1.0 / 3.0),
    ]
    spans = [
        {
            "start_beat": 0.0,
            "end_beat": 4.0,
            "feel": "swing_eighths",
            "subdivision_unit": 0.5,
            "ratio": 2.0,
            "confidence": 1.0,
            "evidence_count": 4,
            "origin": "inferred",
            "maps_written_timing": True,
        }
    ]
    sounded = apply_playback_timing(events, spans)
    by_id = {e.note_id: e for e in sounded}
    assert by_id["straight"].start_beat == pytest.approx(0.5)
    assert by_id["o1"].start_beat == pytest.approx(1.0 + 2.0 / 3.0)
    assert by_id["d0"].start_beat == pytest.approx(0.0)


def test_straight_score_midi_places_offbeat_at_250ms(tmp_path):
    source = tmp_path / "straight.mid"
    SWING_FIXTURES["straight_eighths_jitter"](source)
    output = tmp_path / "straight.musicxml"
    convert(
        source,
        output,
        settings=NotationSettings(),
    )
    score = pretty_midi.PrettyMIDI(str(output.with_suffix(".score.mid")))
    onsets = sorted(n.start for inst in score.instruments for n in inst.notes)
    assert onsets[1] == pytest.approx(0.25, abs=0.04)
