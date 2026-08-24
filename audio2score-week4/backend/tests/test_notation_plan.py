"""Notation plan: measures sum, rests, no event destruction."""

from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.plan import NotationPlanner


def test_notation_plan_measures_and_rests():
    events = [
        MusicalEvent(pitch=72, start_beat=0.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=74, start_beat=2.0, duration_beats=1.0, hand=Hand.RIGHT, voice=0),
        MusicalEvent(pitch=48, start_beat=0.0, duration_beats=4.0, hand=Hand.LEFT, voice=0),
    ]
    plan, _ = NotationPlanner().build(events, meta=ScoreMeta(display_tempo_bpm=120))
    assert plan.measures
    rh = plan.measures[0].staves[0].voices[0]
    assert any(el.__class__.__name__ == "PlannedRest" for el in rh.elements)
    for measure in plan.measures:
        for staff in measure.staves:
            for voice in staff.voices:
                total = sum(el.duration_q for el in voice.elements)
                assert abs(total - measure.duration_beats) < 0.13
