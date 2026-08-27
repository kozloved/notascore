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
    assert abs(snap_to_grid(1.0 / 3.0) - (1.0 / 3.0)) < 1e-9


def test_quantize_melody_c_pickup_becomes_quarters():
    """melody_c_major.wav is C4–C5 quarters at 100 BPM with a 0.19s lead-in."""
    from notation_engine.quantize import quantize_events

    bpm = 100.0
    starts_sec = [0.196, 0.802, 1.405, 1.999, 2.602, 3.183, 3.810, 4.391]
    durs_sec = [0.513, 0.510, 0.510, 0.510, 0.510, 0.535, 0.499, 0.545]
    pitches = [60, 62, 64, 65, 67, 69, 71, 72]
    events = [
        MusicalEvent(
            pitch=p,
            start_beat=t * bpm / 60.0,
            duration_beats=d * bpm / 60.0,
            velocity=80,
            hand=Hand.RIGHT,
        )
        for p, t, d in zip(pitches, starts_sec, durs_sec)
    ]
    quantized = quantize_events(events)
    assert [e.pitch for e in quantized] == pitches
    assert [round(e.start_beat, 6) for e in quantized] == [float(i) for i in range(8)]
    assert all(abs(e.duration_beats - 1.0) < 1e-9 for e in quantized)


def test_quantize_does_not_chop_held_bass():
    from notation_engine.quantize import quantize_events

    events = [
        MusicalEvent(pitch=48, start_beat=0.0, duration_beats=4.0, hand=Hand.LEFT),
        MusicalEvent(pitch=72, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT),
        MusicalEvent(pitch=74, start_beat=1.0, duration_beats=1.0, hand=Hand.RIGHT),
    ]
    quantized = quantize_events(events)
    bass = next(e for e in quantized if e.pitch == 48)
    assert abs(bass.duration_beats - 4.0) < 1e-9


def test_estimate_time_signature_defaults_to_four_four():
    from notation_engine.meter import estimate_time_signature

    events = [
        MusicalEvent(pitch=60, start_beat=i * 1.0, duration_beats=1.0)
        for i in range(8)
    ]
    assert estimate_time_signature(events) == "4/4"


def test_writer_spells_ab_not_gs_in_f_minor():
    """MIDI 68 is G# by default; F minor must print A-flat (plain A on the staff)."""
    from notation_engine.writer import spell_midi_for_key

    spelled = spell_midi_for_key(68, "f")
    assert spelled.step == "A"
    assert spelled.alter == -1
    assert spelled.midi == 68

    events = [
        MusicalEvent(pitch=p, start_beat=float(i) * 2.0, duration_beats=2.0, hand=Hand.RIGHT)
        for i, p in enumerate([65, 67, 68, 70, 72])
    ]
    meta = ScoreMeta(display_tempo_bpm=80, time_sig_hint="4/4", key_hint="f")
    score = NotationWriter().write_from_events_direct(events, meta)
    pitched = [n for n in score.recurse().notes if n.isNote]
    ab = next(n for n in pitched if n.pitch.midi == 68)
    assert ab.pitch.step == "A"
    assert ab.pitch.alter == -1
    assert not any(n.pitch.step == "G" and n.pitch.alter == 1 for n in pitched)


def test_estimate_key_f_minor_short_melody():
    from notation_engine.meter import estimate_key

    events = [
        MusicalEvent(pitch=p, start_beat=float(i), duration_beats=1.0)
        for i, p in enumerate([65, 67, 68, 70, 72, 70, 72])
    ]
    assert estimate_key(events) == "f"


def test_bass_octave_notated_as_one_chord():
    """LH D2+D3 should be one glyph (two heads, one stem), not two voices."""
    events = [
        MusicalEvent(pitch=38, start_beat=0.0, duration_beats=0.5, velocity=80, hand=Hand.LEFT, voice=0),
        MusicalEvent(pitch=50, start_beat=0.0, duration_beats=0.5, velocity=80, hand=Hand.LEFT, voice=0),
        MusicalEvent(pitch=54, start_beat=1.0, duration_beats=0.5, velocity=80, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=57, start_beat=1.0, duration_beats=0.5, velocity=80, hand=Hand.RIGHT, voice=0),
    ]
    meta = ScoreMeta(display_tempo_bpm=88, time_sig_hint="3/4", key_hint="D")
    score = NotationWriter().write_from_events_direct(events, meta)
    bass_chords = [
        n
        for n in score.recurse().notesAndRests
        if n.isChord and {p.midi for p in n.pitches} == {38, 50}
    ]
    assert len(bass_chords) == 1
    assert not any(
        n.isNote and n.pitch.midi in (38, 50)
        for n in score.recurse().notes
        if n.isNote
    )
