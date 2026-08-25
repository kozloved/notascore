"""Combine MeterEstimator, beat grouping, and accent evidence into a MeterDecision.

madmom grouping is evidence, not a final time signature. MIDI file meters are
authoritative. 12/8 may be observed but MVP output prefers 6/8 when they tie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mir.meter import MeterEstimator, meter_from_time_signature
from mir.models import MeterDecision, MeterHypothesis
from mir.types import MusicalEvent

MVP_METERS = ("2/4", "3/4", "4/4", "6/8")
COMPOUND_MARGIN = 0.12
TRIPLE_GAP = 0.04


@dataclass
class BeatGroupingEvidence:
    """Beat-tracker output used as grouping evidence, never as a hard meter."""

    source: str = "none"
    beats_per_bar: int | None = None
    grouping_meter: str | None = None
    beat_times: list[float] = field(default_factory=list)
    downbeat_times: list[float] = field(default_factory=list)
    grouping_beats_per_bar: int | None = None
    bpm: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _event_weight(event: MusicalEvent) -> float:
    w = max(1.0, (event.velocity or 64) / 64.0)
    if event.hand.value == "left" or event.role == "bass":
        w *= 2.2
    w *= 1.0 + max(0.0, (60 - event.pitch) / 30.0)
    return w


def downbeat_periodicity(beat_evidence: BeatGroupingEvidence | None) -> dict[str, Any]:
    """Bar length from downbeat spacing, as quarter-note beats at the tracked BPM."""
    if beat_evidence is None or len(beat_evidence.downbeat_times) < 2:
        n = len(beat_evidence.downbeat_times) if beat_evidence else 0
        return {
            "downbeat_count": n,
            "bar_quarter_beats": None,
            "periodicity_ok": False,
        }
    times = sorted(float(t) for t in beat_evidence.downbeat_times)
    gaps = [b - a for a, b in zip(times, times[1:]) if (b - a) > 1e-3]
    if not gaps:
        return {
            "downbeat_count": len(times),
            "bar_quarter_beats": None,
            "periodicity_ok": False,
        }
    gaps.sort()
    median_sec = gaps[len(gaps) // 2]
    bpm = float(beat_evidence.bpm or 120.0)
    bar_q = median_sec * bpm / 60.0
    return {
        "downbeat_count": len(times),
        "median_bar_sec": round(median_sec, 4),
        "bar_quarter_beats": round(bar_q, 3),
        "periodicity_ok": True,
        "suggests_triple_or_compound": 2.4 <= bar_q <= 3.6,
        "suggests_duple": (1.6 <= bar_q <= 2.4) or (3.6 < bar_q <= 4.6),
    }


def _phase_beat(events: list[MusicalEvent], beat_evidence: BeatGroupingEvidence | None) -> float:
    """Align the 3.0-quarter accent window to the first detected downbeat."""
    if not events or beat_evidence is None or not beat_evidence.downbeat_times:
        return 0.0
    first = min(events, key=lambda e: e.start_beat)
    t0 = first.start_time_sec
    if t0 is None:
        return 0.0
    bpm = float(beat_evidence.bpm or 120.0)
    db = min(beat_evidence.downbeat_times)
    phase = ((db - float(t0)) * bpm / 60.0) % 3.0
    # Snap to the eighth grid so jitter does not rotate S-W-W into 6/8.
    return round(phase * 2.0) / 2.0


def triple_meter_evidence(
    events: list[MusicalEvent],
    *,
    phase_beat: float = 0.0,
) -> dict[str, Any]:
    """Distinguish 3/4 (S W W quarters) from 6/8 (S w w M w w eighths).

    Both meters share a 3.0-quarter cycle. Bass / low / loud onsets at 0 and
    1.5 support two compound pulses; onsets at 1.0 and 2.0 without 1.5 support
    three quarter groups.
    """
    bins = [0.0] * 6
    empty = {
        "score_3_4": 0.0,
        "score_6_8": 0.0,
        "prefers_6_8": False,
        "prefers_3_4": False,
        "bass_at_1_5": 0.0,
        "quarter_offbeats": 0.0,
        "phase_beat": phase_beat,
    }
    if not events:
        return empty
    for event in events:
        rel = (event.start_beat - phase_beat) % 3.0
        idx = int(round(rel / 0.5)) % 6
        bins[idx] += _event_weight(event)
    total = sum(bins) or 1.0
    norm = [b / total for b in bins]
    # 6/8 template: strong 0, medium 3 (beat 1.5), weak eighths.
    score_68 = (
        1.15 * norm[0]
        + 0.95 * norm[3]
        + 0.20 * (norm[1] + norm[5])
        - 0.35 * (norm[2] + norm[4])
    )
    # 3/4 template: strong 0, medium quarters 1 and 2, penalize dotted-quarter.
    score_34 = (
        1.10 * norm[0]
        + 0.70 * (norm[2] + norm[4])
        - 0.55 * norm[3]
        - 0.10 * (norm[1] + norm[5])
    )
    return {
        "score_3_4": round(score_34, 4),
        "score_6_8": round(score_68, 4),
        "prefers_6_8": score_68 > score_34 + TRIPLE_GAP,
        "prefers_3_4": score_34 > score_68 + TRIPLE_GAP,
        "bass_at_1_5": round(norm[3], 4),
        "quarter_offbeats": round(norm[2] + norm[4], 4),
        "eighth_bins": [round(x, 4) for x in norm],
        "phase_beat": phase_beat,
    }


def _score_map(hyps: list[MeterHypothesis]) -> dict[str, float]:
    return {h.time_signature: float(h.score) for h in hyps}


def _mvp_meter(name: str) -> str:
    if name == "12/8":
        return "6/8"
    if name in MVP_METERS:
        return name
    return "4/4"


def _hypothesis_for(name: str, hyps: list[MeterHypothesis], confidence: float) -> MeterHypothesis:
    for hyp in hyps:
        if hyp.time_signature == name:
            return MeterHypothesis(
                time_signature=hyp.time_signature,
                numerator=hyp.numerator,
                denominator=hyp.denominator,
                measure_quarter_length=hyp.measure_quarter_length,
                score=hyp.score,
                confidence=confidence,
                evidence=dict(hyp.evidence),
            )
    mapped = _mvp_meter(name)
    return meter_from_time_signature(mapped, confidence=confidence, source="meter_decision")


class MeterArbitrator:
    """Canonical meter decision. Does not treat madmom grouping as a hard hint."""

    def __init__(self, estimator: MeterEstimator | None = None):
        self.estimator = estimator or MeterEstimator()

    def decide(
        self,
        events: list[MusicalEvent],
        *,
        beat_evidence: BeatGroupingEvidence | None = None,
        file_meter: str | None = None,
    ) -> MeterDecision:
        hyps = self.estimator.estimate(events)
        ranked = self.estimator.ranked_candidates(events)
        scores = _score_map(hyps)
        phase = _phase_beat(events, beat_evidence)
        triple = triple_meter_evidence(events, phase_beat=phase)
        period = downbeat_periodicity(beat_evidence)
        grouping = beat_evidence.grouping_beats_per_bar if beat_evidence else None
        if grouping is None and beat_evidence is not None:
            grouping = beat_evidence.beats_per_bar
        grouping_meter = beat_evidence.grouping_meter if beat_evidence else None
        sources: list[str] = ["meter_estimator"]
        if beat_evidence and beat_evidence.source != "none":
            sources.append(f"beat_grouping:{beat_evidence.source}")
        sources.append("accent_periodicity")
        if period.get("periodicity_ok"):
            sources.append("downbeat_periodicity")

        if file_meter:
            meter = _mvp_meter(file_meter) if file_meter == "12/8" else file_meter
            if meter not in MVP_METERS and file_meter not in ("5/4", "7/8", "9/8"):
                meter = _mvp_meter(file_meter)
            # Preserve explicit MIDI 6/8, 3/4, 4/4, 2/4 and uncommon file meters.
            chosen = file_meter if file_meter else meter
            if chosen == "12/8":
                chosen = "6/8"
            hyp = _hypothesis_for(chosen, hyps, confidence=0.92)
            return MeterDecision(
                meter=chosen,
                confidence=0.92,
                candidate_scores=ranked,
                evidence_sources=["midi_file", *sources],
                reason="explicit_file_time_signature",
                was_hint_overridden=False,
                hypothesis=hyp,
                extra={
                    "file_meter": file_meter,
                    "triple": triple,
                    "grouping": grouping,
                    "downbeat_periodicity": period,
                },
            )

        est_raw = hyps[0].time_signature if hyps else "4/4"
        est_mvp = _mvp_meter(est_raw)
        s68 = scores.get("6/8", 0.0)
        s34 = scores.get("3/4", 0.0)
        s44 = scores.get("4/4", 0.0)
        s128 = scores.get("12/8", 0.0)
        compound_score = max(s68, s128)
        grouping_is_compound = grouping == 6
        grouping_is_triple = grouping == 3
        grouping_is_simple = grouping in (2, 4)

        # 12/8 vs 6/8: MVP scope prior.
        if est_raw == "12/8" and abs(s128 - s68) <= 1e-6:
            est_mvp = "6/8"

        chosen = est_mvp
        reason = "estimator_winner"
        overridden = False
        confidence = min(0.93, max(0.2, hyps[0].confidence if hyps else 0.2))

        # Strong compound grouping from a 6-state DBN is evidence for 6/8,
        # not an automatic final meter.
        if grouping_is_compound and (compound_score + 0.05 >= s34 or triple["prefers_6_8"]):
            chosen = "6/8"
            reason = "compound_grouping_and_estimator"
            confidence = max(confidence, 0.72)
            overridden = grouping_meter in ("3/4", "4/4")

        # Estimator 6/8 (or 12/8) with a significant margin over 3/4, plus
        # compound accent evidence, overrides a 3-beat madmom grouping.
        if (
            compound_score - s34 >= COMPOUND_MARGIN
            and triple["prefers_6_8"]
            and chosen != "6/8"
        ):
            chosen = "6/8"
            reason = "estimator_compound_margin_and_two_pulse_accents"
            overridden = bool(grouping_is_triple or grouping_meter == "3/4")
            confidence = min(0.9, 0.55 + (compound_score - s34))

        # Same margin even if grouping is 3 (historical madmom could not emit 6).
        compound_compatible = bool(
            triple["prefers_6_8"]
            or triple["bass_at_1_5"] >= 0.10
            or (
                triple["score_6_8"] >= triple["score_3_4"] - 0.02
                and triple["bass_at_1_5"] > 0.0
            )
        )
        if (
            grouping_is_triple
            and compound_score - s34 >= COMPOUND_MARGIN
            and compound_compatible
        ):
            chosen = "6/8"
            reason = "override_3beat_grouping_with_compound_evidence"
            overridden = True
            confidence = min(0.9, 0.58 + (compound_score - s34))

        # Sparse transcription: MeterEstimator's <8-onset 4/4 prior is not
        # musical evidence. Triple grouping + compound accents still mean 6/8.
        if (
            len(events) < 8
            and grouping_is_triple
            and compound_compatible
            and chosen == "4/4"
        ):
            chosen = "6/8"
            reason = "sparse_events_triple_grouping_compound_accents"
            overridden = True
            confidence = max(confidence, 0.64)

        # 3/4 vs 6/8: three quarter groups beat two dotted-quarter pulses.
        if triple["prefers_3_4"] and chosen in ("6/8", "12/8", "3/4"):
            # Don't let a 6/8 estimator win a clear S-W-W quarter pattern
            # (typical waltz / simple triple) just because 0 and 3.0 align
            # with a 6/8 barline.
            if s44 < max(s34, compound_score) + 0.15 or grouping_is_triple:
                chosen = "3/4"
                reason = "three_quarter_accent_groups"
                overridden = grouping_is_simple or est_mvp == "6/8"
                confidence = min(0.88, 0.55 + (triple["score_3_4"] - triple["score_6_8"]))

        # Wrong 4-beat grouping on a piece whose estimator contest is 3/4 vs
        # 6/8, with S-W-W quarter accents — choose 3/4, not 4/4 or 6/8.
        if (
            grouping_is_simple
            and triple["prefers_3_4"]
            and est_mvp in ("6/8", "3/4", "12/8")
        ):
            chosen = "3/4"
            reason = "three_quarter_groups_override_simple_grouping"
            overridden = True
            confidence = min(0.86, 0.55 + (triple["score_3_4"] - triple["score_6_8"]))

        # Simple duple/quadruple grouping agrees with estimator 4/4 or 2/4.
        if (
            grouping_is_simple
            and est_mvp in ("4/4", "2/4")
            and not triple["prefers_6_8"]
            and not triple["prefers_3_4"]
            and chosen not in ("6/8", "3/4")
        ):
            chosen = est_mvp
            reason = "simple_grouping_and_estimator"
            overridden = False
            confidence = max(confidence, 0.7)

        # Triple grouping without compound accents is 3/4, even if 4/4 is the
        # short-clip estimator default.
        if (
            grouping_is_triple
            and not triple["prefers_6_8"]
            and triple["prefers_3_4"]
            and chosen == "4/4"
        ):
            chosen = "3/4"
            reason = "triple_grouping_without_compound_accents"
            overridden = True
            confidence = 0.62

        # Downbeats every ~3 quarter notes support 3/4 or 6/8, not 4/4.
        if (
            period.get("suggests_triple_or_compound")
            and chosen == "4/4"
            and (triple["prefers_3_4"] or grouping_is_triple)
        ):
            chosen = "3/4"
            reason = "downbeat_period_three_quarters"
            overridden = True
            confidence = max(confidence, 0.6)
        if (
            period.get("suggests_triple_or_compound")
            and chosen == "4/4"
            and compound_compatible
        ):
            chosen = "6/8"
            reason = "downbeat_period_compound_compatible"
            overridden = True
            confidence = max(confidence, 0.6)

        chosen = _mvp_meter(chosen)
        hyp = _hypothesis_for(chosen, hyps, confidence)
        return MeterDecision(
            meter=chosen,
            confidence=round(float(confidence), 4),
            candidate_scores=ranked,
            evidence_sources=sources,
            reason=reason,
            was_hint_overridden=overridden,
            hypothesis=hyp,
            extra={
                "estimator_winner": est_raw,
                "grouping": grouping,
                "grouping_meter": grouping_meter,
                "triple": triple,
                "compound_margin": round(compound_score - s34, 4),
                "downbeat_periodicity": period,
            },
        )
