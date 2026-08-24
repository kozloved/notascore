"""Tests for unquantized MIDI export."""

from __future__ import annotations

import pretty_midi

from mir.raw_midi import write_job_raw_midi, write_notes_to_midi
from mir.types import Hand, MusicalEvent, NoteEvent, TempoMap, TempoPoint


def test_write_notes_to_midi_preserves_seconds(tmp_path):
    notes = [
        NoteEvent(pitch=60, start_time=0.11, end_time=0.47, velocity=88, confidence=0.7),
        NoteEvent(pitch=64, start_time=0.50, end_time=0.91, velocity=70, confidence=0.5),
    ]
    path = write_notes_to_midi(notes, tmp_path / "out.mid", bpm=96)
    midi = pretty_midi.PrettyMIDI(str(path))
    written = sorted(midi.instruments[0].notes, key=lambda n: n.start)
    assert len(written) == 2
    assert written[0].pitch == 60
    assert abs(written[0].start - 0.11) < 0.02
    assert abs(written[0].end - 0.47) < 0.02


def test_write_job_raw_midi_path(tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"")
    notes = [
        NoteEvent(pitch=67, start_time=0.0, end_time=0.4, velocity=64, confidence=0.4),
    ]
    path = write_job_raw_midi(audio, "job-1", notes, bpm=120)
    assert path == tmp_path / "bp_job-1" / "job-1.raw.mid"
    assert path.exists()


def test_write_notes_splits_hands_and_pedal(tmp_path):
    notes = [
        NoteEvent(pitch=48, start_time=0.0, end_time=0.5, velocity=70, confidence=0.6),
        NoteEvent(pitch=72, start_time=0.0, end_time=0.5, velocity=80, confidence=0.7),
    ]
    path = write_notes_to_midi(
        notes,
        tmp_path / "hands.mid",
        bpm=120,
        pedal_events=[(0.1, 127), (0.4, 0)],
    )
    midi = pretty_midi.PrettyMIDI(str(path))
    names = {inst.name for inst in midi.instruments}
    assert "RH" in names and "LH" in names
    ccs = [cc for inst in midi.instruments for cc in inst.control_changes]
    assert any(cc.number == 64 and cc.value == 127 for cc in ccs)


def test_write_notes_writes_tempo_changes_without_moving_notes(tmp_path):
    notes = [
        NoteEvent(pitch=60, start_time=0.5, end_time=1.0, velocity=80),
        NoteEvent(pitch=64, start_time=2.5, end_time=3.0, velocity=80),
    ]
    tm = TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=100.0),
            TempoPoint(time_sec=2.0, beat=0.0, bpm=150.0),
        ]
    )
    path = write_notes_to_midi(notes, tmp_path / "tempo.mid", bpm=100, tempo_map=tm)
    midi = pretty_midi.PrettyMIDI(str(path))
    written = sorted((n for inst in midi.instruments for n in inst.notes), key=lambda n: n.start)
    assert abs(written[0].start - 0.5) < 0.03
    assert abs(written[1].start - 2.5) < 0.03
    times, tempi = midi.get_tempo_changes()
    assert len(tempi) >= 2
    assert abs(float(tempi[0]) - 100.0) < 1.5
    assert any(abs(float(t) - 150.0) < 2.0 for t in tempi)


def test_write_job_raw_midi_uses_note_times_and_event_hands(tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"")
    notes = [
        NoteEvent(pitch=48, start_time=0.11, end_time=0.40, velocity=70),
        NoteEvent(pitch=72, start_time=0.11, end_time=0.40, velocity=80),
    ]
    events = [
        MusicalEvent(pitch=48, start_beat=10.0, duration_beats=1.0, hand=Hand.LEFT),
        MusicalEvent(pitch=72, start_beat=10.0, duration_beats=1.0, hand=Hand.RIGHT),
    ]
    path = write_job_raw_midi(
        audio,
        "hands-times",
        notes,
        bpm=90,
        events=events,
    )
    midi = pretty_midi.PrettyMIDI(str(path))
    by_name = {inst.name: inst for inst in midi.instruments}
    assert abs(by_name["LH"].notes[0].start - 0.11) < 0.02
    assert abs(by_name["RH"].notes[0].start - 0.11) < 0.02


def test_write_notes_to_midi_preserves_seconds(tmp_path):
    notes = [
        NoteEvent(pitch=60, start_time=0.11, end_time=0.47, velocity=88, confidence=0.7),
        NoteEvent(pitch=64, start_time=0.50, end_time=0.91, velocity=70, confidence=0.5),
    ]
    path = write_notes_to_midi(notes, tmp_path / "out.mid", bpm=96)
    midi = pretty_midi.PrettyMIDI(str(path))
    written = sorted(midi.instruments[0].notes, key=lambda n: n.start)
    assert len(written) == 2
    assert written[0].pitch == 60
    assert abs(written[0].start - 0.11) < 0.02
    assert abs(written[0].end - 0.47) < 0.02


def test_write_job_raw_midi_path(tmp_path):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"")
    notes = [
        NoteEvent(pitch=67, start_time=0.0, end_time=0.4, velocity=64, confidence=0.4),
    ]
    path = write_job_raw_midi(audio, "job-1", notes, bpm=120)
    assert path == tmp_path / "bp_job-1" / "job-1.raw.mid"
    assert path.exists()


def test_write_notes_splits_hands_and_pedal(tmp_path):
    notes = [
        NoteEvent(pitch=48, start_time=0.0, end_time=0.5, velocity=70, confidence=0.6),
        NoteEvent(pitch=72, start_time=0.0, end_time=0.5, velocity=80, confidence=0.7),
    ]
    path = write_notes_to_midi(
        notes,
        tmp_path / "hands.mid",
        bpm=120,
        pedal_events=[(0.1, 127), (0.4, 0)],
    )
    midi = pretty_midi.PrettyMIDI(str(path))
    names = {inst.name for inst in midi.instruments}
    assert "RH" in names and "LH" in names
    ccs = [cc for inst in midi.instruments for cc in inst.control_changes]
    assert any(cc.number == 64 and cc.value == 127 for cc in ccs)
