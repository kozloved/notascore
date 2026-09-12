"""Pitch-only editor saves must keep performance identity, voice, and seconds."""

from __future__ import annotations

from io import BytesIO

import pretty_midi
import pytest

from mir.performance import PerformanceSnapshot, SourceNote
from mir.types import TempoMap, TempoPoint
from score_edits import (
    PROVENANCE_MUSICXML_DEGRADED,
    PROVENANCE_PERFORMANCE,
    build_musicxml_and_midi,
    extract_from_musicxml,
    extract_from_performance,
)
from timing.tempo_map import MusicalTimeMap


def _snapshot(notes, *, backend="midi"):
    return PerformanceSnapshot(
        source_backend=backend,
        notes=tuple(
            SourceNote(
                note_id=item[0],
                pitch=item[1],
                start_sec=item[2],
                end_sec=item[3],
                velocity=item[4],
                confidence=1.0,
                track_id=item[5] if len(item) > 5 else "track:0",
                program=0,
                hand_hint=item[6] if len(item) > 6 else "right",
            )
            for item in notes
        ),
    )


def _midi_notes(midi_bytes: bytes) -> list[tuple[int, float, float]]:
    midi = pretty_midi.PrettyMIDI(BytesIO(midi_bytes))
    rows = []
    for inst in midi.instruments:
        for note in inst.notes:
            rows.append((int(note.pitch), float(note.start), float(note.end)))
    return sorted(rows)


def _tick_tolerance(bpm: float = 120.0, ticks_per_beat: int = 220) -> float:
    return (60.0 / bpm) / ticks_per_beat + 1e-6


def test_musicxml_migration_does_not_fabricate_source_ids(tmp_path):
    from music21 import meter, note, stream, tempo

    part = stream.Part()
    part.insert(0, tempo.MetronomeMark(number=100))
    part.insert(0, meter.TimeSignature("4/4"))
    event = note.Note("C4")
    event.quarterLength = 1.0
    part.insert(0, event)
    score = stream.Score()
    score.insert(0, part)
    path = tmp_path / "old.musicxml"
    score.write("musicxml", fp=str(path))
    model = extract_from_musicxml(path.read_text(encoding="utf-8"))
    assert model["provenance"] == PROVENANCE_MUSICXML_DEGRADED
    assert all(item["source_note_id"] is None for item in model["notes"])


def test_performance_extract_keeps_ids_voices_and_exact_beats():
    time_map = MusicalTimeMap.from_bpm(120.0, duration_sec=8.0)
    snapshot = _snapshot(
        [
            ("original-a", 60, 0.0, 0.5, 80, "track:0", "right"),
            ("original-b", 64, 0.0, 0.5, 70, "track:0", "right"),
            ("original-c", 60, 0.25, 0.5, 75, "track:0", "right"),
        ]
    )
    model = extract_from_performance(snapshot, time_map, time_signature="4/4")
    assert model["provenance"] == PROVENANCE_PERFORMANCE
    by_id = {item["source_note_id"]: item for item in model["notes"]}
    assert set(by_id) == {"original-a", "original-b", "original-c"}
    assert by_id["original-a"]["start"] == pytest.approx(0.0)
    assert by_id["original-a"]["duration"] == pytest.approx(1.0)
    assert by_id["original-c"]["start"] == pytest.approx(0.5)
    assert by_id["original-a"]["voice"] != by_id["original-c"]["voice"]


