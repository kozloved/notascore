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


def test_voice_separator_chords_share_voice():
    events = [
        MusicalEvent(pitch=60, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT),
        MusicalEvent(pitch=64, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT),
    ]
    voiced = VoiceSeparator().separate(events)
    assert len({e.voice for e in voiced}) == 1


def test_voice_separator_assigns_voices():
    events = [
        MusicalEvent(pitch=72, start_beat=0.0, duration_beats=2.0, hand=Hand.RIGHT),
        MusicalEvent(pitch=64, start_beat=0.5, duration_beats=1.0, hand=Hand.RIGHT),
    ]
    voiced = VoiceSeparator().separate(events)
    voices = {e.voice for e in voiced}
    assert len(voices) >= 2


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
        MusicalEvent(pitch=60, start_beat=0.0, duration_beats=1.0, velocity=80, hand=Hand.RIGHT),
        MusicalEvent(pitch=64, start_beat=1.0, duration_beats=1.0, velocity=80, hand=Hand.RIGHT),
        MusicalEvent(pitch=48, start_beat=0.0, duration_beats=2.0, velocity=70, hand=Hand.LEFT),
    ]
    meta = ScoreMeta(display_tempo_bpm=120, time_sig_hint="4/4")
    score = NotationWriter().write_from_events_direct(events, meta)
    notes = list(score.recurse().notes)
    assert len(notes) >= 3
    parts = list(score.parts)
    assert len(parts) >= 2


def test_notation_writer_grand_staff_musicxml(tmp_path):
    events = [
        MusicalEvent(pitch=72, start_beat=0.0, duration_beats=1.0, velocity=80, hand=Hand.RIGHT),
        MusicalEvent(pitch=76, start_beat=0.0, duration_beats=1.0, velocity=80, hand=Hand.RIGHT),
        MusicalEvent(pitch=48, start_beat=0.0, duration_beats=4.0, velocity=70, hand=Hand.LEFT),
        MusicalEvent(pitch=67, start_beat=2.0, duration_beats=1.0, velocity=75, hand=Hand.RIGHT),
    ]
    meta = ScoreMeta(display_tempo_bpm=120, time_sig_hint="4/4")
    xml = NotationWriter().write_musicxml(
        events, meta, job_id="grand-test", audio_path=tmp_path / "clip.wav"
    )
    lower = xml.lower()
    assert "score-partwise" in lower
    assert "<rest" in lower
    assert "f</sign>" in lower or "<sign>f</sign>" in lower
    assert "g</sign>" in lower or "<sign>g</sign>" in lower
    assert "<staves>2</staves>" in lower or "part-group" in lower
    assert "<metronome" in lower
    assert "<per-minute>120</per-minute>" in xml.replace(" ", "")
    score_midi = tmp_path / "bp_grand-test" / "grand-test.score.mid"
    assert score_midi.exists()


def test_quantize_prefers_sixteenths_over_triplets():
    from notation_engine.quantize import snap_to_grid

    assert abs(snap_to_grid(1.0) - 1.0) < 1e-9
    assert abs(snap_to_grid(0.5) - 0.5) < 1e-9
    assert abs(snap_to_grid(0.26) - 0.25) < 1e-9


def test_estimate_time_signature_defaults_to_four_four():
    from notation_engine.meter import estimate_time_signature

    events = [
        MusicalEvent(pitch=60, start_beat=i * 1.0, duration_beats=1.0)
        for i in range(8)
    ]
    assert estimate_time_signature(events) == "4/4"
