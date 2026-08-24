"""Measure-aware, staff-aware, voice-aware quantization.

Does not snap every note independently onto a global grid. Each (measure,
staff, voice) group selects its own grid by scoring candidate notations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mir.models import MeterHypothesis, staff_for_hand
from mir.types import MusicalEvent, copy_event


# Whole, dotted half, half, dotted quarter, quarter, dotted eighth,
# quarter-note triplet, eighth, dotted sixteenth, eighth-note triplet,
# sixteenth. No complex tuplets.
DURATION_CANDIDATES = (
    4.0,
    3.0,
    2.0,
    1.5,
    1.0,
    0.75,
    2.0 / 3.0,
    0.5,
    0.375,
    1.0 / 3.0,
    0.25,
    0.125,
)

SIMPLE_DURATIONS = {4.0, 2.0, 1.0, 0.5, 0.25, 0.125}
DOTTED_DURATIONS = {3.0, 1.5, 0.75, 0.375}
TUPLET_DURATIONS = {2.0 / 3.0, 1.0 / 3.0}

VOICE_SUM_TOLERANCE = 0.08


@dataclass
class QuantizerConfig:
    absorb_rest_ql: float = 0.12
    max_timing_error: float = 0.18
    complexity_weight: float = 0.35
    tuplet_weight: float = 0.55
    tie_weight: float = 0.2
    rest_weight: float = 0.7


class MeasureQuantizer:
    def __init__(self, config: QuantizerConfig | None = None):
        self.config = config or QuantizerConfig()

    def quantize(
        self,
        events: list[MusicalEvent],
        meter: MeterHypothesis,
    ) -> tuple[list[MusicalEvent], list[dict]]:
        if not events:
            return [], []

        grouped: dict[tuple[int, int], list[MusicalEvent]] = {}
        for ev in events:
            key = (staff_for_hand(ev.hand, ev.pitch), int(ev.voice))
            grouped.setdefault(key, []).append(ev)

        out: list[MusicalEvent] = []
        decisions: list[dict] = []
        mql = meter.measure_quarter_length

        for (staff_id, voice_id), group in grouped.items():
            ordered = sorted(group, key=lambda e: (e.start_beat, e.pitch))
            by_measure: dict[int, list[MusicalEvent]] = {}
            for ev in ordered:
                idx = int(math.floor((ev.start_beat + 1e-9) / mql))
                by_measure.setdefault(idx, []).append(ev)
            for measure_idx, bucket in sorted(by_measure.items()):
                q_events, bucket_decisions = self._quantize_bucket(
                    bucket,
                    meter=meter,
                    measure_idx=measure_idx,
                    staff_id=staff_id,
                    voice_id=voice_id,
                    voice_events=ordered,
                )
                out.extend(q_events)
                decisions.extend(bucket_decisions)

        out.sort(key=lambda e: (e.start_beat, e.pitch, e.voice))
        return out, decisions

    def _grids_for(self, meter: MeterHypothesis) -> list[float]:
        if meter.time_signature in ("6/8", "12/8"):
            return [0.5, 0.25, 1.0 / 3.0]
        return [0.25, 0.5, 1.0 / 3.0]

    def _quantize_bucket(
        self,
        bucket: list[MusicalEvent],
        *,
        meter: MeterHypothesis,
        measure_idx: int,
        staff_id: int,
        voice_id: int,
        voice_events: list[MusicalEvent],
    ) -> tuple[list[MusicalEvent], list[dict]]:
        grids = self._grids_for(meter)
        best_events: list[MusicalEvent] | None = None
        best_decisions: list[dict] = []
        best_cost = float("inf")
        best_grid = grids[0]

        for grid in grids:
            q_events, decisions, cost = self._quantize_with_grid(
                bucket,
                meter=meter,
                measure_idx=measure_idx,
                grid=grid,
                staff_id=staff_id,
                voice_id=voice_id,
                voice_events=voice_events,
            )
            if cost < best_cost:
                best_cost = cost
                best_events = q_events
                best_decisions = decisions
                best_grid = grid

        for d in best_decisions:
            d["selected_grid"] = best_grid
            d["staff"] = staff_id
            d["measure"] = measure_idx + 1
        return best_events or list(bucket), best_decisions

    def _quantize_with_grid(
        self,
        bucket: list[MusicalEvent],
        *,
        meter: MeterHypothesis,
        measure_idx: int,
        grid: float,
        staff_id: int,
        voice_id: int,
        voice_events: list[MusicalEvent],
    ) -> tuple[list[MusicalEvent], list[dict], float]:
        cfg = self.config
        mql = meter.measure_quarter_length
        measure_start = measure_idx * mql
        measure_end = measure_start + mql
        tuplet_grid = abs(grid - 1.0 / 3.0) < 1e-6
        ordered = sorted(bucket, key=lambda e: (e.start_beat, e.pitch))
        out: list[MusicalEvent] = []
        decisions: list[dict] = []
        total_cost = 0.0

        for i, ev in enumerate(ordered):
            rel = ev.start_beat - measure_start
            snapped_rel = round(rel / grid) * grid
            snapped_rel = max(0.0, min(max(mql - grid, 0.0), snapped_rel))
            start = measure_start + snapped_rel
            timing_err = abs(start - ev.start_beat)

            next_start = self._next_onset(ev, ordered[i + 1 :], voice_events)
            remaining = 8.0
            if next_start is not None:
                gap = next_start - start
                remaining = max(grid, gap)
                raw_gap = next_start - (start + ev.duration_beats)
                if 0 < raw_gap < cfg.absorb_rest_ql:
                    remaining = max(grid, next_start - start)

            target = min(max(ev.duration_beats, 0.125), remaining)
            orig_end = ev.start_beat + ev.duration_beats
            orig_crosses = orig_end > measure_end + 1e-6
            duration, dur_cost = self._score_duration(
                target=target,
                remaining=remaining,
                measure_remaining=max(0.0, measure_end - start),
                orig_crosses=orig_crosses,
                tuplet_ok=tuplet_grid,
            )

            cost = timing_err + dur_cost
            total_cost += cost
            decisions.append(
                {
                    "note_id": ev.note_id,
                    "pitch": ev.pitch,
                    "raw_start": ev.start_beat,
                    "quantized_start": start,
                    "raw_duration": ev.duration_beats,
                    "quantized_duration": duration,
                    "grid": grid,
                    "timing_error": timing_err,
                    "hand": ev.hand.value,
                    "voice": voice_id,
                    "staff": staff_id,
                    "cost": cost,
                }
            )
            out.append(
                copy_event(
                    ev,
                    start_beat=start,
                    duration_beats=max(0.125, duration),
                )
            )

        mean_straight = 0.0
        if ordered:
            errs = []
            for ev in ordered:
                rel = (ev.start_beat - measure_start) / 0.25
                errs.append(abs(rel - round(rel)))
            mean_straight = sum(errs) / len(errs)
        if tuplet_grid:
            if mean_straight < 0.12:
                total_cost += 4.0
            else:
                total_cost += 0.15
        return out, decisions, total_cost

    def _next_onset(
        self,
        ev: MusicalEvent,
        later_in_bucket: list[MusicalEvent],
        voice_events: list[MusicalEvent],
    ) -> float | None:
        for nxt in later_in_bucket:
            if nxt.start_beat > ev.start_beat + 1e-8:
                return nxt.start_beat
        for nxt in voice_events:
            if nxt.start_beat > ev.start_beat + 1e-8:
                return nxt.start_beat
        return None

    def _score_duration(
        self,
        *,
        target: float,
        remaining: float,
        measure_remaining: float,
        orig_crosses: bool,
        tuplet_ok: bool,
    ) -> tuple[float, float]:
        cfg = self.config
        best_d = min(remaining, 0.25) if remaining > 0 else 0.25
        best_cost = float("inf")

        for d in DURATION_CANDIDATES:
            if d > remaining + 1e-9:
                continue
            if d in TUPLET_DURATIONS and not tuplet_ok:
                continue
            leftover = remaining - d
            actual = d
            rest_pen = 0.0
            if 0 < leftover < cfg.absorb_rest_ql:
                filled = self._nearest_candidate(remaining, tuplet_ok=tuplet_ok)
                if filled is not None and abs(filled - remaining) < cfg.absorb_rest_ql:
                    actual = filled
                    leftover = 0.0
            if 0 < leftover < 0.25:
                rest_pen = 1.0

            complexity = 0.0
            if d in SIMPLE_DURATIONS:
                complexity = 0.0
            elif d in DOTTED_DURATIONS:
                complexity = 0.2
            else:
                complexity = 1.0

            tuplet_pen = 0.0
            if d in TUPLET_DURATIONS:
                simple_err = min(abs(s - target) for s in SIMPLE_DURATIONS | DOTTED_DURATIONS)
                if simple_err <= 0.08:
                    tuplet_pen = 1.0
                else:
                    tuplet_pen = 0.05

            crosses = actual > measure_remaining + 1e-6
            tie_pen = 1.0 if crosses and not orig_crosses else 0.0
            timing = abs(d - target)
            cost = (
                timing
                + cfg.complexity_weight * complexity
                + cfg.tuplet_weight * tuplet_pen
                + cfg.tie_weight * tie_pen
                + cfg.rest_weight * rest_pen
            )
            if cost < best_cost:
                best_cost = cost
                best_d = actual

        if best_cost is float("inf") or best_cost == float("inf"):
            return min(remaining, 0.25) if remaining > 0 else 0.25, 1.0
        return best_d, best_cost

    def _nearest_candidate(self, value: float, tuplet_ok: bool) -> float | None:
        cands = [
            d
            for d in DURATION_CANDIDATES
            if tuplet_ok or d not in TUPLET_DURATIONS
        ]
        if not cands:
            return None
        best = min(cands, key=lambda d: abs(d - value))
        if abs(best - value) > 1e-6:
            return None
        return best
