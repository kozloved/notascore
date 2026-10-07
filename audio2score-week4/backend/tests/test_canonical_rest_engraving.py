"""Silence exposes meter without changing attacks or source ownership."""

from fractions import Fraction as F
from xml.etree import ElementTree as ET

import pytest

from mir.models import MeterHypothesis, NotationPlan, PlannedNote, PlannedRest
from mir.notation_settings import NotationSettings
from mir.performance_score import report_from_events
from mir.types import Hand, MusicalEvent
from notation_engine.exact_plan import (
    _pieces, _rest_pieces, annotate_rhythm, build_exact_measures,
)


@pytest.mark.parametrize("policy", ["preserve", "show_meter"])
@pytest.mark.parametrize("start,length,pulse,bar,expected", [
    (F(1, 2), F(3, 2), F(1), F(4), [F(1, 2), F(1)]),
    (F(1), F(2), F(1), F(4), [F(1), F(1)]),
    (F(2), F(2), F(1), F(4), [F(2)]),
    (F(0), F(2), F(1), F(3), [F(1), F(1)]),
    (F(0), F(3, 2), F(3, 2), F(3), [F(3, 2)]),
    (F(1, 2), F(5, 2), F(3, 2), F(3), [F(1), F(3, 2)]),
    (F(0), F(3), F(3, 2), F(9, 2), [F(3, 2), F(3, 2)]),
])
def test_rests_show_simple_and_compound_pulses(policy, start, length, pulse, bar, expected):
    settings = NotationSettings.from_dict({"syncopation": policy})
    pieces = list(_rest_pieces(start, length, pulse, settings, bar))
    assert [duration for _, duration in pieces] == expected
    assert sum(duration for _, duration in pieces) == length
    assert pieces[0][0] == start
    assert pieces[-1][0] + pieces[-1][1] == start + length


def test_note_syncopation_is_independent_of_rest_spelling():
    settings = NotationSettings.from_dict({"syncopation": "preserve"})
    assert list(_pieces(F(1, 2), F(3, 2), F(1), settings, F(4))) == [
        (F(1, 2), F(3, 2)),
    ]


def test_triplet_rest_retains_time_modification_and_bracket_ownership():
    elements = [
        PlannedNote([72], F(0), F(1, 3), 0),
        PlannedRest(F(1, 3), F(1, 3), 0),
        PlannedNote([74], F(2, 3), F(1, 3), 0),
    ]
    annotate_rhythm(elements, "4/4", "test")
    assert all(el.tuplet is not None for el in elements)
    assert {(el.tuplet.actual, el.tuplet.normal) for el in elements} == {(3, 2)}
    assert len({el.tuplet.group_id for el in elements}) == 1


def test_empty_primary_bars_remain_visible_and_secondary_filler_stays_hidden():
    events = [
        MusicalEvent(72, 0, 1, note_id="opening", hand=Hand.RIGHT, voice=0),
        MusicalEvent(76, 0, F(1, 2), note_id="inner", hand=Hand.RIGHT, voice=1),
        MusicalEvent(74, 8, 1, note_id="return", hand=Hand.RIGHT, voice=0),
    ]
    report = report_from_events(events)
    meter = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
    measures = build_exact_measures(events, report, meter, "C")
    for staff in measures[1].staves:
        primary = staff.voices[0].elements
        assert len(primary) == 1
        assert isinstance(primary[0], PlannedRest)
        assert primary[0].duration_q == 4
        assert not primary[0].hidden and primary[0].kind == "musical"
        for voice in staff.voices[1:]:
            assert all(el.hidden and el.kind == "structural" for el in voice.elements)
    assert {sid for measure in measures for staff in measure.staves
            for voice in staff.voices for el in voice.elements
            if isinstance(el, PlannedNote) for sid in el.event_ids} == {
        "opening", "inner", "return",
    }


@pytest.mark.parametrize("signature,numerator,denominator,bar", [
    ("3/4", 3, 4, F(3)), ("4/4", 4, 4, F(4)), ("6/8", 6, 8, F(3)),
])
def test_musicxml_empty_bar_has_visible_measure_rest(tmp_path, signature, numerator, denominator, bar):
    from notation_engine.writer import NotationWriter

    events = [MusicalEvent(72, float(2 * bar), 1, note_id="return", hand=Hand.RIGHT)]
    report = report_from_events(events)
    hypothesis = MeterHypothesis(signature, numerator, denominator, float(bar), 1.0, 1.0)
    plan = NotationPlan(time_signature=signature, measures=build_exact_measures(
        events, report, hypothesis, "C",
    ))
    path = NotationWriter().score_from_plan(plan).write("musicxml", fp=tmp_path / "empty.xml")
    root = ET.parse(path).getroot()
    for part in root.findall("part"):
        rest = part.find("measure/note")
        assert rest is not None
        assert rest.get("print-object") != "no"
        assert rest.find("rest").get("measure") == "yes"


def test_triplet_rest_bracket_survives_musicxml_export(tmp_path):
    from music21 import meter, stream
    from notation_engine.writer import NotationWriter

    elements = [
        PlannedRest(F(0), F(1, 3), 0),
        PlannedNote([72], F(1, 3), F(1, 3), 0),
        PlannedNote([74], F(2, 3), F(1, 3), 0),
    ]
    annotate_rhythm(elements, "4/4", "export")
    measure = stream.Measure(number=1)
    measure.append(meter.TimeSignature("4/4"))
    writer = NotationWriter()
    for el in elements:
        measure.insert(el.start_q, writer._element_to_m21(el))
    part = stream.Part()
    part.append(measure)
    score = stream.Score()
    score.append(part)
    path = score.write("musicxml", fp=tmp_path / "triplet.xml")
    root = ET.parse(path).getroot()
    rest = root.find("part/measure/note")
    assert rest.find("rest") is not None
    assert rest.findtext("time-modification/actual-notes") == "3"
    assert rest.find("notations/tuplet").get("type") == "start"
