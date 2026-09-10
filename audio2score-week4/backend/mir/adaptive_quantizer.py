"""Adaptive notation quantizer.

Works only on copies of transcribed events. Raw performance MIDI stays
untouched. One scoring model picks a rhythmic interpretation:

    TOTAL COST = timing error
               + duration error
               + notation complexity
               + rest penalty
               + triplet penalty
               + inconsistency penalty
               + boundary penalty
               + movement penalty

Hard constraints (never scored away):

* note count / ids / pitches / velocities preserved
* duration > 0 and duration <= available space
* no invented barline crossings
* no same-voice overlaps
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from mir.models import MeterHypothesis, staff_for_hand
from mir.pipeline_config import QuantizationMode
from mir.types import MusicalEvent, copy_event

EPS = 1e-9
MIN_DURATION = 1e-4
MAX_ONSET_MOVE = 0.22
TINY_REST = 0.12

BINARY_DURATIONS = (4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25)
TUPLET_DURATIONS = (2.0 / 3.0, 1.0 / 3.0, 1.0 / 6.0)
SIMPLE_DURATIONS = {4.0, 2.0, 1.0, 0.5, 0.25}
DOTTED_DURATIONS = {3.0, 1.5, 0.75, 0.375}

TRIPLET_GRID = 1.0 / 3.0
EIGHTH_TRIPLET_GRID = 1.0 / 6.0

COMPLEXITY = {
    1.5: 0.08,
    1.0: 0.0,
    0.5: 0.05,
    0.25: 0.2,
    TRIPLET_GRID: 0.35,
    EIGHTH_TRIPLET_GRID: 0.45,
}


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
    max_onset_move: float = MAX_ONSET_MOVE
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
    preserved: bool = False


@dataclass
class RhythmicAnalysis:
    unique_onsets: list[float] = field(default_factory=list)
    iois: list[float] = field(default_factory=list)
    pattern: str = "mixed"
    pattern_grid: float = 0.5
    triplet_groups: int = 0
    triplet_evidence: float = 0.0
    clusters: list[ChordCluster] = field(default_factory=list)
    compound: bool = False


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
    preserved_timing: bool = False

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
            "preserved_timing": self.preserved_timing,
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
    from mir.quantizer import QuantizerConfig, summarize_quantization

    cfg = config or QuantizerConfig()
    raw = [copy_event(ev) for ev in events]
    if not raw:
        empty = QuantizationReport(
            decisions=[],
            summary=_empty_quality_summary(),
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
        mql=float(meter.measure_quarter_length) or 4.0,
        mode=mode,
        raw_events=raw,
        analysis=analysis,
        chord_window=getattr(cfg, "chord_window_beats", 0.08),
        absorb_rest=cfg.absorb_rest_ql,
        max_timing_error=cfg.max_timing_error,
        barline_pull=cfg.barline_pull_beats,
        max_onset_move=float(getattr(cfg, "max_onset_move", MAX_ONSET_MOVE)),
        complexity_weight=cfg.complexity_weight,
        tuplet_weight=cfg.tuplet_weight,
        rest_weight=cfg.rest_weight,
        tie_weight=cfg.tie_weight,
    )

    selected_grids = select_measure_grids(ctx)
    snapped = snap_onsets(ctx, selected_grids)
    snapped = align_chords(ctx, snapped)
    snapped = resolve_onset_collisions(ctx, snapped)
    snapped = quantize_durations(ctx, snapped, selected_grids)
    snapped = clamp_voice_overlaps(snapped)
    snapped, decisions = validate_notation(ctx, snapped, selected_grids)
    snapped = restore_identity(raw, snapped)
    snapped.sort(key=lambda e: (e.start_beat, e.pitch, e.voice))

    summary = summarize_quantization(raw, snapped, decisions)
    summary.update(quality_metrics(raw, snapped, analysis, decisions))
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


def _compound_meter(meter: MeterHypothesis) -> bool:
    ts = (meter.time_signature or "").strip()
    if ts in {"6/8", "9/8", "12/8"}:
        return True
    return int(meter.denominator) == 8 and int(meter.numerator) % 3 == 0


def _is_vertical(a: MusicalEvent, b: MusicalEvent, window: float) -> bool:
    """True when two notes are one vertical event, not successive attacks."""
    if a.pitch == b.pitch:
        return False
    if abs(a.start_beat - b.start_beat) > window + EPS:
        return False
    a_end = a.start_beat + max(a.duration_beats, MIN_DURATION)
    b_end = b.start_beat + max(b.duration_beats, MIN_DURATION)
    overlap = min(a_end, b_end) - max(a.start_beat, b.start_beat)
    short = min(max(a.duration_beats, MIN_DURATION), max(b.duration_beats, MIN_DURATION))
    return overlap >= 0.45 * short


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
        seed = events[i]
        for j in ordered:
            if j in used:
                continue
            if not _is_vertical(seed, events[j], chord_window):
                continue
            if any(events[j].pitch == events[k].pitch for k in members):
                continue
            members.append(j)
            used.add(j)
        onset = sum(events[k].start_beat for k in members) / len(members)
        clusters.append(ChordCluster(indices=members, raw_onset=onset))

    onsets = [c.raw_onset for c in clusters]
    iois = [b - a for a, b in zip(onsets, onsets[1:]) if b - a > EPS]
    compound = _compound_meter(meter)
    pattern, pattern_grid = _detect_pattern(iois, onsets, compound=compound)
    groups, evidence = _triplet_evidence(onsets, meter)
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
        compound=compound,
    )


def _nearest(value: float, candidates: tuple[float, ...]) -> float:
    return min(candidates, key=lambda c: abs(c - value))


def _detect_pattern(
    iois: list[float], onsets: list[float], *, compound: bool
) -> tuple[str, float]:
    if not iois:
        return ("eighths", 0.5) if compound else ("quarters", 1.0)
    named = [_nearest(i, BINARY_DURATIONS + TUPLET_DURATIONS) for i in iois]
    counts = Counter(round(n, 6) for n in named)
    total = max(1, len(named))
    eighths = counts.get(0.5, 0)
    sixteenths = counts.get(0.25, 0)
    quarters = counts.get(1.0, 0)
    dotted = counts.get(0.75, 0) + counts.get(1.5, 0)
    triplets = counts.get(round(TRIPLET_GRID, 6), 0) + counts.get(round(2.0 / 3.0, 6), 0)

    eighth_trips = counts.get(round(EIGHTH_TRIPLET_GRID, 6), 0)
    if not compound and triplets / total >= 0.45 and triplets >= 2:
        return "triplets", TRIPLET_GRID
    if not compound and eighth_trips / total >= 0.45 and eighth_trips >= 3:
        return "triplets", EIGHTH_TRIPLET_GRID
    if dotted / total >= 0.25 and sixteenths / total >= 0.2:
        return "dotted", 0.25
    if sixteenths / total >= 0.35 and sixteenths >= 2:
        return "sixteenths", 0.25
    if eighths / total >= 0.5:
        return "eighths", 0.5
    if not compound and quarters / total >= 0.5:
        return "quarters", 1.0
    off_eighth = 0
    for o in onsets:
        if abs((o / 0.5) - round(o / 0.5)) > 0.12:
            if abs((o / 0.25) - round(o / 0.25)) < 0.08:
                off_eighth += 1
    if off_eighth >= 2:
        return "sixteenths", 0.25
    return "eighths", 0.5


def _triplet_evidence(onsets: list[float], meter: MeterHypothesis) -> tuple[int, float]:
    if _compound_meter(meter) or len(onsets) < 3:
        return 0, 0.0
    groups = 0
    last_beat = int(math.floor(max(onsets))) + 1
    for beat in range(last_beat + 1):
        local = sorted(o - beat for o in onsets if beat - EPS <= o < beat + 1.0 - EPS)
        unique: list[float] = []
        for rel in local:
            if not unique or abs(rel - unique[-1]) > 0.06:
                unique.append(rel)
        if len(unique) < 3:
            continue
        expected = (0.0, TRIPLET_GRID, 2.0 / 3.0)
        trip_err = 0.0
        bin_err = 0.0
        for rel in unique[:3]:
            trip_err += min(abs(rel - t) for t in expected)
            bin_err += min(abs(rel - b) for b in (0.0, 0.25, 0.5, 0.75, 1.0))
        trip_err /= 3
        bin_err /= 3
        eighth_expected = (0.0, EIGHTH_TRIPLET_GRID, 2.0 / 6.0, 0.5, 4.0 / 6.0, 5.0 / 6.0)
        eighth_err = 0.0
        for rel in unique[: min(6, len(unique))]:
            eighth_err += min(abs(rel - t) for t in eighth_expected)
        eighth_err /= min(6, len(unique))
        if trip_err + 0.02 < bin_err * 0.75 and trip_err < 0.08:
            groups += 1
        elif len(unique) >= 4 and eighth_err + 0.02 < bin_err * 0.7 and eighth_err < 0.06:
            groups += 1
    evidence = min(1.0, 0.4 + 0.3 * groups) if groups else 0.0
    return groups, evidence


def _binary_grids(ctx: QuantizationContext) -> tuple[float, ...]:
    if ctx.mode == QuantizationMode.STRICT_GRID:
        return (0.25,)
    if ctx.analysis.compound:
        return (0.5, 0.25, 1.5)
    pattern = ctx.analysis.pattern
    if pattern == "quarters":
        return (1.0, 0.5, 0.25)
    if pattern == "eighths":
        return (0.5, 0.25)
    if pattern == "sixteenths":
        return (0.25, 0.5)
    if pattern == "dotted":
        return (0.25, 0.5)
    if pattern == "triplets":
        return (0.25, 0.5)
    return (0.5, 0.25, 1.0)


def interpretation_cost(
    rel_onsets: list[float],
    grid: float,
    *,
    triplet: bool,
    ctx: QuantizationContext,
) -> float:
    """Single cost model used for every rhythmic candidate."""
    if not rel_onsets:
        return 0.0
    errors = [abs(round(rel / grid) * grid - rel) if grid > 0 else abs(rel) for rel in rel_onsets]
    timing = sum(errors) / len(errors)
    max_err = max(errors)
    complexity = COMPLEXITY.get(grid, 0.3)

    unused = 0.0
    if not triplet:
        for coarse in (1.5, 1.0, 0.5):
            if coarse <= grid + EPS:
                continue
            coarse_err = [abs(round(rel / coarse) * coarse - rel) for rel in rel_onsets]
            if sum(coarse_err) / len(coarse_err) < 0.06:
                unused += 0.35

    triplet_pen = 0.0
    if triplet:
        triplet_pen = 0.35
        if ctx.analysis.triplet_groups < 1 or ctx.analysis.triplet_evidence < 0.45:
            triplet_pen += 2.2
        binary_err = [abs(round(rel / 0.25) * 0.25 - rel) for rel in rel_onsets]
        mean_bin = sum(binary_err) / len(binary_err)
        if timing + 0.02 >= mean_bin:
            triplet_pen += 1.0

    inconsistency = 0.0
    pattern = ctx.analysis.pattern
    if pattern == "eighths" and grid == 0.25:
        inconsistency += 0.3
    if pattern == "sixteenths" and grid >= 0.5 - EPS:
        inconsistency += 0.45
    if pattern == "triplets" and not triplet:
        inconsistency += 0.85
    if pattern == "quarters" and grid == 0.25:
        inconsistency += 0.25
    if ctx.analysis.compound and abs(grid - 1.0) < EPS:
        inconsistency += 0.6
    if ctx.analysis.compound and abs(grid - 0.25) < EPS:
        # 6/8 / 12/8 eighth pulse is 0.5; don't reach for sixteenths by default.
        inconsistency += 0.2

    boundary = 0.0
    if max_err > ctx.max_timing_error:
        boundary += 8.0 * (max_err - ctx.max_timing_error)
    movement = 0.0
    if max_err > ctx.max_onset_move:
        movement += 6.0 * (max_err - ctx.max_onset_move)

    return (
        timing
        + ctx.complexity_weight * complexity
        + unused
        + ctx.tuplet_weight * triplet_pen
        + inconsistency
        + boundary
        + movement
    )


def generate_candidates(
    ctx: QuantizationContext, rel_onsets: list[float]
) -> list[RhythmicCandidate]:
    onsets = rel_onsets or [0.0]
    cands: list[RhythmicCandidate] = []
    for grid in _binary_grids(ctx):
        cands.append(
            RhythmicCandidate(
                grid=grid,
                kind="binary",
                score=interpretation_cost(onsets, grid, triplet=False, ctx=ctx),
                reason=f"binary_{grid}",
            )
        )
    allow_triplet = (
        ctx.mode != QuantizationMode.STRICT_GRID
        and not ctx.analysis.compound
        and ctx.analysis.triplet_groups >= 1
        and ctx.analysis.triplet_evidence >= 0.45
        and len(onsets) >= 3
    )
    if allow_triplet:
        best_bin = min(c.score for c in cands) if cands else 0.0
        trip = interpretation_cost(onsets, TRIPLET_GRID, triplet=True, ctx=ctx)
        # Triplets only when they clearly beat every binary reading.
        if trip + 0.08 < best_bin:
            cands.append(
                RhythmicCandidate(
                    grid=TRIPLET_GRID,
                    kind="triplet",
                    score=trip,
                    reason="triplet_third",
                )
            )
        eighth = interpretation_cost(
            onsets, EIGHTH_TRIPLET_GRID, triplet=True, ctx=ctx
        )
        if eighth + 0.16 < best_bin and eighth + 0.06 < trip:
            cands.append(
                RhythmicCandidate(
                    grid=EIGHTH_TRIPLET_GRID,
                    kind="triplet",
                    score=eighth,
                    reason="triplet_sixth",
                )
            )
    return cands or [
        RhythmicCandidate(grid=0.5, kind="binary", score=0.0, reason="fallback_eighth")
    ]


def select_measure_grids(ctx: QuantizationContext) -> dict[int, float]:
    from mir.quantizer import measure_index_for_onset

    by_measure: dict[int, list[float]] = {}
    for onset in ctx.analysis.unique_onsets:
        idx = measure_index_for_onset(onset, ctx.mql, pull_beats=ctx.barline_pull)
        by_measure.setdefault(idx, []).append(onset - idx * ctx.mql)

    global_cands = generate_candidates(ctx, ctx.analysis.unique_onsets)
    global_grid = min(global_cands, key=lambda c: c.score).grid

    grids: dict[int, float] = {}
    for idx, rels in by_measure.items():
        local = generate_candidates(ctx, rels)
        best = min(local, key=lambda c: c.score)
        # Keep the phrase grid unless a measure is clearly better on another grid.
        global_local = interpretation_cost(
            rels,
            global_grid,
            triplet=abs(global_grid - TRIPLET_GRID) < EPS,
            ctx=ctx,
        )
        if best.score + 0.12 < global_local:
            grids[idx] = best.grid
        else:
            grids[idx] = global_grid
    return grids


def _grid_for_measure(selected: dict[int, float], idx: int, ctx: QuantizationContext) -> float:
    if idx in selected:
        return selected[idx]
    return ctx.analysis.pattern_grid or 0.5


def snap_onsets(
    ctx: QuantizationContext, selected_grids: dict[int, float]
) -> list[MusicalEvent]:
    from mir.quantizer import measure_index_for_onset

    notation = [copy_event(ev) for ev in ctx.raw_events]
    for cluster in ctx.analysis.clusters:
        idx = measure_index_for_onset(
            cluster.raw_onset, ctx.mql, pull_beats=ctx.barline_pull
        )
        grid = _grid_for_measure(selected_grids, idx, ctx)
        start = _snap_in_measure(
            cluster.raw_onset, idx, ctx.mql, grid, ctx.barline_pull
        )
        if abs(start - cluster.raw_onset) > ctx.max_onset_move:
            start = cluster.raw_onset
            cluster.preserved = True
        cluster.quantized_onset = start
        cluster.measure_idx = idx
        for i in cluster.indices:
            notation[i] = copy_event(notation[i], start_beat=start)
    return notation


def resolve_onset_collisions(
    ctx: QuantizationContext, events: list[MusicalEvent]
) -> list[MusicalEvent]:
    """Keep distinct attacks from collapsing onto one onset.

    Chord members already share a cluster and may stay simultaneous.
    Separate clusters in the same voice must remain in raw order and must
    not silently merge into a false chord.
    """
    out = [copy_event(ev) for ev in events]
    cluster_of: dict[int, ChordCluster] = {}
    for cluster in ctx.analysis.clusters:
        for i in cluster.indices:
            cluster_of[i] = cluster

    def set_start(cluster: ChordCluster, start: float) -> None:
        start = max(0.0, float(start))
        cluster.quantized_onset = start
        for i in cluster.indices:
            out[i] = copy_event(out[i], start_beat=start)

    grouped: dict[tuple[int, int], list[int]] = {}
    for i, ev in enumerate(out):
        key = (staff_for_hand(ev.hand, ev.pitch), int(ev.voice))
        grouped.setdefault(key, []).append(i)

    for indices in grouped.values():
        ordered = sorted(
            indices, key=lambda i: (ctx.raw_events[i].start_beat, i)
        )
        seen: list[ChordCluster] = []
        used: set[int] = set()
        for i in ordered:
            cluster = cluster_of[i]
            cid = id(cluster)
            if cid in used:
                continue
            used.add(cid)
            if seen:
                prev = seen[-1]
                if cluster.quantized_onset <= prev.quantized_onset + EPS:
                    pulled = prev.quantized_onset - 0.25
                    if (
                        pulled >= -EPS
                        and abs(pulled - prev.raw_onset) <= ctx.max_onset_move + EPS
                    ):
                        set_start(prev, pulled)
                    elif prev.raw_onset < cluster.quantized_onset - EPS:
                        set_start(prev, prev.raw_onset)
                        prev.preserved = True
                    else:
                        set_start(
                            prev, max(0.0, cluster.quantized_onset - MIN_DURATION)
                        )
                    if cluster.quantized_onset <= prev.quantized_onset + EPS:
                        if cluster.raw_onset > prev.quantized_onset + EPS:
                            set_start(cluster, cluster.raw_onset)
                            cluster.preserved = True
                        else:
                            set_start(
                                cluster, prev.quantized_onset + MIN_DURATION
                            )
            seen.append(cluster)
    return out


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
    if snapped_rel >= mql - EPS:
        if (mql - rel) <= pull_beats + 1e-12:
            return measure_start + mql
        snapped_rel = max(0.0, mql - grid)
    return measure_start + snapped_rel


def align_chords(
    ctx: QuantizationContext, events: list[MusicalEvent]
) -> list[MusicalEvent]:
    out = [copy_event(ev) for ev in events]
    for cluster in ctx.analysis.clusters:
        if len(cluster.indices) < 2:
            continue
        target = cluster.quantized_onset
        for i in cluster.indices:
            out[i] = copy_event(out[i], start_beat=target)
    return out


def _duration_candidates(tuplet_ok: bool) -> tuple[float, ...]:
    cands = list(BINARY_DURATIONS)
    if tuplet_ok:
        cands.extend(TUPLET_DURATIONS)
    return tuple(sorted(set(cands), reverse=True))


def _available_space(
    start: float,
    next_start: float | None,
    measure_end: float,
    orig_crosses: bool,
) -> float:
    remaining = 8.0 if next_start is None else max(0.0, next_start - start)
    if not orig_crosses:
        remaining = min(remaining, max(0.0, measure_end - start))
    return remaining


def _choose_duration(
    *,
    target: float,
    cap: float,
    tuplet_ok: bool,
    absorb: float,
    orig_crosses: bool,
    measure_remaining: float,
    complexity_weight: float,
    tuplet_weight: float,
    rest_weight: float,
    tie_weight: float,
) -> float:
    """Named duration that never exceeds ``cap``."""
    if cap <= EPS:
        return MIN_DURATION
    fill_target = target
    if 0 < cap - target < absorb:
        fill_target = cap
    cands = _duration_candidates(tuplet_ok)
    best_d = None
    best_cost = float("inf")
    for d in cands:
        if d > cap + EPS:
            continue
        leftover = cap - d
        actual = d
        rest_pen = 0.0
        if 0 < leftover < absorb:
            actual = cap
            leftover = 0.0
            named = min(cands, key=lambda x: abs(x - cap))
            if named <= cap + EPS and abs(named - cap) <= 0.04:
                actual = named
        if 0 < leftover < 0.25:
            rest_pen = 1.0
        if actual in SIMPLE_DURATIONS:
            complexity = 0.0
        elif actual in DOTTED_DURATIONS or d in DOTTED_DURATIONS:
            complexity = 0.18
        elif d in TUPLET_DURATIONS:
            complexity = 0.12
        else:
            complexity = 1.0
        tuplet_pen = 0.0
        if d in TUPLET_DURATIONS:
            if not tuplet_ok:
                continue
            simple_err = min(abs(s - fill_target) for s in SIMPLE_DURATIONS)
            tuplet_pen = 1.0 if simple_err <= 0.08 else 0.05
        crosses = actual > measure_remaining + EPS
        tie_pen = 1.0 if crosses and not orig_crosses else 0.0
        cost = (
            abs(d - fill_target)
            + complexity_weight * complexity
            + tuplet_weight * tuplet_pen
            + tie_weight * tie_pen
            + rest_weight * rest_pen
        )
        if cost < best_cost:
            best_cost = cost
            best_d = actual
    if best_d is None:
        best_d = min(cap, fill_target if fill_target > EPS else cap)
    # Hard cap: never overflow available space, never go to zero.
    return max(MIN_DURATION, min(cap, best_d))


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
            measure_idx = measure_index_for_onset(
                ev.start_beat, ctx.mql, pull_beats=ctx.barline_pull
            )
            measure_end = (measure_idx + 1) * ctx.mql
            orig_end = raw.start_beat + raw.duration_beats
            orig_crosses = orig_end > measure_end + EPS
            cap = _available_space(ev.start_beat, nxt, measure_end, orig_crosses)
            grid = _grid_for_measure(selected_grids, measure_idx, ctx)
            tuplet_ok = abs(grid - TRIPLET_GRID) < EPS
            duration = _choose_duration(
                target=raw.duration_beats,
                cap=cap,
                tuplet_ok=tuplet_ok,
                absorb=ctx.absorb_rest,
                orig_crosses=orig_crosses,
                measure_remaining=max(0.0, measure_end - ev.start_beat),
                complexity_weight=ctx.complexity_weight,
                tuplet_weight=ctx.tuplet_weight,
                rest_weight=ctx.rest_weight,
                tie_weight=ctx.tie_weight,
            )
            out[i] = copy_event(ev, duration_beats=duration)
    return out


def _next_onset(
    events: list[MusicalEvent], indices: list[int], pos: int, start: float
) -> float | None:
    for j in indices[pos + 1 :]:
        if events[j].start_beat > start + EPS:
            return events[j].start_beat
    return None


def clamp_voice_overlaps(events: list[MusicalEvent]) -> list[MusicalEvent]:
    """Same-voice later onsets must not be overlapped. Chords (same start) may share."""
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
            room = nxt - out[i].start_beat
            if out[i].duration_beats > room + EPS:
                out[i] = copy_event(
                    out[i], duration_beats=max(MIN_DURATION, room)
                )
    return out


def restore_identity(
    raw: list[MusicalEvent], notation: list[MusicalEvent]
) -> list[MusicalEvent]:
    """Pitches, velocities, and ids always come from the raw copy.

    ``notation`` must still be in the same order as ``raw``.
    """
    out: list[MusicalEvent] = []
    for src, got in zip(raw, notation):
        duration = max(MIN_DURATION, float(got.duration_beats))
        out.append(
            copy_event(
                src,
                start_beat=got.start_beat,
                duration_beats=duration,
            )
        )
    return out


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
        measure_end = (idx + 1) * ctx.mql
        orig_end = raw.start_beat + raw.duration_beats
        orig_crosses = orig_end > measure_end + EPS
        if not orig_crosses and ev.start_beat + ev.duration_beats > measure_end + EPS:
            room = max(MIN_DURATION, measure_end - ev.start_beat)
            out[i] = copy_event(ev, duration_beats=min(ev.duration_beats, room))
            ev = out[i]
        if ev.duration_beats <= EPS:
            out[i] = copy_event(ev, duration_beats=MIN_DURATION)
            ev = out[i]
        reason = "adaptive"
        if ctx.analysis.clusters and any(
            i in c.indices and c.preserved for c in ctx.analysis.clusters
        ):
            reason = "preserved_timing"
        elif abs(grid - TRIPLET_GRID) < EPS or abs(grid - EIGHTH_TRIPLET_GRID) < EPS:
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
                preserved_timing=reason == "preserved_timing",
            ).to_dict()
        )
    return out, decisions


def quality_metrics(
    raw: list[MusicalEvent],
    notation: list[MusicalEvent],
    analysis: RhythmicAnalysis,
    decisions: list[dict],
) -> dict:
    onset_disp = [
        abs(float(d.get("quantized_start", 0)) - float(d.get("raw_start", 0)))
        for d in decisions
    ]
    dur_disp = [
        abs(float(d.get("quantized_duration", 0)) - float(d.get("raw_duration", 0)))
        for d in decisions
    ]
    moved = sum(1 for x in onset_disp if x > EPS)
    tiny_rests = 0
    overlaps = 0
    measure_violations = 0
    grouped: dict[tuple[int, int], list[MusicalEvent]] = {}
    for ev in notation:
        grouped.setdefault((staff_for_hand(ev.hand, ev.pitch), int(ev.voice)), []).append(ev)
    for group in grouped.values():
        ordered = sorted(group, key=lambda e: (e.start_beat, e.pitch))
        for i, ev in enumerate(ordered):
            nxt = None
            for later in ordered[i + 1 :]:
                if later.start_beat > ev.start_beat + EPS:
                    nxt = later
                    break
            if nxt is not None:
                gap = nxt.start_beat - (ev.start_beat + ev.duration_beats)
                if EPS < gap < TINY_REST:
                    tiny_rests += 1
                if ev.start_beat + ev.duration_beats > nxt.start_beat + 1e-6:
                    overlaps += 1
            if ev.duration_beats <= EPS:
                measure_violations += 1
    mean_onset = (sum(onset_disp) / len(onset_disp)) if onset_disp else 0.0
    mean_dur = (sum(dur_disp) / len(dur_disp)) if dur_disp else 0.0
    return {
        "mean_onset_displacement": mean_onset,
        "mean_duration_displacement": mean_dur,
        "max_onset_displacement": max(onset_disp) if onset_disp else 0.0,
        "max_duration_displacement": max(dur_disp) if dur_disp else 0.0,
        "notes_moved": moved,
        "notes_preserved": len(notation),
        "chord_alignments": sum(1 for c in analysis.clusters if len(c.indices) >= 2),
        "triplet_groups": analysis.triplet_groups,
        "tiny_rests": tiny_rests,
        "measure_violations": measure_violations,
        "overlaps_detected": overlaps,
        "fallback_preserved": sum(
            1 for d in decisions if d.get("preserved_timing")
        )
        + sum(1 for c in analysis.clusters if c.preserved),
        "events_removed": max(0, len(raw) - len(notation)),
    }


def _empty_quality_summary() -> dict:
    return {
        "raw_events": 0,
        "quantized_events": 0,
        "events_changed": 0,
        "events_removed": 0,
        "average_onset_displacement": 0.0,
        "average_duration_displacement": 0.0,
        "mean_onset_displacement": 0.0,
        "mean_duration_displacement": 0.0,
        "max_onset_displacement": 0.0,
        "max_duration_displacement": 0.0,
        "triplet_decisions": 0,
        "removed_events": [],
        "notes_moved": 0,
        "notes_preserved": 0,
        "chord_alignments": 0,
        "triplet_groups": 0,
        "tiny_rests": 0,
        "measure_violations": 0,
        "overlaps_detected": 0,
        "fallback_preserved": 0,
        "engine": "adaptive",
    }
