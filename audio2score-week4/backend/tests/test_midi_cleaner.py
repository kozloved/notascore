"""Tests for MIDICleaner."""

from mir.midi_cleaner import MIDICleaner
from mir.types import NoteEvent


def test_merges_chord_starts():
    notes = [
        NoteEvent(pitch=60, start_time=0.500, end_time=1.0, velocity=80),
        NoteEvent(pitch=64, start_time=0.502, end_time=1.0, velocity=75),
        NoteEvent(pitch=67, start_time=0.501, end_time=1.0, velocity=70),
    ]
    cleaned = MIDICleaner().clean(notes)
    starts = {n.start_time for n in cleaned}
    assert len(starts) == 1
    assert 0.500 in starts or 0.501 in starts


def test_removes_micro_notes():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.01, velocity=64),
        NoteEvent(pitch=62, start_time=0.5, end_time=1.0, velocity=64),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert len(cleaned) == 1
    assert cleaned[0].pitch == 62


def test_merges_duplicate_resonance():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=64),
        NoteEvent(pitch=60, start_time=0.01, end_time=0.52, velocity=60),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert len(cleaned) == 1


def test_drops_quiet_octave_ghost():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=1.0, velocity=90, confidence=0.8),
        NoteEvent(pitch=72, start_time=0.02, end_time=0.9, velocity=30, confidence=0.2),
    ]
    cleaned = MIDICleaner().clean(notes)
    pitches = {n.pitch for n in cleaned}
    assert pitches == {60}


def test_drops_two_octave_ghost():
    notes = [
        NoteEvent(pitch=48, start_time=0.0, end_time=1.0, velocity=88, confidence=0.75),
        NoteEvent(pitch=72, start_time=0.01, end_time=0.8, velocity=20, confidence=0.15),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert {n.pitch for n in cleaned} == {48}


def test_keeps_similar_strength_real_octaves():
    notes = [
        NoteEvent(pitch=48, start_time=0.0, end_time=1.0, velocity=80, confidence=0.7),
        NoteEvent(pitch=60, start_time=0.01, end_time=1.0, velocity=78, confidence=0.68),
        NoteEvent(pitch=64, start_time=0.01, end_time=1.0, velocity=76, confidence=0.66),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert {n.pitch for n in cleaned} == {48, 60, 64}


def test_does_not_drop_only_note_in_window():
    notes = [
        NoteEvent(pitch=72, start_time=0.0, end_time=0.4, velocity=20, confidence=0.2),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert len(cleaned) == 1
    assert cleaned[0].pitch == 72
