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


def test_merges_overlapping_same_pitch_into_one_sustain():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=1.0, velocity=80, confidence=0.8),
        NoteEvent(pitch=60, start_time=0.4, end_time=1.2, velocity=70, confidence=0.7),
    ]
    cleaned = MIDICleaner().clean(notes)
    same = [n for n in cleaned if n.pitch == 60]
    assert len(same) == 1
    assert same[0].start_time == 0.0
    assert same[0].end_time >= 1.2


def test_merges_split_held_melody_note():
    """Case1 last C: Basic Pitch re-onsets the same pitch while it is still down."""
    notes = [
        NoteEvent(pitch=70, start_time=9.0, end_time=9.77, velocity=80, confidence=0.8),
        NoteEvent(pitch=72, start_time=9.75, end_time=11.60, velocity=80, confidence=0.8),
        NoteEvent(pitch=72, start_time=11.49, end_time=13.00, velocity=78, confidence=0.75),
    ]
    cleaned = MIDICleaner().clean(notes)
    cs = [n for n in cleaned if n.pitch == 72]
    assert len(cs) == 1
    assert abs(cs[0].start_time - 9.75) < 1e-6
    assert cs[0].end_time >= 13.0
    assert any(n.pitch == 70 for n in cleaned)


def test_drops_isolated_low_ghost_at_end():
    notes = [
        NoteEvent(pitch=65, start_time=0.0, end_time=1.5, velocity=90, confidence=0.9),
        NoteEvent(pitch=67, start_time=1.5, end_time=3.0, velocity=88, confidence=0.9),
        NoteEvent(pitch=68, start_time=3.0, end_time=4.5, velocity=86, confidence=0.85),
        NoteEvent(pitch=70, start_time=4.5, end_time=6.0, velocity=84, confidence=0.85),
        NoteEvent(pitch=72, start_time=6.0, end_time=9.0, velocity=82, confidence=0.8),
        NoteEvent(pitch=22, start_time=13.1, end_time=13.4, velocity=40, confidence=0.3),
    ]
    cleaned, report = MIDICleaner().clean_with_report(notes)
    assert {n.pitch for n in cleaned} == {65, 67, 68, 70, 72}
    assert any(d.reason == "isolated_low_ghost" and d.pitch == 22 for d in report)


def test_keeps_real_left_hand_bass_line():
    notes = [
        NoteEvent(pitch=72, start_time=0.0, end_time=0.5, velocity=80, confidence=0.8),
        NoteEvent(pitch=74, start_time=0.5, end_time=1.0, velocity=80, confidence=0.8),
        NoteEvent(pitch=76, start_time=1.0, end_time=1.5, velocity=80, confidence=0.8),
        NoteEvent(pitch=36, start_time=0.0, end_time=0.5, velocity=70, confidence=0.75),
        NoteEvent(pitch=38, start_time=0.5, end_time=1.0, velocity=70, confidence=0.75),
        NoteEvent(pitch=40, start_time=1.0, end_time=1.5, velocity=70, confidence=0.75),
    ]
    cleaned = MIDICleaner().clean(notes)
    assert {n.pitch for n in cleaned} == {72, 74, 76, 36, 38, 40}


def test_stretches_short_final_note():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=80),
        NoteEvent(pitch=62, start_time=0.5, end_time=1.0, velocity=80),
        NoteEvent(pitch=64, start_time=1.0, end_time=1.1, velocity=80),
    ]
    cleaned = MIDICleaner().clean(notes)
    last = max(cleaned, key=lambda n: n.start_time)
    assert last.pitch == 64
    assert last.duration >= 0.4
