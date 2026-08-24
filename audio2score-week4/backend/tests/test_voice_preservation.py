"""Voices must survive MusicXML export (Staff → Voice → notes/chords/rests)."""

from music21 import chord as m21chord, note as m21note, stream

from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.plan import NotationPlanner
from notation_engine.writer import NotationWriter


def test_voices_are_not_flattened_into_chords():
    events = [
        MusicalEvent(
            pitch=76, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0
        ),
        MusicalEvent(
            pitch=77, start_beat=1.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0
        ),
        MusicalEvent(
            pitch=79, start_beat=2.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0
        ),
        MusicalEvent(
            pitch=81, start_beat=3.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0
        ),
        MusicalEvent(
            pitch=60, start_beat=0.0, duration_beats=4.0, hand=Hand.RIGHT, voice=1
        ),
    ]
    meta = ScoreMeta(display_tempo_bpm=120)
    plan, _ = NotationPlanner().build(events, meta=meta)
    score = NotationWriter().score_from_plan(plan)
    rh = score.parts[0]
    voices = list(rh.recurse().getElementsByClass(stream.Voice))
    assert len(voices) >= 2

    # The held C4 must not be chorded with the melody notes.
    for v in voices:
        for el in v.notes:
            if isinstance(el, m21chord.Chord):
                midis = {p.midi for p in el.pitches}
                assert not (60 in midis and 76 in midis)


def test_measures_sum_correctly():
    events = [
        MusicalEvent(pitch=72, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=74, start_beat=1.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=76, start_beat=2.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=77, start_beat=3.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=48, start_beat=0.0, duration_beats=4.0, hand=Hand.LEFT, voice=0),
    ]
    plan, _ = NotationPlanner().build(events, meta=ScoreMeta(display_tempo_bpm=120))
    for measure in plan.measures:
        for staff in measure.staves:
            for voice in staff.voices:
                total = sum(el.duration_q for el in voice.elements)
                assert abs(total - measure.duration_beats) < 0.13, (
                    measure.number,
                    staff.staff_id,
                    voice.voice_id,
                    total,
                )


def test_rests_are_inserted():
    events = [
        MusicalEvent(pitch=72, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=74, start_beat=2.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
    ]
    plan, _ = NotationPlanner().build(events, meta=ScoreMeta(display_tempo_bpm=120))
    voice = plan.measures[0].staves[0].voices[0]
    rest_ql = sum(el.duration_q for el in voice.elements if el.__class__.__name__ == "PlannedRest")
    assert rest_ql >= 1.0


def test_same_voice_simultaneous_notes_become_chords():
    events = [
        MusicalEvent(pitch=60, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=64, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=67, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
    ]
    plan, _ = NotationPlanner().build(events, meta=ScoreMeta(display_tempo_bpm=120))
    notes = [
        el
        for el in plan.measures[0].staves[0].voices[0].elements
        if el.__class__.__name__ == "PlannedNote"
    ]
    chord_like = [el for el in notes if len(el.pitches) >= 2]
    assert chord_like
    assert set(chord_like[0].pitches) == {60, 64, 67}


def test_writer_emits_musicxml_with_two_parts_for_piano():
    events = [
        MusicalEvent(pitch=72, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=48, start_beat=0.0, duration_beats=1.0, hand=Hand.LEFT, voice=0),
    ]
    writer = NotationWriter()
    plan, _ = writer.planner.build(events, meta=ScoreMeta(display_tempo_bpm=120))
    score = writer.score_from_plan(plan)
    assert len(score.parts) == 2
    xml = score.write("musicxml")
    text = xml.read_text(encoding="utf-8") if hasattr(xml, "read_text") else str(xml)
    assert "score-partwise" in text.lower() or "part" in text.lower()
