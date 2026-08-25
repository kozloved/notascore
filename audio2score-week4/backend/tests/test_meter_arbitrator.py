"""Canonical MeterDecision / MeterArbitrator: combine evidence, do not trust madmom."""

from __future__ import annotations

from mir.meter import MeterEstimator
from mir.meter_arbitrator import BeatGroupingEvidence, MeterArbitrator
from mir.models import MeterHypothesis, MusicalStructure
from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.plan import NotationPlanner


def _ev(pitch, start, dur, hand=Hand.RIGHT, role=None, velocity=80):
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        hand=hand,
        voice=0,
        velocity=velocity,
        role=role,
    )


def _compound_6_8_events():
    events = []
    for bar in range(2):
        base = bar * 3.0
        events.append(_ev(48, base + 0.0, 1.5, hand=Hand.LEFT, role="bass", velocity=90))
        events.append(_ev(72, base + 0.0, 0.5))
        events.append(_ev(74, base + 0.5, 0.5))
        events.append(_ev(76, base + 1.0, 0.5))
        events.append(_ev(48, base + 1.5, 1.5, hand=Hand.LEFT, role="bass", velocity=88))
        events.append(_ev(77, base + 1.5, 0.5))
        events.append(_ev(79, base + 2.0, 0.5))
        events.append(_ev(81, base + 2.5, 0.5))
    return events


def _waltz_3_4_events():
    return [
        _ev(48, 0.0, 1.0, hand=Hand.LEFT, role="bass", velocity=90),
        _ev(72, 0.0, 1.0),
        _ev(74, 1.0, 1.0),
        _ev(76, 2.0, 1.0),
        _ev(48, 3.0, 1.0, hand=Hand.LEFT, role="bass", velocity=90),
        _ev(77, 3.0, 1.0),
        _ev(76, 4.0, 1.0),
        _ev(74, 5.0, 1.0),
    ]


def _straight_4_4_events():
    return [_ev(72, i * 0.5, 0.5) for i in range(16)]


def _triple_grouping(beats_per_bar=3, meter="3/4"):
    return BeatGroupingEvidence(
        source="madmom",
        beats_per_bar=beats_per_bar,
        grouping_meter=meter,
        grouping_beats_per_bar=beats_per_bar,
        bpm=120.0,
        downbeat_times=[0.0, 1.5] if beats_per_bar == 3 else [0.0, 2.0],
        beat_times=[i * 0.5 for i in range(8)],
    )


def test_ranked_candidates_expose_scores_not_only_winner():
    ranked = MeterEstimator().ranked_candidates(_compound_6_8_events())
    assert ranked
    assert {row["meter"] for row in ranked} >= {"2/4", "3/4", "4/4", "6/8"}
    assert ranked[0]["score"] >= ranked[-1]["score"]
    assert "normalized" in ranked[0]
    assert ranked[0]["meter"] in ("6/8", "12/8")


def test_strong_6_8_overrides_conflicting_3_4_grouping():
    decision = MeterArbitrator().decide(
        _compound_6_8_events(),
        beat_evidence=_triple_grouping(3, "3/4"),
    )
    assert decision.meter == "6/8"
    assert decision.was_hint_overridden is True
    assert decision.confidence >= 0.5
    scores = {row["meter"]: row["score"] for row in decision.candidate_scores}
    assert scores["6/8"] > scores["3/4"]
    assert "meter_estimator" in decision.evidence_sources
    assert any("beat_grouping" in s for s in decision.evidence_sources)
    assert decision.reason


def test_waltz_sww_accents_choose_3_4_not_6_8_or_4_4():
    """Bass on 0 and 3.0 with weak quarters is 3/4, even if estimator likes 6/8."""
    grouping = BeatGroupingEvidence(
        source="madmom",
        beats_per_bar=4,
        grouping_meter="4/4",
        grouping_beats_per_bar=4,
        bpm=90.0,
        downbeat_times=[1.99],
        beat_times=[0.0, 0.67, 1.33, 2.0, 2.67, 3.33],
    )
    decision = MeterArbitrator().decide(_waltz_3_4_events(), beat_evidence=grouping)
    assert decision.meter == "3/4"
    extra = decision.extra["triple"]
    assert extra["prefers_3_4"] is True
    assert extra["prefers_6_8"] is False


