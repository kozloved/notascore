"""Cross-language swing playback contract: onsets and releases."""

from __future__ import annotations

import json
from pathlib import Path

import pretty_midi
import pytest

from evaluation.swing_fixtures import SWING_FIXTURES
from mir.notation_settings import NotationSettings
from mir.performance_cli import convert
from mir.notation_regen import editor_model_from_events
from mir.swing import allocate_sounding_lanes, apply_playback_timing, stream_key
from mir.types import Hand, MusicalEvent
from notation_engine.playback import playback_duration_beats, playback_score
from score_edits import dumps_edits, events_from_editor_model, loads_edits, validate_notes

PARITY = Path(__file__).resolve().parents[1] / "evaluation" / "swing_playback_parity.json"
BEAT_TOL = 1e-9
PPQ = json.loads(PARITY.read_text(encoding="utf-8"))["tick_tolerance_ppq"]


def _ticks(beat: float) -> int:
    return int(round(float(beat) * PPQ))


def _hand(note):
    key = str(note.get("stream_key") or "")
    if "|left|" in key:
        return Hand.LEFT
    if note.get("track") == 1:
        return Hand.LEFT
    return Hand.RIGHT


def _event_from_case(note):
    track = str(note.get("stream_key") or "|").split("|")[0]
    return MusicalEvent(
        int(note.get("pitch") or 60),
        float(note["start"]),
        float(note["duration"]),
        note_id=str(note["id"]),
        hand=_hand(note),
        voice=int(note.get("voice") or 0),
        source_track_id=track,
        velocity=80,
        performed_start_beat=note.get("performed_start_beat"),
        performed_duration_beats=note.get("performed_duration_beats"),
        score_timing_locked=bool(note.get("score_timing_locked") or False),
        stream_key=note.get("stream_key"),
        articulation=note.get("articulation") or None,
        articulation_source=str(note.get("articulation_source") or ""),
    )


def _load_cases():
    return json.loads(PARITY.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["name"])
def test_parity_case_onsets_and_releases(case):
    events = [_event_from_case(note) for note in case["notes"]]
    sounded = apply_playback_timing(events, case["spans"])
    by_id = {e.note_id: e for e in sounded}
    assert case.get("expected"), case["name"]
    for row in case["expected"]:
        got = by_id[row["id"]]
        assert got.start_beat == pytest.approx(row["start"], abs=BEAT_TOL)
        assert got.start_beat + got.duration_beats == pytest.approx(
            row["start"] + row["duration"], abs=BEAT_TOL
        )
        assert got.duration_beats == pytest.approx(row["duration"], abs=BEAT_TOL)
        assert _ticks(got.start_beat) == _ticks(row["start"])
        assert _ticks(got.start_beat + got.duration_beats) == _ticks(row["start"] + row["duration"])
        assert got.pitch == int(next(n["pitch"] for n in case["notes"] if n["id"] == row["id"]))
        assert got.note_id == row["id"]
        if "sounding_duration" in row:
            assert playback_duration_beats(got) == pytest.approx(
                row["sounding_duration"], abs=BEAT_TOL
            )


def test_http_note_model_keeps_swing_provenance():
    from main import ScoreNoteIn

    note = ScoreNoteIn(
        id="n-0000",
        pitch=74,
        start=0.5,
        duration=3.5,
        performed_start_beat=2.0 / 3.0,
        performed_duration_beats=10.0 / 3.0,
        stream_key="|right|0",
        score_timing_locked=True,
    )
    dumped = note.model_dump()
    assert dumped["stream_key"] == "|right|0"
    assert dumped["performed_start_beat"] == pytest.approx(2.0 / 3.0)
    assert dumped["score_timing_locked"] is True


def test_editor_roundtrip_keeps_stream_and_performed_provenance(tmp_path):
    case = next(c for c in _load_cases() if c["name"] == "swung_rh_straight_lh")
    events = [_event_from_case(note) for note in case["notes"]]
    sounding = apply_playback_timing(events, case["spans"])
    model_notes = []
    for event, src in zip(events, case["notes"]):
        model_notes.append(
            {
                "id": f"n-{src['id']}" if not str(src["id"]).startswith("n-") else src["id"],
                "source_note_id": event.note_id,
                "pitch": event.pitch,
                "start": event.start_beat,
                "duration": event.duration_beats,
                "velocity": 80,
                "track": 1 if event.hand == Hand.LEFT else 0,
                "voice": event.voice,
                "performed_start_beat": event.performed_start_beat,
                "performed_duration_beats": event.performed_duration_beats,
                "stream_key": stream_key(event),
            }
        )
    # validate_notes requires n-xxxx ids
    for index, row in enumerate(model_notes):
        row["id"] = f"n-{index:04d}"
    saved = validate_notes(model_notes)
    assert all(row.get("stream_key") for row in saved)
    assert all(row.get("performed_start_beat") is not None for row in saved)
    saved[0]["pitch"] = 73
    reloaded = loads_edits(dumps_edits({"notes": saved, "tempo_bpm": 120, "time_signature": "4/4"}))
    assert reloaded["notes"][0]["stream_key"] == saved[0]["stream_key"]
    assert reloaded["notes"][0]["performed_start_beat"] == pytest.approx(saved[0]["performed_start_beat"])
    restored = events_from_editor_model(reloaded)
    assert stream_key(restored[0]) == saved[0]["stream_key"]
    assert restored[0].performed_start_beat == pytest.approx(saved[0]["performed_start_beat"])
    again = apply_playback_timing(restored, case["spans"])
    original = {e.note_id: e for e in sounding}
    for event in again:
        if event.note_id == events[0].note_id:
            assert event.pitch == 73
            assert event.start_beat == pytest.approx(original[event.note_id].start_beat)
            continue
        match = original[event.note_id]
        assert event.start_beat == pytest.approx(match.start_beat)
        assert event.duration_beats == pytest.approx(match.duration_beats)