def test_pitch_only_edit_keeps_seconds_through_midi():
    tempo_map = TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=80.0),
            TempoPoint(time_sec=0.4, beat=0.5, bpm=70.0),
            TempoPoint(time_sec=1.2, beat=1.5, bpm=95.0),
            TempoPoint(time_sec=2.0, beat=2.5, bpm=60.0),
            TempoPoint(time_sec=4.0, beat=4.0, bpm=80.0),
        ]
    )
    time_map = MusicalTimeMap.from_tempo_map(tempo_map, duration_sec=6.0)
    snapshot = _snapshot(
        [
            ("src-c", 60, 0.0, 0.4, 80),
            ("src-e", 64, 0.4, 1.2, 82),
            ("src-g", 67, 1.2, 2.0, 77),
            ("src-repeat", 60, 2.0, 2.15, 90),
        ]
    )
    printed = [{"beat": 0.0, "bpm": 80, "mark": "metronome", "reason": "opening_tempo"}]
    model = extract_from_performance(
        snapshot, time_map, printed_marks=printed, time_signature="4/4"
    )
    assert len(model["tempo_curve"]) >= 3
    assert len(model["printed_tempo_marks"]) == 1
    before = {
        item["source_note_id"]: (
            item["start"],
            item["duration"],
            item["voice"],
            item["start_sec"],
            item["end_sec"],
        )
        for item in model["notes"]
    }
    target = next(item for item in model["notes"] if item["source_note_id"] == "src-e")
    target["pitch"] = 65
    xml_text, midi_bytes = build_musicxml_and_midi(model)
    rebuilt = extract_from_musicxml(xml_text)
    by_source = {item["source_note_id"]: item for item in rebuilt["notes"]}
    assert by_source["src-e"]["pitch"] == 65
    assert by_source["src-c"]["pitch"] == 60
    assert by_source["src-e"]["source_note_id"] == "src-e"
    assert by_source["src-e"]["voice"] == next(
        item["voice"] for item in model["notes"] if item["source_note_id"] == "src-e"
    )
    midi = _midi_notes(midi_bytes)
    original = [(60, 0.0, 0.4), (65, 0.4, 1.2), (67, 1.2, 2.0), (60, 2.0, 2.15)]
    assert len(midi) == len(original)
    tol = max(_tick_tolerance(80.0), 0.02)
    for got, expected in zip(
        sorted(midi, key=lambda row: (row[1], row[0])),
        sorted(original, key=lambda row: (row[1], row[0])),
    ):
        assert got[0] == expected[0]
        assert abs(got[1] - expected[1]) <= tol
        assert abs(got[2] - expected[2]) <= tol
    for item in model["notes"]:
        start, duration, voice, start_sec, end_sec = before[item["source_note_id"]]
        assert item["start"] == start
        assert item["duration"] == duration
        assert item["voice"] == voice
        assert item["start_sec"] == start_sec
        assert item["end_sec"] == end_sec


def test_ties_triplets_pickups_and_long_curve():
    time_map = MusicalTimeMap.from_bpm(120.0, duration_sec=12.0)
    snapshot = _snapshot(
        [
            ("pickup", 62, 0.25, 0.5, 70),
            ("tie-long", 48, 0.5, 4.5, 60),
            ("trip-a", 72, 4.5, 4.6666667, 80),
            ("trip-b", 74, 4.6666667, 4.8333334, 80),
            ("trip-c", 76, 4.8333334, 5.0, 80),
            ("early-end", 55, 0.5, 1.0, 50, "track:1", "left"),
        ]
    )
    model = extract_from_performance(snapshot, time_map, time_signature="4/4")
    model["tempo_curve"] = [{"beat": float(i), "bpm": 90.0 + (i % 5)} for i in range(40)]
    model["tempo_bpm"] = 90.0
    assert len(model["tempo_curve"]) > 12
    by_id = {item["source_note_id"]: item for item in model["notes"]}
    assert by_id["pickup"]["start"] == pytest.approx(0.5)
    assert by_id["tie-long"]["duration"] == pytest.approx(8.0)
    assert by_id["early-end"]["track"] == 1
    by_id["trip-b"]["pitch"] = 75
    xml_text, midi_bytes = build_musicxml_and_midi(model)
    rebuilt = extract_from_musicxml(xml_text)
    restored = {item["source_note_id"]: item for item in rebuilt["notes"]}
    assert restored["trip-b"]["pitch"] == 75
    assert restored["trip-a"]["pitch"] == 72
    assert restored["tie-long"]["source_note_id"] == "tie-long"
    midi = _midi_notes(midi_bytes)
    assert any(pitch == 75 for pitch, _start, _end in midi)
    assert any(pitch == 48 for pitch, _start, _end in midi)
