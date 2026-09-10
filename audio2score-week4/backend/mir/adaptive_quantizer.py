"""Adaptive notation quantizer.

Performance MIDI stays untouched. This module builds a derived notation
representation from copies of the transcribed events:

    Performance notes
      → rhythmic analysis
      → meter / beat context
      → candidate grid generation
      → adaptive quantization
      → chord / voice consistency
      → duration / rest cleanup
      → notation validation
      → notation events

Never write quantized onsets or durations back onto the raw event list.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from mir.models import MeterHypothesis, staff_for_hand
from mir.pipeline_config import QuantizationMode
from mir.types import MusicalEvent, copy_event

# Named durations used for notation. 32nds (0.125) are not a default unit.
BINARY_DURATIONS = (4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25)
TUPLET_DURATIONS = (2.0 / 3.0, 1.0 / 3.0, 1.0 / 6.0)
SIMPLE_DURATIONS = {4.0, 2.0, 1.0, 0.5, 0.25}
DOTTED_DURATIONS = {3.0, 1.5, 0.75, 0.375}

BINARY_GRIDS = (1.0, 0.5, 0.25)
TRIPLET_GRID = 1.0 / 3.0
EIGHTH_TRIPLET_GRID = 1.0 / 6.0


@dataclass
class QuantizationContext:
    meter: MeterHypothesis
    mql: float
    mode: QuantizationMode
    raw_events: list[MusicalEvent]
    analysis: "RhythmicAnalysis"
    chord_window: float = 0.08
    absorb_rest: float = 0.12
    max_timing_error: float = 0.18
    barline_pull: float = 0.125
    pattern_lock: float = 0.14
    complexity_weight: float = 0.35
    tuplet_weight: float = 0.55
    rest_weight: float = 0.7
    tie_weight: float = 0.2


@dataclass
class RhythmicCandidate:
    grid: float
    kind: str
    score: float
    reason: str = ""


@dataclass
class ChordCluster:
    indices: list[int]
    raw_onset: float
    quantized_onset: float = 0.0
    measure_idx: int = 0


@dataclass
class RhythmicAnalysis:
    unique_onsets: list[float] = field(default_factory=list)
    iois: list[float] = field(default_factory=list)
    pattern: str = "mixed"
    pattern_grid: float = 0.5
    triplet_groups: int = 0
    triplet_evidence: float = 0.0
    clusters: list[ChordCluster] = field(default_factory=list)


@dataclass
class QuantizationDecision:
    note_id: str
    pitch: int
    raw_start: float
    quantized_start: float
    raw_duration: float
    quantized_duration: float
    grid: float | None
    selected_grid: float | None
    timing_error: float
    hand: str
    voice: int
    staff: int
    cost: float
    reason: str
    measure: int

    def to_dict(self) -> dict:
        return {
            "note_id": self.note_id,
            "pitch": self.pitch,
            "raw_start": self.raw_start,
            "quantized_start": self.quantized_start,
            "raw_duration": self.raw_duration,
            "quantized_duration": self.quantized_duration,
            "grid": self.grid,
            "selected_grid": self.selected_grid,
            "timing_error": self.timing_error,
            "hand": self.hand,
            "voice": self.voice,
            "staff": self.staff,
            "cost": self.cost,
            "reason": self.reason,
            "measure": self.measure,
        }


@dataclass
class QuantizationReport:
    decisions: list[dict]
    summary: dict
    raw_events: list[MusicalEvent]
    notation_events: list[MusicalEvent]
    selected_grids: dict[int, float]
    analysis: RhythmicAnalysis
    engine: str = "adaptive"


def quantize_notation(
    events: list[MusicalEvent],
    meter: MeterHypothesis,
    *,
    config=None,
    mode: QuantizationMode = QuantizationMode.ADAPTIVE,
) -> tuple[list[MusicalEvent], list[dict], QuantizationReport]:
    """Return notation copies. ``events`` is treated as read-only raw input."""
    from mir.quantizer import QuantizerConfig, measure_index_for_onset, summarize_quantization

    cfg = config or QuantizerConfig()
    raw = [copy_event(ev) for ev in events]
    if not raw:
        empty = QuantizationReport(
            decisions=[],
            summary={
                "raw_events": 0,
                "quantized_events": 0,
                "events_changed": 0,
                "events_removed": 0,
                "average_onset_displacement": 0.0,
                "average_duration_displacement": 0.0,
                "triplet_decisions": 0,
                "removed_events": [],
                "engine": "adaptive",
            },
            raw_events=[],
            notation_events=[],
            selected_grids={},
            analysis=RhythmicAnalysis(),
        )
        return [], [], empty

    analysis = analyze_rhythm(
        raw, meter, chord_window=getattr(cfg, "chord_window_beats", 0.08)
    )
    ctx = QuantizationContext(
        meter=meter,
        mql=float(meter.measure_quarter_length),
        mode=mode,
        raw_events=raw,
        analysis=analysis,
        chord_window=getattr(cfg, "chord_window_beats", 0.08),
        absorb_rest=cfg.absorb_rest_ql,
        max_timing_error=cfg.max_timing_error,
        barline_pull=cfg.barline_pull_beats,
        complexity_weight=cfg.complexity_weight,
        tuplet_weight=cfg.tuplet_weight,
        rest_weight=cfg.rest_weight,
        tie_weight=cfg.tie_weight,
    )

    selected_grids = select_measure_grids(ctx)
    snapped = snap_onsets(ctx, selected_grids)
    snapped = align_chords(ctx, snapped, selected_grids)
    snapped = quantize_durations(ctx, snapped, selected_grids)
    snapped = cleanup_rests_and_durations(ctx, snapped)
    snapped, decisions = validate_notation(ctx, snapped, selected_grids)

    from mir.quantizer import MeasureQuantizer

    if len(snapped) < len(raw):
        snapped, decisions = MeasureQuantizer._restore_missing(raw, snapped, decisions)

    summary = summarize_quantization(raw, snapped, decisions)
    summary["engine"] = "adaptive"
    summary["pattern"] = analysis.pattern
    summary["triplet_evidence"] = analysis.triplet_evidence
    report = QuantizationReport(
        decisions=decisions,
        summary=summary,
        raw_events=raw,
        notation_events=list(snapped),
        selected_grids=selected_grids,
        analysis=analysis,
    )
    return snapped, decisions, report


def analyze_rhythm(
    events: list[MusicalEvent],
    meter: MeterHypothesis,
    *,
    chord_window: float = 0.08,
) -> RhythmicAnalysis:
    ordered = sorted(range(len(events)), key=lambda i: (events[i].start_beat, events[i].pitch))
    clusters: list[ChordCluster] = []
    used: set[int] = set()
    for i in ordered:
        if i in used:
            continue
        members = [i]
        used.add(i)
        seed = events[i].start_beat
        for j in ordered:
            if j in used:
                continue
            if abs(events[j].start_beat - seed) <= chord_window:
                members.append(j)
                used.add(j)
                seed = sum(events[k].start_beat for k in members) / len(members)
        onset = sum(events[k].start_beat for k in members) / len(members)
        clusters.append(ChordCluster(indices=members, raw_onset=onset))

    onsets = [c.raw_onset for c in clusters]
    iois = [b - a for a, b in zip(onsets, onsets[1:]) if b - a > 1e-6]
    pattern, pattern_grid = _detect_pattern(iois, onsets)
    groups, evidence = _triplet_evidence(onsets)
    if pattern == "triplets":
        evidence = max(evidence, 0.7)
        pattern_grid = TRIPLET_GRID
    return RhythmicAnalysis(
        unique_onsets=onsets,
        iois=iois,
        pattern=pattern,
        pattern_grid=pattern_grid,
        triplet_groups=groups,
        triplet_evidence=evidence,
        clusters=clusters,
    )


def _nearest(value: float, candidates: tuple[float, ...]) -> float:
    return min(candidates, key=lambda c: abs(c - value))


def _detect_pattern(iois: list[float], onsets: list[float]) -> tuple[str, float]:
    if not iois:
        return "quarters", 1.0
    named = [_nearest(i, BINARY_DURATIONS + TUPLET_DURATIONS) for i in iois]
    counts = Counter(round(n, 6) for n in named)
    total = len(named)
    eighths = counts.get(0.5, 0)
    sixteenths = counts.get(0.25, 0)
    quarters = counts.get(1.0, 0)
    dotted = counts.get(0.75, 0)
    triplets = counts.get(round(1.0 / 3.0, 6), 0) + counts.get(round(2.0 / 3.0, 6), 0)

    if triplets / total >= 0.45 and triplets >= 2:
        return "triplets", TRIPLET_GRID
    if dotted / total >= 0.25 and sixteenths / total >= 0.2:
        return "dotted", 0.25
    if sixteenths / total >= 0.35 and sixteenths >= 2:
        return "sixteenths", 0.25
    if eighths / total >= 0.5:
        return "eighths", 0.5
    if quarters / total >= 0.5:
        return "quarters", 1.0
    # Off-eighth 16th density from absolute onsets.
    off_eighth = 0
    for o in onsets:
        if abs((o / 0.5) - round(o / 0.5)) > 0.12:
            if abs((o / 0.25) - round(o / 0.25)) < 0.08:
                off_eighth += 1
    if off_eighth >= 2:
        return "sixteenths", 0.25
    return "eighths", 0.5


def _triplet_evidence(onsets: list[float]) -> tuple[int, float]:
    if len(onsets) < 3:
        return 0, 0.0
    groups = 0
    last_beat = int(math.floor(max(onsets))) + 1
    for beat in range(last_beat + 1):
        local = sorted(o - beat for o in onsets if beat - 1e-6 <= o < beat + 1.0 - 1e-6)
        unique: list[float] = []
        for rel in local:
            if not unique or abs(rel - unique[-1]) > 0.06:
                unique.append(rel)
        if len(unique) < 3:
            continue
        expected = (0.0, 1.0 / 3.0, 2.0 / 3.0)
        trip_err = 0.0
        bin_err = 0.0
        for rel in unique[:3]:
            trip_err += min(abs(rel - t) for t in expected)
            bin_err += min(abs(rel - b) for b in (0.0, 0.25, 0.5, 0.75, 1.0))
        trip_err /= 3
        bin_err /= 3
        if trip_err + 0.02 < bin_err * 0.75 and trip_err < 0.08:
            groups += 1
    evidence = 0.0
    if groups:
        evidence = min(1.0, 0.4 + 0.3 * groups)
    return groups, evidence


def select_measure_grids(ctx: QuantizationContext) -> dict[int, float]:
    mql = ctx.mql
    grids: dict[int, float] = {}
    by_measure: dict[int, list[float]] = {}
    from mir.quantizer import measure_index_for_onset

    for onset in ctx.analysis.unique_onsets:
        idx = measure_index_for_onset(onset, mql, pull_beats=ctx.barline_pull)
        by_measure.setdefault(idx, []).append(onset - idx * mql)

    for idx, rels in by_measure.items():
        candidates = generate_candidates(ctx, rels)
        best = min(candidates, key=lambda c: c.score)
        grids[idx] = best.grid
    return grids


def generate_candidates(
    ctx: QuantizationContext, rel_onsets: list[float]
) -> list[RhythmicCandidate]:
    onsets = rel_onsets or [0.0]
    cands: list[RhythmicCandidate] = []
    binary = BINARY_GRIDS if ctx.mode != QuantizationMode.STRICT_GRID else (0.25,)
    if ctx.mode == QuantizationMode.STRICT_GRID:
        binary = (0.25,)
    elif ctx.analysis.pattern == "quarters":
        binary = (1.0, 0.5, 0.25)
    elif ctx.analysis.pattern == "eighths":
        binary = (0.5, 0.25)
    elif ctx.analysis.pattern == "triplets":
        binary = (0.25, 0.5)
    elif ctx.analysis.pattern == "sixteenths":
        binary = (0.25, 0.5)
    else:
        binary = (0.5, 0.25, 1.0)

    for grid in binary:
        cands.append(
            RhythmicCandidate(
                grid=grid,
                kind="binary",
                score=_score_grid(ctx, onsets, grid, triplet=False),
                reason=f"binary_{grid}",
            )
        )

    allow_triplet = ctx.analysis.triplet_evidence >= 0.45 and ctx.analysis.triplet_groups >= 1
    if ctx.mode == QuantizationMode.STRICT_GRID:
        allow_triplet = False
    if allow_triplet:
        cands.append(
            RhythmicCandidate(
                grid=TRIPLET_GRID,
                kind="triplet",
                score=_score_grid(ctx, onsets, TRIPLET_GRID, triplet=True),
                reason="triplet_third",
            )
        )
    return cands or [
        RhythmicCandidate(grid=0.5, kind="binary", score=0.0, reason="fallback_eighth")
    ]


def _score_grid(
    ctx: QuantizationContext,
    rel_onsets: list[float],
    grid: float,
    *,
    triplet: bool,
) -> float:
    errors = []
    for rel in rel_onsets:
        snapped = round(rel / grid) * grid
        errors.append(abs(snapped - rel))
    mean_err = sum(errors) / len(errors)
    max_err = max(errors)
    complexity = {1.0: 0.0, 0.5: 0.04, 0.25: 0.22, TRIPLET_GRID: 0.5}.get(grid, 0.3)
    unused = 0.0
    if grid == 0.25:
        coarse = [abs(round(r / 0.5) * 0.5 - r) for r in rel_onsets]
        if sum(coarse) / len(coarse) < 0.06:
            unused = 0.45
        if ctx.analysis.pattern == "eighths" and ctx.analysis.pattern_grid == 0.5:
            unused += 0.25
    if grid == 0.5 and ctx.analysis.pattern == "sixteenths":
        unused += 0.4
    if grid == 1.0:
        coarse = [abs(round(r / 1.0) * 1.0 - r) for r in rel_onsets]
        if sum(coarse) / len(coarse) > 0.12:
            unused += 0.5

    tuplet_pen = 0.0
    if triplet:
        binary_err = [
            abs(round(r / 0.25) * 0.25 - r) for r in rel_onsets
        ]
        mean_bin = sum(binary_err) / len(binary_err)
        if ctx.analysis.triplet_evidence < 0.45:
            tuplet_pen = 3.0
        elif mean_err + 0.01 >= mean_bin:
            tuplet_pen = 1.4
        else:
            tuplet_pen = 0.08
        if ctx.analysis.pattern in ("eighths", "sixteenths", "quarters") and ctx.analysis.triplet_groups < 1:
            tuplet_pen += 2.0

    overtime = 0.0
    if max_err > ctx.max_timing_error:
        overtime = 8.0 * (max_err - ctx.max_timing_error)

    pattern_term = 0.0
    pattern = ctx.analysis.pattern
    if pattern == "triplets" and ctx.analysis.triplet_evidence >= 0.45:
        if triplet:
            pattern_term = -0.45
            tuplet_pen = min(tuplet_pen, 0.02)
            complexity = min(complexity, 0.05)
        else:
            pattern_term = 0.7 + max(0.0, max_err - 0.08) * 4.0
    elif triplet and pattern in ("eighths", "sixteenths", "quarters"):
        pattern_term = 1.6

    return (
        mean_err
        + ctx.complexity_weight * complexity
        + unused
        + ctx.tuplet_weight * tuplet_pen
        + overtime
        + pattern_term
    )


def _grid_for_measure(selected: dict[int, float], idx: int, ctx: QuantizationContext) -> float:
    if idx in selected:
        return selected[idx]
    return ctx.analysis.pattern_grid or 0.5


def snap_onsets(
    ctx: QuantizationContext, selected_grids: dict[int, float]
) -> list[MusicalEvent]:
    from mir.quantizer import measure_index_for_onset

    mql = ctx.mql
    notation = [copy_event(ev) for ev in ctx.raw_events]
    for cluster in ctx.analysis.clusters:
        idx = measure_index_for_onset(
            cluster.raw_onset, mql, pull_beats=ctx.barline_pull
        )
        grid = _grid_for_measure(selected_grids, idx, ctx)
        if (
            ctx.mode != QuantizationMode.STRICT_GRID
            and ctx.analysis.pattern == "triplets"
            and ctx.analysis.triplet_evidence >= 0.45
        ):
            grid = TRIPLET_GRID
        # Pattern lock: stay on the repeated grid when the error is small.
        pattern_grid = ctx.analysis.pattern_grid
        if (
            ctx.mode != QuantizationMode.STRICT_GRID
            and ctx.analysis.pattern in ("eighths", "quarters")
            and not (ctx.analysis.triplet_evidence >= 0.45 and grid == TRIPLET_GRID)
        ):
            rel = cluster.raw_onset - idx * mql
            pattern_err = abs(round(rel / pattern_grid) * pattern_grid - rel)
            fine_err = abs(round(rel / grid) * grid - rel)
            if pattern_err <= ctx.pattern_lock and pattern_err <= pattern_grid * 0.35:
                if not (grid < pattern_grid and fine_err + 0.04 < pattern_err):
                    grid = pattern_grid
        start = _snap_in_measure(
            cluster.raw_onset, idx, mql, grid, ctx.barline_pull
        )
        cluster.quantized_onset = start
        cluster.measure_idx = idx
        for i in cluster.indices:
            notation[i] = copy_event(notation[i], start_beat=start)
    return notation


def _snap_in_measure(
    raw_start: float,
    measure_idx: int,
    mql: float,
    grid: float,
    pull_beats: float,
) -> float:
    measure_start = measure_idx * mql
    rel = raw_start - measure_start
    snapped_rel = round(rel / grid) * grid if grid > 0 else 0.0
    snapped_rel = max(0.0, snapped_rel)
    if snapped_rel >= mql - 1e-9:
        # Early downbeat already assigned to this next bar should land on 0.
        # A true last-grid note (e.g. 3.75 in 4/4) stays inside.
        if (mql - rel) <= pull_beats + 1e-12:
            return measure_start + mql
        snapped_rel = max(0.0, mql - grid)
    return measure_start + snapped_rel


def align_chords(
    ctx: QuantizationContext,
    events: list[MusicalEvent],
    selected_grids: dict[int, float],
) -> list[MusicalEvent]:
    """Force raw chord members onto one quantized onset."""
    out = [copy_event(ev) for ev in events]
    for cluster in ctx.analysis.clusters:
        if len(cluster.indices) < 2:
            continue
        starts = [out[i].start_beat for i in cluster.indices]
        # Prefer the already-snapped cluster onset; if members drifted, vote.
        votes = Counter(round(s, 6) for s in starts)
        agreed, _ = votes.most_common(1)[0]
        target = cluster.quantized_onset if abs(cluster.quantized_onset - agreed) < 0.26 else agreed
        for i in cluster.indices:
            out[i] = copy_event(out[i], start_beat=target)
    return out


def _duration_candidates(grid: float, tuplet_ok: bool) -> tuple[float, ...]:
    cands = list(BINARY_DURATIONS)
    if tuplet_ok:
        cands.extend(TUPLET_DURATIONS)
    if grid <= 0.25 + 1e-9 and 0.125 not in cands:
        pass
    return tuple(sorted(set(cands), reverse=True))


def quantize_durations(
    ctx: QuantizationContext,
    events: list[MusicalEvent],
    selected_grids: dict[int, float],
) -> list[MusicalEvent]:
    from mir.quantizer import measure_index_for_onset

    out = [copy_event(ev) for ev in events]
    grouped: dict[tuple[int, int], list[int]] = {}
    for i, ev in enumerate(out):
        key = (staff_for_hand(ev.hand, ev.pitch), int(ev.voice))
        grouped.setdefault(key, []).append(i)

    for indices in grouped.values():
        indices.sort(key=lambda i: (out[i].start_beat, out[i].pitch))
        for pos, i in enumerate(indices):
            ev = out[i]
            raw = ctx.raw_events[i]
            nxt = _next_onset(out, indices, pos, ev.start_beat)
            remaining = 8.0
            if nxt is not None:
                remaining = max(0.0, nxt - ev.start_beat)
            measure_idx = measure_index_for_onset(
                ev.start_beat, ctx.mql, pull_beats=ctx.barline_pull
            )
            measure_end = (measure_idx + 1) * ctx.mql
            orig_end = raw.start_beat + raw.duration_beats
            orig_crosses = orig_end > measure_end + 1e-6
            if not orig_crosses:
                remaining = min(remaining, max(0.0, measure_end - ev.start_beat))
            grid = _grid_for_measure(selected_grids, measure_idx, ctx)
            tuplet_ok = abs(grid - TRIPLET_GRID) < 1e-6
            duration = _choose_duration(
                ctx,
                target=raw.duration_beats,
                remaining=remaining,
                grid=grid,
                tuplet_ok=tuplet_ok,
                orig_crosses=orig_crosses,
                measure_remaining=max(0.0, measure_end - ev.start_beat),
            )
            out[i] = copy_event(ev, duration_beats=duration)
    return out


def _next_onset(
    events: list[MusicalEvent], indices: list[int], pos: int, start: float
) -> float | None:
    for j in indices[pos + 1 :]:
        if events[j].start_beat > start + 1e-8:
            return events[j].start_beat
    return None


def _choose_duration(
    ctx: QuantizationContext,
    *,
    target: float,
    remaining: float,
    grid: float,
    tuplet_ok: bool,
    orig_crosses: bool,
    measure_remaining: float,
) -> float:
    if remaining <= 1e-9:
        return max(grid if grid > 0 else 0.25, 0.25) if tuplet_ok is False else max(grid, 1.0 / 6.0)
    cands = _duration_candidates(grid, tuplet_ok)
    min_d = TRIPLET_GRID if tuplet_ok else 0.25
    best_d = min_d
    best_cost = float("inf")
    fill_target = target
    if 0 < remaining - target < ctx.absorb_rest:
        fill_target = remaining
    for d in cands:
        if d > remaining + 1e-9:
            continue
        leftover = remaining - d
        actual = d
        rest_pen = 0.0
        if 0 < leftover < ctx.absorb_rest:
            if leftover <= ctx.absorb_rest:
                actual = remaining
                leftover = 0.0
                # Prefer a named duration when remaining itself is named.
                named = min(cands, key=lambda x: abs(x - remaining))
                if abs(named - remaining) < 1e-6:
                    actual = named
                elif abs(named - remaining) <= 0.04 and named <= remaining + 1e-9:
                    actual = named
        if 0 < leftover < 0.25:
            rest_pen = 1.0
        complexity = 0.0
        if d in SIMPLE_DURATIONS:
            complexity = 0.0
        elif d in DOTTED_DURATIONS:
            complexity = 0.18
        else:
            complexity = 1.0
        tuplet_pen = 0.0
        if d in TUPLET_DURATIONS:
            simple_err = min(abs(s - fill_target) for s in SIMPLE_DURATIONS | DOTTED_DURATIONS)
            tuplet_pen = 1.0 if simple_err <= 0.08 else 0.05
            if not tuplet_ok:
                continue
        crosses = actual > measure_remaining + 1e-6
        tie_pen = 1.0 if crosses and not orig_crosses else 0.0
        timing = abs(d - fill_target)
        cost = (
            timing
            + ctx.complexity_weight * complexity
            + ctx.tuplet_weight * tuplet_pen
            + ctx.tie_weight * tie_pen
            + ctx.rest_weight * rest_pen
        )
        if cost < best_cost:
            best_cost = cost
            best_d = actual
    if best_cost == float("inf"):
        best_d = max(min_d, min(remaining, fill_target if fill_target > 0 else min_d))
    return max(min_d, best_d)


def cleanup_rests_and_durations(
    ctx: QuantizationContext, events: list[MusicalEvent]
) -> list[MusicalEvent]:
    """Absorb pathological tiny gaps into the preceding note when on-grid."""
    out = [copy_event(ev) for ev in events]
    grouped: dict[tuple[int, int], list[int]] = {}
    for i, ev in enumerate(out):
        key = (staff_for_hand(ev.hand, ev.pitch), int(ev.voice))
        grouped.setdefault(key, []).append(i)
    for indices in grouped.values():
        indices.sort(key=lambda i: (out[i].start_beat, out[i].pitch))
        for pos, i in enumerate(indices):
            nxt = _next_onset(out, indices, pos, out[i].start_beat)
            if nxt is None:
                continue
            end = out[i].start_beat + out[i].duration_beats
            gap = nxt - end
            if 0 < gap < ctx.absorb_rest:
                out[i] = copy_event(
                    out[i], duration_beats=max(out[i].duration_beats, nxt - out[i].start_beat)
                )
            elif gap < -1e-6:
                # Do not overlap the next onset.
                out[i] = copy_event(
                    out[i],
                    duration_beats=max(0.25, nxt - out[i].start_beat)
                    if abs(_grid_hint(out[i].duration_beats) - TRIPLET_GRID) > 1e-6
                    else max(1.0 / 6.0, nxt - out[i].start_beat),
                )
    return out


def _grid_hint(duration: float) -> float:
    return duration


def validate_notation(
    ctx: QuantizationContext,
    events: list[MusicalEvent],
    selected_grids: dict[int, float],
) -> tuple[list[MusicalEvent], list[dict]]:
    from mir.quantizer import measure_index_for_onset

    out = [copy_event(ev) for ev in events]
    decisions: list[dict] = []
    for i, ev in enumerate(out):
        raw = ctx.raw_events[i]
        idx = measure_index_for_onset(ev.start_beat, ctx.mql, pull_beats=ctx.barline_pull)
        grid = _grid_for_measure(selected_grids, idx, ctx)
        # Keep genuine cross-bar sustains; do not invent them.
        measure_end = (idx + 1) * ctx.mql
        orig_end = raw.start_beat + raw.duration_beats
        orig_crosses = orig_end > measure_end + 1e-6
        if not orig_crosses and ev.start_beat + ev.duration_beats > measure_end + 1e-6:
            out[i] = copy_event(
                ev, duration_beats=max(0.25, measure_end - ev.start_beat)
            )
            ev = out[i]
        reason = "adaptive"
        if abs(grid - TRIPLET_GRID) < 1e-6:
            reason = "adaptive_triplet"
        elif ctx.analysis.pattern == "eighths":
            reason = "adaptive_pattern_eighths"
        elif ctx.analysis.pattern == "sixteenths":
            reason = "adaptive_pattern_sixteenths"
        staff = staff_for_hand(ev.hand, ev.pitch)
        decisions.append(
            QuantizationDecision(
                note_id=ev.note_id,
                pitch=ev.pitch,
                raw_start=raw.start_beat,
                quantized_start=ev.start_beat,
                raw_duration=raw.duration_beats,
                quantized_duration=ev.duration_beats,
                grid=grid,
                selected_grid=grid,
                timing_error=abs(ev.start_beat - raw.start_beat),
                hand=ev.hand.value,
                voice=int(ev.voice),
                staff=staff,
                cost=abs(ev.start_beat - raw.start_beat)
                + abs(ev.duration_beats - raw.duration_beats),
                reason=reason,
                measure=idx + 1,
            ).to_dict()
        )
    out.sort(key=lambda e: (e.start_beat, e.pitch, e.voice))
    return out, decisions
