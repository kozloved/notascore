"""Global meter inference from onset / accent patterns."""

from __future__ import annotations

from collections import defaultdict

from mir.models import MeterHypothesis
from mir.types import MusicalEvent


SUPPORTED_METERS = (
    ("2/4", 2, 4, 2.0),
    ("3/4", 3, 4, 3.0),
    ("4/4", 4, 4, 4.0),
    ("6/8", 6, 8, 3.0),
    ("12/8", 12, 8, 6.0),
)


def meter_from_time_signature(
    time_signature: str,
    *,
    confidence: float = 0.9,
    source: str = "meta_hint",
) -> MeterHypothesis:
    """Build a MeterHypothesis from an explicit time-signature string."""
    ts = (time_signature or "4/4").strip()
    for name, num, den, mql in SUPPORTED_METERS:
        if name == ts:
            return MeterHypothesis(
                time_signature=name,
                numerator=num,
                denominator=den,
                measure_quarter_length=mql,
                score=confidence,
                confidence=confidence,
                evidence={"source": source},
            )
    try:
        num_s, den_s = ts.split("/", 1)
        num, den = int(num_s), int(den_s)
        mql = (float(num) * 4.0) / float(den)
    except (ValueError, ZeroDivisionError):
        return meter_from_time_signature("4/4", confidence=0.2, source="invalid_hint")
    return MeterHypothesis(
        time_signature=ts,
        numerator=num,
        denominator=den,
        measure_quarter_length=mql,
        score=confidence,
        confidence=confidence,
        evidence={"source": source},
    )


