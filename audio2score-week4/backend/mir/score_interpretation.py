"""Joint tempo-scale / meter candidates. Derived score time only.

Never mutates performed seconds, pitch, velocity, or note_id.
Half/double-time reinterprets the beat grid; audio is not time-stretched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Iterable

from mir.meter import SUPPORTED_METERS
from mir.types import Hand
from timing.tempo_map import MusicalTimeMap

TEMPO_SCALES = (0.5, 1.0, 2.0)
APPLY_MARGIN = 0.82


@dataclass
class CandidateScore:
    tempo_scale: float
    meter: str
    timing_cost: float
    grouping_cost: float
    rhythm_complexity: float
    rest_fragmentation: float
    tie_complexity: float
    voice_complexity: float
    measure_complexity: float
    notation_cost: float
    total: float
    printed_rests: int = 0
    ties: int = 0
    short_notes: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tempo_scale": self.tempo_scale,
            "meter": self.meter,
            "timing_cost": round(self.timing_cost, 4),
            "grouping_cost": round(self.grouping_cost, 4),
            "rhythm_complexity": round(self.rhythm_complexity, 4),
            "rest_fragmentation": round(self.rest_fragmentation, 4),
            "tie_complexity": round(self.tie_complexity, 4),
            "voice_complexity": round(self.voice_complexity, 4),
            "measure_complexity": round(self.measure_complexity, 4),
            "notation_cost": round(self.notation_cost, 4),
            "total": round(self.total, 4),
            "printed_rests": self.printed_rests,
            "ties": self.ties,
            "short_notes": self.short_notes,
            **self.extra,
        }


def scaled_time_map(time_map: MusicalTimeMap, scale: float) -> MusicalTimeMap:
    if abs(scale - 1.0) < 1e-9:
        return time_map
    if abs(scale - 0.5) < 1e-9:
        return time_map.with_stride(2)
    if abs(scale - 2.0) < 1e-9:
        return time_map.with_subdivisions(2)
    return time_map


def source_identity(note) -> dict[str, Any]:
    return {
        "note_id": getattr(note, "note_id", None),
        "pitch": int(note.pitch),
        "velocity": int(getattr(note, "velocity", 0) or 0),
        "start_sec": float(getattr(note, "start_time", getattr(note, "start_sec", 0.0))),
        "end_sec": float(getattr(note, "end_time", getattr(note, "end_sec", 0.0))),
    }


def beats_for_notes(notes, time_map: MusicalTimeMap) -> list[dict[str, Any]]:
    rows = []
    for note in notes:
        ident = source_identity(note)
        start = time_map.seconds_to_beats(ident["start_sec"])
        end = time_map.seconds_to_beats(ident["end_sec"])
        rows.append(
            {
                **ident,
                "start_beat": start,
                "duration_beats": max(1e-4, end - start),
            }
        )
    return rows


def _measure_ql(name: str) -> float:
    for meter, _n, _d, mql in SUPPORTED_METERS:
        if meter == name:
            return mql
    return 4.0


def _grid_error(onset: float, pulse: float) -> float:
    grid = onset / pulse
    return abs(grid - round(grid))


def _period_strength(onsets: list[float], period: int) -> float:
    if not onsets or period <= 0:
        return 0.0
    bins = [0.0] * period
    for onset in onsets:
        bins[int(round(onset)) % period] += 1.0
    total = sum(bins) or 1.0
    return bins[0] / total - 1.0 / period


def triple_grouping_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
    """3/4 (2+2+2) vs 6/8 (3+3). Velocity is supporting evidence only."""
    bins = [0.0] * 6
    if not rows:
        return {"score_3_4": 0.0, "score_6_8": 0.0, "bass_at_1_5": 0.0, "quarter_offbeats": 0.0}
    for row in rows:
        rel = row["start_beat"] % 3.0
        idx = int(round(rel / 0.5)) % 6
        weight = 1.0 + max(0.0, (60 - int(row.get("pitch") or 60)) / 30.0)
        bins[idx] += weight
    total = sum(bins) or 1.0
    norm = [b / total for b in bins]
    score_68 = (
        1.15 * norm[0]
        + 0.95 * norm[3]
        + 0.20 * (norm[1] + norm[5])
        - 0.35 * (norm[2] + norm[4])
    )
    score_34 = (
        1.10 * norm[0]
        + 0.70 * (norm[2] + norm[4])
        - 0.55 * norm[3]
        - 0.10 * (norm[1] + norm[5])
    )
    return {
        "score_3_4": round(score_34, 4),
        "score_6_8": round(score_68, 4),
        "bass_at_1_5": round(norm[3], 4),
        "quarter_offbeats": round(norm[2] + norm[4], 4),
    }


def summarize_hand_decisions(events, source: str = "viterbi") -> dict[str, Any]:
    crossings = 0
    ambiguous = 0
    frames: dict[float, dict[str, list[int]]] = {}
    for ev in events or []:
        hand = getattr(ev, "hand", None)
        value = getattr(hand, "value", hand)
        if value == Hand.AMBIGUOUS.value or value == "ambiguous":
            ambiguous += 1
        beat = round(float(getattr(ev, "start_beat", 0.0)), 3)
        frame = frames.setdefault(beat, {"left": [], "right": []})
        if value in ("left", "right"):
            frame[value].append(int(ev.pitch))
    for frame in frames.values():
        if frame["left"] and frame["right"] and max(frame["left"]) > min(frame["right"]):
            crossings += 1
    return {
        "source": source or "viterbi",
        "crossings": crossings,
        "ambiguous_notes": ambiguous,
    }


def score_notation_cost(rows: list[dict[str, Any]], meter: str) -> dict[str, float | int]:
    """Transparent cost. Does not rewrite notes."""
    mql = _measure_ql(meter)
    if meter in ("6/8", "9/8", "12/8"):
        pulse = 0.5
        if meter == "6/8":
            strong, medium = {0}, {3}
        elif meter == "9/8":
            strong, medium = {0}, {3, 6}
        else:
            strong, medium = {0, 6}, {3, 9}
        compound = True
    elif meter == "3/4":
        pulse, strong, medium, compound = 1.0, {0}, {1, 2}, False
    elif meter == "2/4":
        pulse, strong, medium, compound = 1.0, {0}, {1}, False
    else:
        pulse, strong, medium, compound = 1.0, {0}, {2}, False

    if not rows:
        return {
            "timing_cost": 1.0,
            "grouping_cost": 1.0,
            "rhythm_complexity": 0.0,
            "rest_fragmentation": 0.0,
            "tie_complexity": 0.0,
            "voice_complexity": 0.0,
            "measure_complexity": 0.5,
            "notation_cost": 1.0,
            "printed_rests": 0,
            "ties": 0,
            "short_notes": 0,
        }

    onsets = sorted(r["start_beat"] for r in rows)
    span = max(onsets[-1] - onsets[0], mql)
    n_measures = max(1, int(round(span / mql)))
    timing = 0.0
    grouping = 0.0
    short = 0
    ties = 0
    rests = 0
    for row in rows:
        rel = row["start_beat"] % mql
        err = _grid_error(rel, pulse)
        timing += min(1.0, err * 2.0)
        bin_i = int(round(rel / pulse)) % max(1, int(round(mql / pulse)))
        if bin_i in strong:
            grouping -= 0.15
        elif bin_i in medium:
            grouping -= 0.04
        else:
            grouping += 0.08
        dur = row["duration_beats"]
        if dur <= 0.125 + 1e-6:
            short += 1
        if dur > mql + 0.05:
            ties += 1
    timing /= len(rows)
    grouping = max(0.0, grouping / len(rows) + 0.2)
    triple = triple_grouping_scores(rows)
    p2 = _period_strength(onsets, 2)
    p3 = _period_strength(onsets, 3)
    p4 = _period_strength(onsets, 4)
    lows = [r["start_beat"] for r in rows if int(r.get("pitch") or 72) <= 55]
    p3_low = _period_strength(lows, 3) if lows else 0.0
    p4_low = _period_strength(lows, 4) if lows else 0.0
    if meter == "6/8":
        grouping = max(0.0, grouping * (0.55 if triple["score_6_8"] > triple["score_3_4"] + 0.08 else 1.25))
        grouping += max(0.0, 0.35 - triple["score_6_8"])
        if triple["score_6_8"] <= triple["score_3_4"] + 0.08:
            grouping += 0.22
    elif meter == "3/4":
        grouping = max(0.0, grouping * (0.55 if triple["score_3_4"] > triple["score_6_8"] + 0.08 else 1.25))
        grouping += max(0.0, 0.35 - triple["score_3_4"])
        if not lows or p3_low < p4_low + 0.08:
            grouping += 0.3
        if p3 < p4 + 0.04:
            grouping += 0.12
    elif meter == "2/4" and p2 <= p4 + 0.05:
        grouping += 0.12
    elif meter == "4/4":
        if p3_low > p4_low + 0.08:
            grouping += 0.15
        elif p4 >= p3:
            grouping *= 0.85
    elif compound:
        dotted = 1.5
        on_compound = sum(1 for o in onsets if _grid_error(o % mql, dotted) < 0.12)
        grouping *= 0.7 if on_compound >= len(onsets) * 0.35 else 1.15

    densities = []
    start = onsets[0]
    for i in range(n_measures):
        a = start + i * mql
        densities.append(sum(1 for o in onsets if a <= o < a + mql))
    empty = sum(1 for d in densities if d == 0)
    one_note = sum(1 for d in densities if d == 1)
    measure_complexity = (empty * 0.35 + one_note * 0.12) / n_measures
    if n_measures > len(rows) * 1.5:
        measure_complexity += 0.25

    # Rest fragments: gaps smaller than a beat inside a measure.
    rest_frag = 0.0
    ordered = sorted(rows, key=lambda r: r["start_beat"])
    for a, b in zip(ordered, ordered[1:]):
        gap = b["start_beat"] - (a["start_beat"] + a["duration_beats"])
        if 0.02 < gap < 0.45:
            rest_frag += 0.4
            rests += 1
        elif gap >= 0.45:
            rests += 1
    rest_frag /= max(1, len(rows))

    rhythm = short / len(rows)
    # Preserve genuine fast patterns: four even sixteenths should not be costly.
    even_16 = 0
    for a, b in zip(onsets, onsets[1:]):
        if abs((b - a) - 0.25) < 0.04:
            even_16 += 1
    if even_16 >= 3:
        rhythm *= 0.35

    even_trip = 0
    for a, b in zip(onsets, onsets[1:]):
        if abs((b - a) - (1.0 / 3.0)) < 0.05:
            even_trip += 1
    if even_trip >= 2:
        rhythm *= 0.4

    durations = [r["duration_beats"] for r in rows]
    avg_dur = mean(durations)
    if avg_dur < 0.22 and even_16 < 3 and even_trip < 2:
        rhythm += 0.35
    elif avg_dur > 2.2:
        measure_complexity += 0.15
    if len(onsets) >= 4:
        gaps = [b - a for a, b in zip(onsets, onsets[1:])]
        median_gap = sorted(gaps)[len(gaps) // 2]
        if 1.7 < median_gap < 2.4:
            measure_complexity += 0.25

    tie_cost = ties / len(rows)
    ordered = sorted(rows, key=lambda r: (r["start_beat"], r.get("pitch") or 0))
    staggered = 0
    for i, a in enumerate(ordered):
        a_end = a["start_beat"] + a["duration_beats"]
        for b in ordered[i + 1 :]:
            if b["start_beat"] >= a_end - 0.04:
                break
            if abs(b["start_beat"] - a["start_beat"]) > 0.04 and a.get("pitch") != b.get("pitch"):
                staggered += 1
    voice_cost = min(1.0, staggered / max(1, len(rows)) * 0.25)
    notation = (
        1.1 * timing
        + 0.9 * rhythm
        + 0.8 * rest_frag
        + 0.7 * tie_cost
        + 0.6 * measure_complexity
        + 0.5 * grouping
        + 0.4 * voice_cost
    )
    return {
        "timing_cost": timing,
        "grouping_cost": grouping,
        "rhythm_complexity": rhythm,
        "rest_fragmentation": rest_frag,
        "tie_complexity": tie_cost,
        "voice_complexity": voice_cost,
        "measure_complexity": measure_complexity,
        "notation_cost": notation,
        "printed_rests": rests,
        "ties": ties,
        "short_notes": short,
    }


def evaluate_candidates(
    notes,
    time_map: MusicalTimeMap,
    *,
    meters: Iterable[str] | None = None,
    scales: Iterable[float] = TEMPO_SCALES,
) -> list[CandidateScore]:
    meter_names = tuple(meters) if meters else tuple(m[0] for m in SUPPORTED_METERS)
    identities = [source_identity(n) for n in notes]
    orig_onsets = sorted(r["start_beat"] for r in beats_for_notes(notes, time_map))
    even_16_orig = sum(
        1 for a, b in zip(orig_onsets, orig_onsets[1:]) if abs((b - a) - 0.25) < 0.04
    )
    even_trip_orig = sum(
        1
        for a, b in zip(orig_onsets, orig_onsets[1:])
        if abs((b - a) - (1.0 / 3.0)) < 0.05
    )
    keep_fast_pattern = even_16_orig >= 3 or even_trip_orig >= 2
    out: list[CandidateScore] = []
    for scale in scales:
        scaled = scaled_time_map(time_map, float(scale))
        rows = beats_for_notes(notes, scaled)
        assert [source_identity(n) for n in notes] == identities
        for meter in meter_names:
            costs = score_notation_cost(rows, meter)
            total = float(costs["notation_cost"]) + 0.15 * abs(float(scale) - 1.0)
            if keep_fast_pattern and abs(float(scale) - 1.0) > 1e-9:
                total += 0.6
            out.append(
                CandidateScore(
                    tempo_scale=float(scale),
                    meter=meter,
                    timing_cost=float(costs["timing_cost"]),
                    grouping_cost=float(costs["grouping_cost"]),
                    rhythm_complexity=float(costs["rhythm_complexity"]),
                    rest_fragmentation=float(costs["rest_fragmentation"]),
                    tie_complexity=float(costs["tie_complexity"]),
                    voice_complexity=float(costs["voice_complexity"]),
                    measure_complexity=float(costs["measure_complexity"]),
                    notation_cost=float(costs["notation_cost"]),
                    total=total,
                    printed_rests=int(costs["printed_rests"]),
                    ties=int(costs["ties"]),
                    short_notes=int(costs["short_notes"]),
                    extra={
                        "beat_count": len(scaled.beat_times),
                        **(
                            triple_grouping_scores(rows)
                            if meter in ("3/4", "6/8")
                            else {}
                        ),
                    },
                )
            )
        assert [source_identity(n) for n in notes] == identities
    out.sort(key=lambda c: c.total)
    return out


def choose_candidate(
    candidates: list[CandidateScore],
    *,
    prefer_meter: str | None = None,
    allow_retune: bool = True,
) -> CandidateScore | None:
    if not candidates:
        return None
    by_scale: dict[float, list[CandidateScore]] = {}
    for cand in candidates:
        by_scale.setdefault(cand.tempo_scale, []).append(cand)

    def representative(scale: float) -> CandidateScore:
        rows = by_scale[scale]
        meter = prefer_meter or "4/4"
        return next((c for c in rows if c.meter == meter), min(rows, key=lambda c: c.total))

    baseline = representative(1.0) if 1.0 in by_scale else min(candidates, key=lambda c: c.total)
    best_scale = min((representative(scale) for scale in by_scale), key=lambda c: c.total)
    scale = baseline.tempo_scale
    if allow_retune and best_scale.total <= APPLY_MARGIN * max(baseline.total, 1e-6):
        scale = best_scale.tempo_scale
    return min(by_scale[scale], key=lambda c: c.total)


def infer_pickup(
    first_beat: float,
    measure_ql: float,
    *,
    downbeat_beats: list[float] | None = None,
) -> dict[str, Any]:
    """Do not treat every incomplete opening as a pickup."""
    if first_beat <= 0.08 or measure_ql <= 0:
        return {"pickup_inferred": False, "pickup_beats": 0.0}
    rel = first_beat % measure_ql
    if rel <= 0.08 or rel >= measure_ql - 0.08:
        return {"pickup_inferred": False, "pickup_beats": 0.0}
    downs = [b for b in (downbeat_beats or []) if abs(b - round(b)) < 0.08]
    if not downs:
        return {"pickup_inferred": False, "pickup_beats": 0.0}
    # Strong evidence: a measured downbeat after the first attack.
    if min(downs) > first_beat + 0.1:
        return {"pickup_inferred": True, "pickup_beats": round(rel, 4)}
    return {"pickup_inferred": False, "pickup_beats": 0.0}


def complexity_warnings(
    *,
    voices_max: int,
    rests_per_voice: float,
    fragment_ties: int,
    short_ratio: float,
    tuplet_ratio: float,
    has_fast_pattern: bool,
) -> list[str]:
    warnings: list[str] = []
    if voices_max > 2:
        warnings.append("notation_complexity_warning: >2 voices/staff")
    if rests_per_voice > 4:
        warnings.append("notation_complexity_warning: >4 printed rests/voice/measure")
    if fragment_ties > 4:
        warnings.append("notation_complexity_warning: ties from tiny duration fragments")
    if short_ratio > 0.25 and not has_fast_pattern:
        warnings.append("notation_complexity_warning: >25% notes ≤32nd without a fast pattern")
    if tuplet_ratio > 0.45 and not has_fast_pattern:
        warnings.append("notation_complexity_warning: excessive tuplets without repeated structure")
    return warnings
