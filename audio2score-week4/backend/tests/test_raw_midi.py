"""Tests for unquantized MIDI export."""

from __future__ import annotations

import pretty_midi

from mir.raw_midi import write_job_raw_midi, write_notes_to_midi
from mir.types import NoteEvent


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
