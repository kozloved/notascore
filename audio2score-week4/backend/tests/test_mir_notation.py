"""Tests for MIR layers and notation writer."""

from mir.articulation import ArticulationDetector
from mir.cmr_builder import notes_to_events
from mir.dynamics import DynamicsExtractor
from mir.hand_separator import HandSeparator
from mir.types import Hand, InstrumentKind, MusicalEvent, NoteEvent, ScoreMeta, TempoMap, TempoPoint
from mir.voice_separator import VoiceSeparator
from notation_engine.writer import NotationWriter


def test_notes_to_events():
    notes = [NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=80)]
    tm = TempoMap(points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0)])
    events = notes_to_events(notes, tm, instrument=InstrumentKind.PIANO)
    assert len(events) == 1
    assert events[0].start_beat == 0.0
    assert events[0].duration_beats > 0


def test_hand_separator():
    events = [
        MusicalEvent(pitch=48, start_beat=0.0, duration_beats=1.0),
        MusicalEvent(pitch=72, start_beat=0.0, duration_beats=1.0),
    ]
    separated = HandSeparator().separate(events)
    hands = {e.hand for e in separated}
    assert Hand.LEFT in hands
    assert Hand.RIGHT in hands


def test_voice_separator_chords_share_a_voice():
    events = [
        MusicalEvent(pitch=60, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT),
        MusicalEvent(pitch=64, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT),
    ]
    voiced = VoiceSeparator().separate(events)
    voices = {e.voice for e in voiced}
    assert len(voices) == 1


def test_dynamics_extractor():
    events = [MusicalEvent(pitch=60, start_beat=0.0, duration_beats=1.0, velocity=100)]
    out = DynamicsExtractor().extract(events)
    assert out[0].dynamic in ("f", "ff", "fff")


def test_articulation_staccato():
    events = [MusicalEvent(pitch=60, start_beat=0.0, duration_beats=0.1)]
    out = ArticulationDetector().detect(events)
    assert out[0].articulation == "staccato"


def test_notation_writer_builds_score():
    events = [
        MusicalEvent(pitch=60, start_beat=0.0, duration_beats=1.0, velocity=80),
        MusicalEvent(pitch=64, start_beat=1.0, duration_beats=1.0, velocity=80),
    ]
    meta = ScoreMeta(display_tempo_bpm=120)
    score = NotationWriter().write_from_events_direct(events, meta)
    notes = list(score.recurse().notes)
    assert len(notes) >= 2