def test_12_8_tie_uses_mvp_6_8_prior():
    events = _compound_6_8_events()
    hyps = MeterEstimator().estimate(events)
    scores = {h.time_signature: h.score for h in hyps}
    assert abs(scores["6/8"] - scores["12/8"]) < 1e-6
    decision = MeterArbitrator().decide(events)
    assert decision.meter == "6/8"
    assert decision.meter != "12/8"


def test_straight_four_four_stays_four_four():
    grouping = BeatGroupingEvidence(
        source="madmom",
        beats_per_bar=4,
        grouping_meter="4/4",
        grouping_beats_per_bar=4,
        bpm=120.0,
        downbeat_times=[0.0, 2.0],
        beat_times=[i * 0.5 for i in range(16)],
    )
    decision = MeterArbitrator().decide(_straight_4_4_events(), beat_evidence=grouping)
    assert decision.meter in ("4/4", "2/4")
    assert decision.was_hint_overridden is False


def test_midi_file_meter_is_authoritative():
    events = _straight_4_4_events()
    decision = MeterArbitrator().decide(
        events,
        beat_evidence=_triple_grouping(3, "3/4"),
        file_meter="6/8",
    )
    assert decision.meter == "6/8"
    assert decision.reason == "explicit_file_time_signature"
    assert decision.was_hint_overridden is False
    assert "midi_file" in decision.evidence_sources


def test_planner_ignores_madmom_hint_when_decision_selected_meter():
    events = _compound_6_8_events()
    decision = MeterArbitrator().decide(
        events, beat_evidence=_triple_grouping(3, "3/4")
    )
    structure = MusicalStructure(
        events=events,
        meter_hypotheses=MeterEstimator().estimate(events),
        selected_meter=decision.hypothesis,
    )
    meta = ScoreMeta(
        display_tempo_bpm=120,
        time_sig_hint="3/4",
        extra={"meter_source": "madmom", "meter_decision": decision.to_dict()},
    )
    plan, _ = NotationPlanner().build(events, meta=meta, structure=structure)
    assert plan.time_signature == "6/8"
    assert plan.extra.get("meter_decision", {}).get("meter") == "6/8"


def test_planner_keeps_explicit_test_hint_without_structure():
    events = [_ev(72, 0.0, 1.0), _ev(74, 1.0, 1.0), _ev(76, 2.0, 1.0)]
    plan, _ = NotationPlanner().build(
        events, meta=ScoreMeta(display_tempo_bpm=120, time_sig_hint="3/4")
    )
    assert plan.time_signature == "3/4"


def test_planner_uses_meter_decision_source():
    events = _compound_6_8_events()
    hyp = MeterHypothesis(
        time_signature="6/8",
        numerator=6,
        denominator=8,
        measure_quarter_length=3.0,
        score=0.9,
        confidence=0.8,
    )
    structure = MusicalStructure(events=events, selected_meter=hyp)
    meta = ScoreMeta(
        display_tempo_bpm=120,
        time_sig_hint="6/8",
        extra={"meter_source": "meter_decision", "meter_decision": {"meter": "6/8"}},
    )
    plan, _ = NotationPlanner().build(events, meta=meta, structure=structure)
    assert plan.time_signature == "6/8"
    assert plan.extra.get("meter_source") == "meter_decision"


def test_sparse_transcribed_6_8_still_overrides_3_beat_grouping():
    """Fast midi_6_8 often loses simultaneous eighths; remaining stream is still 6/8."""
    events = [
        _ev(60, 0.0, 0.5, hand=Hand.LEFT, role="bass"),
        _ev(72, 0.5, 0.5),
        _ev(72, 1.0, 0.5),
        _ev(74, 1.5, 0.5),
        _ev(74, 2.0, 0.5),
        _ev(74, 2.5, 0.5),
    ]
    decision = MeterArbitrator().decide(
        events, beat_evidence=_triple_grouping(3, "3/4")
    )
    assert decision.meter == "6/8"
    assert decision.was_hint_overridden is True
