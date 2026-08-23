"""Tests for ChordDetector and role separation."""

from audio_engine.chord_detector import ChordDetector
from audio_engine.role_separator import MelodyAccompanimentSeparator
from mir.types import NoteEvent


def test_chord_detector_c_major():
    notes = [
        NoteEvent(pitch=60, start_time=0.5, end_time=1.0),
        NoteEvent(pitch=64, start_time=0.5, end_time=1.0),
        NoteEvent(pitch=67, start_time=0.5, end_time=1.0),
    ]
    chords = ChordDetector().detect(notes)
    assert len(chords) == 1
    assert chords[0].name in ("C", "Cmaj7", "cluster")


def test_role_separator():
    notes = [
        NoteEvent(pitch=48, start_time=0.0, end_time=1.0, velocity=60),
        NoteEvent(pitch=60, start_time=0.0, end_time=1.0, velocity=70),
        NoteEvent(pitch=72, start_time=0.0, end_time=1.0, velocity=90),
    ]
    role = MelodyAccompanimentSeparator().separate(notes)
    assert role.melody_notes
    assert role.bass_notes or role.accompaniment_notes