class MeterEstimator:
    """Score meter candidates globally. Do not pick a meter from one bar."""

    def estimate(self, events: list[MusicalEvent]) -> list[MeterHypothesis]:
        if not events:
            return [
                MeterHypothesis(
                    time_signature="4/4",
                    numerator=4,
                    denominator=4,
                    measure_quarter_length=4.0,
                    score=0.2,
                    confidence=0.2,
                    evidence={"reason": "empty"},
                )
            ]

        onsets = [e.start_beat for e in sorted(events, key=lambda x: x.start_beat)]
        weights = []
        for e in sorted(events, key=lambda x: x.start_beat):
            w = max(1.0, e.velocity / 64.0)
            if e.hand.value == "left" or e.role == "bass":
                w *= 2.2
            w *= 1.0 + max(0.0, (60 - e.pitch) / 30.0)
            weights.append(w)
        hypotheses: list[MeterHypothesis] = []

        for name, num, den, mql in SUPPORTED_METERS:
            score, evidence = self._score_meter(onsets, weights, events, name, mql)
            hypotheses.append(
                MeterHypothesis(
                    time_signature=name,
                    numerator=num,
                    denominator=den,
                    measure_quarter_length=mql,
                    score=score,
                    confidence=min(0.95, max(0.15, score)),
                    evidence=evidence,
                )
            )

        hypotheses.sort(key=lambda h: h.score, reverse=True)
        total = sum(h.score for h in hypotheses) or 1.0
        for h in hypotheses:
            h.confidence = min(0.95, h.score / total + 0.15)
        return hypotheses

    def select(self, events: list[MusicalEvent]) -> MeterHypothesis:
        hyps = self.estimate(events)
        return hyps[0]

    def ranked_candidates(self, events: list[MusicalEvent]) -> list[dict]:
        """Expose ranked meter scores, not only the winner."""
        hyps = self.estimate(events)
        total = sum(max(0.0, h.score) for h in hyps) or 1.0
        rows = []
        for h in hyps:
            rows.append(
                {
                    "meter": h.time_signature,
                    "score": round(float(h.score), 4),
                    "confidence": round(float(h.confidence), 4),
                    "normalized": round(max(0.0, float(h.score)) / total, 4),
                }
            )
        return rows

    def _score_meter(
        self,
        onsets: list[float],
        weights: list[float],
        events: list[MusicalEvent],
        name: str,
        measure_ql: float,
    ) -> tuple[float, dict]:
        if measure_ql <= 0:
            return 0.0, {}

        span = max(onsets[-1] - onsets[0], 1.0)
        n_measures = max(1, int(round(span / measure_ql)))
        beat_bins: dict[int, float] = defaultdict(float)

        if name in ("6/8", "12/8"):
            pulse = 0.5  # eighth
            strong = {0}
            medium = {3} if name == "6/8" else {0, 6}
            if name == "12/8":
                medium = {3, 6, 9}
                strong = {0, 6}
        elif name == "3/4":
            pulse = 1.0
            strong = {0}
            medium = {1, 2}
        elif name == "2/4":
            pulse = 1.0
            strong = {0}
            medium = {1}
        else:
            pulse = 1.0
            strong = {0}
            medium = {2}

        alignment = 0.0
        accent = 0.0
        total_w = 0.0
        for onset, w in zip(onsets, weights):
            rel = onset % measure_ql
            grid = rel / pulse
            err = abs(grid - round(grid))
            alignment += w * (1.0 - min(1.0, err * 2.0))
            bin_i = int(round(rel / pulse))
            beat_bins[bin_i] += w
            total_w += w
            if int(round(rel / pulse)) in strong:
                accent += w
            elif int(round(rel / pulse)) in medium:
                accent += 0.45 * w

        alignment /= max(total_w, 1e-6)
        accent /= max(total_w, 1e-6)

        # Periodicity: similar onset density per measure
        densities = []
        start = onsets[0]
        for i in range(n_measures):
            a = start + i * measure_ql
            b = a + measure_ql
            densities.append(sum(1 for o in onsets if a <= o < b))
        if densities:
            avg = sum(densities) / len(densities)
            var = sum((d - avg) ** 2 for d in densities) / len(densities)
            stability = 1.0 / (1.0 + var / (avg + 1.0))
        else:
            stability = 0.5

        compound_bonus = 0.0
        if name in ("6/8", "12/8"):
            dq = 1.5
            on_beat = 0.0
            off_beat = 0.0
            for onset, w in zip(onsets, weights):
                rel = onset % measure_ql
                dq_err = abs((rel / dq) - round(rel / dq))
                eighth_off = abs((rel / 0.5) - round(rel / 0.5)) < 0.12
                if dq_err < 0.12:
                    on_beat += w
                elif eighth_off:
                    off_beat += w
            if on_beat > off_beat * 1.05:
                compound_bonus = 0.2 * (on_beat / max(on_beat + off_beat, 1e-6))
            else:
                compound_bonus = -0.35
        if name == "3/4":
            dq_hit = 0.0
            q_hit = 0.0
            for onset, w in zip(onsets, weights):
                rel = onset % 3.0
                dq_hit += w * (1.0 if abs(rel - 1.5) < 0.12 else 0.0)
                q_hit += w * (1.0 if min(abs(rel - 1.0), abs(rel - 2.0)) < 0.12 else 0.0)
            if dq_hit > q_hit * 1.2:
                compound_bonus -= 0.2

        score = 0.45 * alignment + 0.30 * accent + 0.20 * stability + compound_bonus
        if len(onsets) < 8:
            if name == "4/4":
                score += 0.4
            else:
                score *= 0.4
        if name == "4/4":
            eighth_align = 0.0
            for onset, w in zip(onsets, weights):
                rel = (onset % measure_ql) / 0.5
                err = abs(rel - round(rel))
                eighth_align += w * (1.0 - min(1.0, err * 2.0))
            eighth_align /= max(total_w, 1e-6)
            score = (
                0.25 * alignment
                + 0.25 * eighth_align
                + 0.25 * accent
                + 0.20 * stability
                + 0.08
            )
        return max(0.0, score), {
            "alignment": alignment,
            "accent": accent,
            "stability": stability,
            "n_measures": n_measures,
        }