def test_long_swung_offbeat_writes_half_and_plays_two_thirds(tmp_path):
    source = tmp_path / "long.mid"
    SWING_FIXTURES["long_swung_offbeat"](source)
    original = source.read_bytes()
    output = tmp_path / "long.musicxml"
    convert(source, output, settings=NotationSettings())
    assert source.read_bytes() == original
    from mir.cmr_builder import notes_to_events
    from mir.midi_ingest import ingest_midi
    from mir.models import MeterHypothesis
    from mir.performance_score import quantize_notation
    from mir.quantizer import QuantizerConfig

    ingested = ingest_midi(source)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    quantized, _dec, report = quantize_notation(
        events,
        MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0),
        config=QuantizerConfig(),
        settings=NotationSettings(),
    )
    detected = report.summary["detected_interpretation"]
    assert detected["rhythmic_feel"] == "swing_eighths"
    long_note = next(e for e in quantized if e.pitch == 74)
    assert long_note.start_beat == pytest.approx(0.5, abs=0.04)
    assert long_note.start_beat + long_note.duration_beats == pytest.approx(4.0, abs=0.08)
    assert long_note.note_id
    held = next(e for e in quantized if e.pitch == 67)
    assert held.start_beat == pytest.approx(4.5, abs=0.04)
    from mir.swing import apply_playback_timing, spans_from_payload

    spans = spans_from_payload(report.summary.get("interpretation_spans") or detected.get("spans") or ())
    sounded = apply_playback_timing(quantized, spans)
    long_sound = next(e for e in sounded if e.pitch == 74)
    assert long_sound.start_beat == pytest.approx(2.0 / 3.0, abs=0.04)
    assert long_sound.start_beat + long_sound.duration_beats == pytest.approx(4.0, abs=0.08)
    straight_sound = next(e for e in sounded if e.pitch == 67)
    assert straight_sound.start_beat == pytest.approx(4.5, abs=0.04)
    midi = pretty_midi.PrettyMIDI(str(output.with_suffix(".score.mid")))
    long_midi = next(n for inst in midi.instruments for n in inst.notes if n.pitch == 74)
    assert long_midi.start == pytest.approx((2.0 / 3.0) * 0.5, abs=0.03)
    model = editor_model_from_events(quantized, tempo_bpm=120, time_signature="4/4")
    assert all(row.get("stream_key") for row in model["notes"])
    assert all(row.get("performed_start_beat") is not None for row in model["notes"])
    reloaded = loads_edits(dumps_edits(model))
    long_row = next(row for row in reloaded["notes"] if row["pitch"] == 74)
    assert long_row["start"] == pytest.approx(0.5, abs=0.04)
    assert long_row["performed_start_beat"] == pytest.approx(2.0 / 3.0, abs=0.04)
    restored = events_from_editor_model(reloaded)
    again = apply_playback_timing(restored, spans)
    long_again = next(e for e in again if e.pitch == 74)
    assert long_again.start_beat == pytest.approx(2.0 / 3.0, abs=0.04)
    assert long_again.note_id == long_note.note_id


def test_sounding_lanes_keep_overlapping_unisons():
    events = [
        MusicalEvent(59, 0.0, 5.0, note_id="held", voice=0),
        MusicalEvent(59, 4.9, 0.5, note_id="later", voice=0),
    ]
    lanes = allocate_sounding_lanes(events)
    assert lanes[0] != lanes[1]
    score = playback_score(events, "4/4", [(0, 120)], swing_spans=[])
    path = "/tmp/lane_unison.mid"
    score.write("midi", fp=path)
    midi = pretty_midi.PrettyMIDI(path)
    notes = [n for inst in midi.instruments for n in inst.notes if n.pitch == 59]
    assert len(notes) == 2
