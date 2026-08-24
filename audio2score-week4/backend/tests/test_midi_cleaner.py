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


def test_removes_quiet_micro_notes():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.01, velocity=28),
        NoteEvent(pitch=62, start_time=0.5, end_time=1.0, velocity=64),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert len(cleaned) == 1
    assert cleaned[0].pitch == 62


def test_keeps_loud_short_notes_as_uncertain():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.01, velocity=90, confidence=0.9),
        NoteEvent(pitch=62, start_time=0.5, end_time=1.0, velocity=64),
    ]
    cleaned, report = MIDICleaner().clean_with_report(notes)
    pitches = {n.pitch for n in cleaned}
    assert 60 in pitches
    assert any(d.reason == "micro_note_possible_ornament" for d in report)


def test_merges_duplicate_resonance():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=64),
        NoteEvent(pitch=60, start_time=0.01, end_time=0.52, velocity=60),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert len(cleaned) == 1
