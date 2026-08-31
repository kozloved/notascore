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


def test_duple_downbeats_block_three_four_override_of_simple_grouping():
    """Case2-style even chords: 4-beat downbeats must not be rewritten as 3/4."""
    grouping = BeatGroupingEvidence(
        source="madmom",
        beats_per_bar=4,
        grouping_meter="4/4",
        grouping_beats_per_bar=4,
        bpm=69.0,
        downbeat_times=[0.0, 3.45, 6.90, 10.35],
        beat_times=[i * (60.0 / 69.0) for i in range(20)],
    )
    events = []
    for start, dur, pitches in (
        (0.0, 4.0, (60, 63, 67)),
        (4.0, 2.0, (60, 65, 68, 72)),
        (6.0, 2.0, (60, 65, 67, 71)),
        (8.0, 4.0, (60, 63, 67)),
    ):
        for p in pitches:
            events.append(_ev(p, start, dur))
    decision = MeterArbitrator().decide(events, beat_evidence=grouping)
    assert decision.meter in ("4/4", "2/4")
    assert decision.extra["downbeat_periodicity"].get("suggests_duple") is True
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


def test_four_four_block_chords_are_not_called_3_4():
    """Even quarter chords can look like S-W-W in a 3.0 window; 4/4 must survive."""
    events = []
    for beat, (triad, bass) in enumerate(
        [((60, 64, 67), 48), ((67, 71, 74), 43), ((69, 72, 76), 45), ((65, 69, 72), 41)]
    ):
        events.append(_ev(bass, float(beat), 1.0, hand=Hand.LEFT, role="bass"))
        for pitch in triad:
            events.append(_ev(pitch, float(beat), 1.0))
    # Fast often drops an inner chord tone; 4/4 must still hold.
    events = [e for e in events if not (e.pitch == 60 and e.start_beat == 0.0)]
    grouping = BeatGroupingEvidence(
        source="madmom",
        beats_per_bar=4,
        grouping_meter="4/4",
        grouping_beats_per_bar=4,
        bpm=120.0,
        downbeat_times=[0.5],
        beat_times=[0.0, 0.5, 1.0, 1.5],
    )
    decision = MeterArbitrator().decide(events, beat_evidence=grouping)
    assert decision.meter in ("4/4", "2/4")


def test_grouping_6_does_not_override_duple_estimator():
    events = _straight_4_4_events()
    grouping = BeatGroupingEvidence(
        source="madmom",
        beats_per_bar=4,
        grouping_meter="6/8",
        grouping_beats_per_bar=6,
        bpm=120.0,
        downbeat_times=[0.0, 2.0],
        beat_times=[i * 0.5 for i in range(16)],
    )
    decision = MeterArbitrator().decide(events, beat_evidence=grouping)
    assert decision.meter in ("4/4", "2/4")


def test_eighth_stream_with_3beat_grouping_is_6_8_even_if_estimator_likes_4_4():
    events = [
        _ev(48, 0.0, 0.5, hand=Hand.LEFT, role="bass"),
        _ev(72, 0.0, 0.5),
        _ev(74, 0.5, 0.5),
        _ev(76, 1.0, 0.5),
        _ev(77, 1.5, 0.5),
        _ev(79, 2.0, 0.5),
        _ev(81, 2.5, 0.5),
        _ev(72, 3.0, 0.5),
        _ev(74, 3.5, 0.5),
        _ev(76, 4.0, 0.5),
        _ev(77, 4.5, 0.5),
        _ev(79, 5.0, 0.5),
        _ev(81, 5.5, 0.5),
    ]
    decision = MeterArbitrator().decide(
        events, beat_evidence=_triple_grouping(3, "3/4")
    )
    assert decision.meter == "6/8"
    assert decision.was_hint_overridden is True


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
