"""Canonical pipeline data models and notation plan invariants."""

from mir.models import NotationPlan, RawPerformance, TranscriptionResult
from mir.types import Hand, MusicalEvent, NoteEvent, ScoreMeta
from notation_engine.plan import NotationPlanner


def test_transcription_result_and_raw_performance():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, confidence=0.8, note_id="n0000")
    ]
    result = TranscriptionResult(notes=notes, backend="basic_pitch")
    performance = RawPerformance(notes=result.notes, source_backend=result.backend)
    assert performance.notes[0].note_id == "n0000"
    assert isinstance(NotationPlan(), NotationPlan)


def test_plan_has_measures_staves_voices():
    events = [
        MusicalEvent(pitch=72, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0, note_id="a"),
        MusicalEvent(pitch=48, start_beat=0.0, duration_beats=2.0, hand=Hand.LEFT, voice=0, note_id="b"),
        MusicalEvent(pitch=74, start_beat=1.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0, note_id="c"),
    ]
    plan, decisions = NotationPlanner().build(events, meta=ScoreMeta(display_tempo_bpm=120))
    assert plan.measures
    assert plan.time_signature in {"2/4", "3/4", "4/4", "6/8", "12/8"}
    assert any(s.staff_id == 1 for s in plan.measures[0].staves)
    assert decisions is not None


def test_no_accidental_event_destruction():
    events = [
        MusicalEvent(pitch=p, start_beat=float(i), duration_beats=1.0, hand=Hand.RIGHT, voice=0)
        for i, p in enumerate([72, 74, 76, 77])
    ]
    plan, _ = NotationPlanner().build(events, meta=ScoreMeta(display_tempo_bpm=120))
    pitches = []
    for m in plan.measures:
        for s in m.staves:
            for v in s.voices:
                for el in v.elements:
                    if getattr(el, "pitches", None):
                        pitches.extend(el.pitches)
    for p in (72, 74, 76, 77):
        assert p in pitches
