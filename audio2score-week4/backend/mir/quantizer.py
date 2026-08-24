"""Measure-aware, voice-aware quantization.

Does not snap every note independently onto a global grid.
"""

from __future__ import annotations

from dataclasses import dataclass

from mir.models import MeterHypothesis
from mir.types import MusicalEvent, copy_event


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

SIMPLE_DURATIONS = {4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25}


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

        grids = self._grids_for(meter)
        best_events = None
        best_cost = float("inf")
        best_grid = grids[0]
        best_decisions: list[dict] = []

        for grid in grids:
            q_events, decisions, cost = self._quantize_with_grid(events, meter, grid)
            if cost < best_cost:
                best_cost = cost
                best_events = q_events
                best_grid = grid
                best_decisions = decisions

        for d in best_decisions:
            d["selected_grid"] = best_grid
        return best_events or events, best_decisions

    def _grids_for(self, meter: MeterHypothesis) -> list[float]:
        if meter.time_signature in ("6/8", "12/8"):
            return [0.5, 0.25]
        return [0.25, 0.5, 1.0 / 3.0]

    def _quantize_with_grid(
        self,
        events: list[MusicalEvent],
        meter: MeterHypothesis,
        grid: float,
    ) -> tuple[list[MusicalEvent], list[dict], float]:
        cfg = self.config
        mql = meter.measure_quarter_length
        grouped: dict[tuple, list[MusicalEvent]] = {}
        for ev in events:
            grouped.setdefault((ev.hand, ev.voice), []).append(ev)

        out: list[MusicalEvent] = []
        decisions: list[dict] = []
        total_cost = 0.0
        tuplet_used = abs(grid - 1.0 / 3.0) < 1e-6

        for key, group in grouped.items():
            ordered = sorted(group, key=lambda e: (e.start_beat, e.pitch))
            i = 0
            while i < len(ordered):
                ev = ordered[i]
                measure_start = (ev.start_beat // mql) * mql
                rel = ev.start_beat - measure_start
                snapped_rel = round(rel / grid) * grid
                snapped_rel = max(0.0, min(mql - grid, snapped_rel))
                start = measure_start + snapped_rel
                timing_err = abs(start - ev.start_beat)

                next_start = None
                for nxt in ordered[i + 1 :]:
                    if nxt.start_beat > ev.start_beat + 1e-8:
                        next_start = nxt.start_beat
                        break
                remaining = 8.0  # do not clip to the bar; the planner ties across barlines
                if next_start is not None:
                    gap = next_start - start
                    remaining = max(grid, gap)
                    if 0 < (next_start - (start + ev.duration_beats)) < cfg.absorb_rest_ql:
                        remaining = next_start - start

                target = min(max(ev.duration_beats, grid), remaining)
                duration = self._pick_duration(target, remaining, tuplet_ok=tuplet_used)
                complexity = 0.0 if duration in SIMPLE_DURATIONS else 1.0
                rest_pen = 0.0
                leftover = remaining - duration
                if 0 < leftover < cfg.absorb_rest_ql:
                    duration = remaining
                    leftover = 0.0
                    rest_pen = 0.0
                elif 0 < leftover < 0.25:
                    rest_pen = 1.0

                cost = (
                    timing_err
                    + cfg.complexity_weight * complexity
                    + cfg.tuplet_weight * (1.0 if tuplet_used else 0.0)
                    + cfg.rest_weight * rest_pen
                )
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
                        "voice": ev.voice,
                    }
                )
                out.append(
                    copy_event(
                        ev,
                        start_beat=start,
                        duration_beats=max(grid, duration),
                    )
                )
                i += 1

        if tuplet_used:
            # If straight 16ths already fit well, penalize the triplet grid.
            straight_err = 0.0
            for ev in events:
                rel = ev.start_beat % mql
                g = rel / 0.25
                straight_err += abs(g - round(g))
            if straight_err / max(len(events), 1) < 0.12:
                total_cost += 4.0
        return out, decisions, total_cost

    def _pick_duration(
        self, target: float, remaining: float, tuplet_ok: bool
    ) -> float:
        cands = [
            d
            for d in DURATION_CANDIDATES
            if d <= remaining + 1e-9 and (tuplet_ok or d not in (1.0 / 3.0, 2.0 / 3.0))
        ]
        if not cands:
            return min(remaining, 0.25) if remaining > 0 else 0.25
        best = min(
            cands,
            key=lambda d: abs(d - target)
            + (0.12 if d not in SIMPLE_DURATIONS else 0.0),
        )
        return best
