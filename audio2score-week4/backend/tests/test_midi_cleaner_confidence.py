"""MIDI cleaning: KEEP / SUPPRESS / UNCERTAIN with reasons."""

from mir.midi_cleaner import MIDICleaner
from mir.models import CleaningAction
from mir.types import NoteEvent


def test_duplicate_notes_merge():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=80, confidence=0.9),
        NoteEvent(pitch=60, start_time=0.01, end_time=0.52, velocity=40, confidence=0.4),
    ]
    cleaned, report = MIDICleaner().clean_with_report(notes)
    assert len(cleaned) == 1
    assert any(d.reason == "duplicate_same_pitch_onset" for d in report)


def test_real_octave_doubling_kept():
    notes = [
        NoteEvent(pitch=48, start_time=0.0, end_time=1.0, velocity=80, confidence=0.9),
        NoteEvent(pitch=60, start_time=0.0, end_time=1.0, velocity=78, confidence=0.9),
    ]
    cleaned, report = MIDICleaner().clean_with_report(notes)
    assert len(cleaned) == 2
    assert any(d.reason == "octave_doubling" for d in report)
    assert all(d.action != CleaningAction.SUPPRESS for d in report if "octave" in d.reason)


def test_false_octave_ghost_flagged_when_not_dropping():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=1.0, velocity=90, confidence=0.95),
        NoteEvent(pitch=72, start_time=0.01, end_time=0.20, velocity=25, confidence=0.2),
    ]
    cleaned, report = MIDICleaner(drop_octave_ghosts=False).clean_with_report(notes)
    pitches = {n.pitch for n in cleaned}
    assert 60 in pitches
    assert 72 in pitches
    assert any(d.reason == "octave_ghost_candidate" for d in report)


def test_short_grace_like_notes_uncertain():
    notes = [
        NoteEvent(pitch=71, start_time=0.0, end_time=0.03, velocity=88, confidence=0.8),
        NoteEvent(pitch=72, start_time=0.10, end_time=0.50, velocity=80, confidence=0.9),
    ]
    cleaned, report = MIDICleaner().clean_with_report(notes)
    assert {n.pitch for n in cleaned} == {71, 72}
    assert any(d.action == CleaningAction.UNCERTAIN for d in report)


def test_repeated_notes_not_merged():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.20, velocity=80),
        NoteEvent(pitch=60, start_time=0.25, end_time=0.45, velocity=80),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert len(cleaned) == 2


def test_same_pitch_overlaps_merge():
    notes = [
        NoteEvent(pitch=64, start_time=0.0, end_time=0.40, velocity=70),
        NoteEvent(pitch=64, start_time=0.02, end_time=0.50, velocity=60),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert len(cleaned) == 1
    assert cleaned[0].end_time >= 0.50
