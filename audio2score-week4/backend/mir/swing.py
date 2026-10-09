"""Swing-aware feel inference and reversible written-timing mapping.

Work is in normalized beat coordinates from the tempo map, never in fixed
millisecond thresholds. Genre/style is a prior. User overrides win. Sparse or
conflicting evidence falls back to straight notation.

Written vs performed mapping (ratio r:1, subdivision pair length P = 2U)::

    performed offbeat fraction  f_p = r / (r + 1)
    written offbeat fraction    f_w = 1 / 2

    f_written(f) =
        f * (f_w / f_p)                         if 0 <= f <= f_p
        f_w + (f - f_p) * ((1-f_w)/(1-f_p))     if f_p < f <= 1

The inverse is the same piecewise linear map with f_p and f_w swapped.
Source timestamps (seconds) are never rewritten. Long sustained ends are not
pulled onto swing slots.

Compound meters (6/8, 9/8, 12/8) are not classified as swing: equal eighths
there are the ordinary pulse, not a binary long-short pair.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import median, pstdev
from typing import Any, Iterable

from mir.interpretation_profile import (
    InterpretationProfile,
    RhythmicFeel,
    SourceStyle,
    StylePrior,
    TimingFeel,
)

DEFAULT_SWING_RATIO = 2.0
SHUFFLE_RATIO_PRIOR = 2.0
LIGHT_SWING_RATIO = 1.5
PAIR_EIGHTH = 1.0
PAIR_SIXTEENTH = 0.5
CHORD_WINDOW_BEATS = 0.04
DOWNBEAT_FRAC = 0.12
SWING_OFFBEAT_WINDOW = 0.11
DOTTED_FRAC = 0.75
STRAIGHT_FRAC = 0.5
TRIPLET_OFF_FRAC = 2.0 / 3.0
WINDOW_BEATS = 4.0
MIN_RATIO = 1.15
MAX_RATIO = 2.55  # 3:1 (0.75) is a dotted rhythm, not swing

COMPOUND_METERS = {"6/8", "9/8", "12/8"}


@dataclass(frozen=True)
class InterpretationSpan:
    start_beat: float
    end_beat: float
    feel: str
    subdivision_unit: float
    ratio: float | None
    confidence: float
    evidence_count: int
    origin: str
    triplet_exceptions: tuple[tuple[float, float], ...] = ()

    def contains(self, beat: float, *, end_inclusive: bool = False) -> bool:
        if end_inclusive:
            return self.start_beat - 1e-9 <= float(beat) <= self.end_beat + 1e-9
        return self.start_beat - 1e-9 <= float(beat) < self.end_beat - 1e-9

    def triplet_exception_at(self, beat: float) -> bool:
        moment = float(beat)
        return any(start - 1e-9 <= moment < end + 1e-9 for start, end in self.triplet_exceptions)

    def pair_length(self) -> float:
        return max(2.0 * float(self.subdivision_unit), 1e-6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_beat": round(float(self.start_beat), 6),
            "end_beat": round(float(self.end_beat), 6),
            "feel": self.feel,
            "subdivision_unit": float(self.subdivision_unit),
            "ratio": None if self.ratio is None else round(float(self.ratio), 4),
            "confidence": round(float(self.confidence), 4),
            "evidence_count": int(self.evidence_count),
            "origin": self.origin,
            "triplet_exceptions": [
                [round(float(a), 4), round(float(b), 4)] for a, b in self.triplet_exceptions
            ],
        }


def performed_offbeat_fraction(ratio: float) -> float:
    r = max(float(ratio), 1e-6)
    return r / (r + 1.0)


def map_pair_fraction(fraction: float, ratio: float, *, reverse: bool = False) -> float:
    """Map a position in [0, 1] of a subdivision pair between performed and written."""
    f = float(fraction) % 1.0
    f_p = performed_offbeat_fraction(ratio)
    f_w = 0.5
    src, dst = (f_w, f_p) if reverse else (f_p, f_w)
    if src <= 1e-9:
        return f
    if f <= src:
        return f * (dst / src)
    remain_src = max(1.0 - src, 1e-9)
    remain_dst = 1.0 - dst
    return dst + (f - src) * (remain_dst / remain_src)


def map_beat_through_swing(beat: float, *, pair_length: float, ratio: float, reverse: bool = False) -> float:
    pair = max(float(pair_length), 1e-6)
    origin = float(beat)
    index = origin // pair
    frac = (origin - index * pair) / pair
    mapped = map_pair_fraction(frac, ratio, reverse=reverse)
    return (index + mapped) * pair


def _stream_key(event) -> tuple:
    hand = getattr(event, "hand", None)
    hand_value = getattr(hand, "value", hand)
    voice = getattr(event, "voice", 0)
    track = str(getattr(event, "source_track_id", "") or "")
    return (track, hand_value, int(voice or 0))


def _onset(event) -> float:
    performed = getattr(event, "performed_start_beat", None)
    if performed is not None:
        return float(performed)
    return float(event.start_beat)


def _collapse_onsets(onsets: Iterable[float], window: float = CHORD_WINDOW_BEATS) -> list[float]:
    ordered = sorted(float(v) for v in onsets)
    if not ordered:
        return []
    groups = [[ordered[0]]]
    for onset in ordered[1:]:
        if onset - groups[-1][-1] <= window:
            groups[-1].append(onset)
        else:
            groups.append([onset])
    return [sum(group) / len(group) for group in groups]


def _meter_name(meter) -> str:
    if meter is None:
        return "4/4"
    if isinstance(meter, str):
        return meter
    return str(getattr(meter, "time_signature", None) or "4/4")


def _is_compound(meter) -> bool:
    return _meter_name(meter) in COMPOUND_METERS


def _piece_span(onsets: list[float], meter) -> tuple[float, float]:
    if not onsets:
        return (0.0, 4.0)
    mql = float(getattr(meter, "measure_quarter_length", 4.0) or 4.0)
    start = min(0.0, onsets[0])
    last = onsets[-1]
    # Pad to the next measure boundary, not past a tiny leftover window.
    end = max(mql, (int(last / mql) + 1) * mql)
    if end - last > mql:
        end = last + 0.01
    return (start, end)


def _ratio_from_fraction(fraction: float) -> float:
    f = min(max(float(fraction), 0.51), 0.82)
    return f / max(1.0 - f, 1e-6)


def _window_score(
    fractions: list[float],
    *,
    target: float,
    prior: float,
    n: int,
) -> tuple[float, float]:
    if n <= 0 or not fractions:
        return (prior * 0.05, 0.0)
    residuals = [abs(f - target) for f in fractions]
    mean_res = sum(residuals) / len(residuals)
    spread = pstdev(fractions) if len(fractions) > 1 else 0.0
    consistency = max(0.0, 1.0 - spread * 3.0)
    closeness = max(0.0, 1.0 - mean_res / 0.22)
    evidence = min(1.0, n / 6.0)
    score = 0.55 * closeness + 0.25 * consistency + 0.12 * evidence + 0.08 * prior
    confidence = closeness * consistency * (0.55 + 0.45 * evidence)
    return (score, confidence)


def _triplet_beats(onsets: list[float]) -> tuple[tuple[float, float], ...]:
    by_beat: dict[int, list[float]] = defaultdict(list)
    for onset in onsets:
        beat = int(onset) if onset >= 0 else int(onset) - 1
        by_beat[beat].append(onset - beat)
    found = []
    expected = (0.0, 1.0 / 3.0, 2.0 / 3.0)
    for beat, fracs in by_beat.items():
        if len(fracs) < 3:
            continue
        unused = list(fracs)
        matched = []
        for target in expected:
            if not unused:
                break
            best = min(unused, key=lambda f: abs(f - target))
            if abs(best - target) <= 0.08:
                matched.append(best)
                unused.remove(best)
        if len(matched) >= 3:
            found.append((float(beat), float(beat) + 1.0))
    return tuple(found)


def _offbeat_fractions(onsets: list[float], pair_length: float, triplet_beats) -> list[float]:
    pair = max(float(pair_length), 1e-6)
    out = []
    for onset in onsets:
        if any(start - 1e-9 <= onset < end for start, end in triplet_beats):
            continue
        frac = (onset % pair) / pair
        if DOWNBEAT_FRAC < frac < (1.0 - DOWNBEAT_FRAC):
            out.append(frac)
    return out


def _hypothesis_for_window(
    onsets: list[float],
    *,
    start: float,
    end: float,
    prior: StylePrior,
    profile: InterpretationProfile,
    pair_length: float,
    feel: str,
    triplet_beats,
) -> dict[str, Any]:
    local = [o for o in onsets if start - 1e-9 <= o < end]
    fractions = _offbeat_fractions(local, pair_length, triplet_beats)
    n = len(fractions)
    if feel == "straight":
        score, conf = _window_score(fractions, target=STRAIGHT_FRAC, prior=prior.straight, n=n)
        return {
            "feel": "straight",
            "score": score,
            "confidence": conf,
            "evidence_count": n,
            "ratio": None,
            "subdivision_unit": pair_length / 2.0,
        }
    if feel == "dotted":
        score, conf = _window_score(fractions, target=DOTTED_FRAC, prior=prior.dotted, n=n)
        return {
            "feel": "dotted",
            "score": score,
            "confidence": conf,
            "evidence_count": n,
            "ratio": None,
            "subdivision_unit": pair_length / 2.0,
        }
    target_ratio = profile.swing_ratio
    if target_ratio is None and fractions:
        raw_ratio = median(_ratio_from_fraction(f) for f in fractions)
        # 3:1 maps to dotted-eighth/sixteenth. Do not relabel it as heavy swing.
        if raw_ratio > MAX_RATIO:
            return {
                "feel": feel,
                "score": 0.0,
                "confidence": 0.0,
                "evidence_count": n,
                "ratio": None,
                "subdivision_unit": pair_length / 2.0,
            }
        target_ratio = min(MAX_RATIO, max(MIN_RATIO, raw_ratio))
    if target_ratio is None:
        target_ratio = SHUFFLE_RATIO_PRIOR if feel == "shuffle" else DEFAULT_SWING_RATIO
    if feel == "shuffle":
        target_ratio = profile.swing_ratio or SHUFFLE_RATIO_PRIOR
    if feel == "swing_eighths" and profile.swing_ratio is None and abs(target_ratio - LIGHT_SWING_RATIO) < 0.25:
        # Keep light swing (≈3:2) rather than snapping every estimate to 2:1.
        pass
    feel_prior = {
        "swing_eighths": prior.swing_eighths,
        "swing_sixteenths": prior.swing_sixteenths,
        "shuffle": prior.shuffle,
    }.get(feel, 0.1)
    target_frac = performed_offbeat_fraction(target_ratio)
    score, conf = _window_score(fractions, target=target_frac, prior=feel_prior, n=n)
    # Isolated exact-triplet offbeats without a third attack still look like 2:1.
    # Require the cluster to sit closer to the swing target than to 0.75 dotted.
    if fractions:
        swing_res = sum(abs(f - target_frac) for f in fractions) / n
        dotted_res = sum(abs(f - DOTTED_FRAC) for f in fractions) / n
        straight_res = sum(abs(f - STRAIGHT_FRAC) for f in fractions) / n
        if dotted_res + 0.02 < swing_res:
            score *= 0.35
        if straight_res + 0.03 < swing_res:
            score *= 0.4
    return {
        "feel": feel,
        "score": score,
        "confidence": conf,
        "evidence_count": n,
        "ratio": float(target_ratio),
        "subdivision_unit": pair_length / 2.0,
    }


def _pick_window(
    onsets: list[float],
    *,
    start: float,
    end: float,
    prior: StylePrior,
    profile: InterpretationProfile,
    triplet_beats,
    compound: bool,
) -> dict[str, Any]:
    candidates = [
        _hypothesis_for_window(
            onsets,
            start=start,
            end=end,
            prior=prior,
            profile=profile,
            pair_length=PAIR_EIGHTH,
            feel="straight",
            triplet_beats=triplet_beats,
        ),
        _hypothesis_for_window(
            onsets,
            start=start,
            end=end,
            prior=prior,
            profile=profile,
            pair_length=PAIR_EIGHTH,
            feel="dotted",
            triplet_beats=triplet_beats,
        ),
    ]
    if not compound:
        candidates.extend(
            [
                _hypothesis_for_window(
                    onsets,
                    start=start,
                    end=end,
                    prior=prior,
                    profile=profile,
                    pair_length=PAIR_EIGHTH,
                    feel="swing_eighths",
                    triplet_beats=triplet_beats,
                ),
                _hypothesis_for_window(
                    onsets,
                    start=start,
                    end=end,
                    prior=prior,
                    profile=profile,
                    pair_length=PAIR_EIGHTH,
                    feel="shuffle",
                    triplet_beats=triplet_beats,
                ),
                _hypothesis_for_window(
                    onsets,
                    start=start,
                    end=end,
                    prior=prior,
                    profile=profile,
                    pair_length=PAIR_SIXTEENTH,
                    feel="swing_sixteenths",
                    triplet_beats=triplet_beats,
                ),
            ]
        )
    override = profile.user_feel_override()
    if override is not None and not compound:
        named = [c for c in candidates if c["feel"] == override.value]
        if named:
            best = max(named, key=lambda c: c["score"])
            best = dict(best)
            best["origin"] = "user_override"
            best["confidence"] = max(float(best["confidence"]), 0.9)
            return best
    if override == RhythmicFeel.STRAIGHT or compound:
        best = max(
            (c for c in candidates if c["feel"] in {"straight", "dotted"}),
            key=lambda c: c["score"],
        )
        best = dict(best)
        best["feel"] = "straight"
        best["ratio"] = None
        best["origin"] = "user_override" if override else "inferred"
        return best
    ranked = sorted(candidates, key=lambda c: c["score"], reverse=True)
    best = dict(ranked[0])
    straight = next(c for c in candidates if c["feel"] == "straight")
    min_obs = prior.min_observations
    if profile.timing == TimingFeel.EXPRESSIVE:
        min_obs += 1
    if profile.source_style == SourceStyle.CLASSICAL:
        min_obs = max(min_obs, 6)
    swingish = best["feel"] in {"swing_eighths", "swing_sixteenths", "shuffle"}
    if swingish and (
        best["evidence_count"] < min_obs
        or best["confidence"] < prior.min_confidence
        or best["score"] < straight["score"] + prior.apply_margin
    ):
        best = dict(straight)
        best["feel"] = "straight"
        best["ratio"] = None
        best["origin"] = "inferred"
        return best
    if best["feel"] == "dotted":
        best["feel"] = "straight"
        best["ratio"] = None
    best["origin"] = "inferred"
    return best


def _merge_windows(windows: list[dict[str, Any]], triplet_beats) -> list[InterpretationSpan]:
    if not windows:
        return []
    trimmed = [
        row
        for row in windows
        if row.get("evidence_count", 0) > 0 or (row["end"] - row["start"]) >= WINDOW_BEATS - 1e-6
    ]
    if not trimmed:
        trimmed = list(windows)
    merged: list[dict[str, Any]] = []
    for row in trimmed:
        if (
            merged
            and merged[-1]["feel"] == row["feel"]
            and abs((merged[-1].get("ratio") or 0) - (row.get("ratio") or 0)) < 0.35
            and merged[-1]["subdivision_unit"] == row["subdivision_unit"]
        ):
            merged[-1]["end"] = row["end"]
            merged[-1]["evidence_count"] += int(row["evidence_count"])
            merged[-1]["confidence"] = max(float(merged[-1]["confidence"]), float(row["confidence"]))
            if row.get("ratio") and merged[-1].get("ratio"):
                merged[-1]["ratio"] = (float(merged[-1]["ratio"]) + float(row["ratio"])) / 2.0
        else:
            merged.append(dict(row))
    spans = []
    for row in merged:
        local_trips = tuple(
            item
            for item in triplet_beats
            if item[0] < row["end"] and item[1] > row["start"]
        )
        spans.append(
            InterpretationSpan(
                start_beat=float(row["start"]),
                end_beat=float(row["end"]),
                feel=str(row["feel"]),
                subdivision_unit=float(row["subdivision_unit"]),
                ratio=None if row.get("ratio") is None else float(row["ratio"]),
                confidence=float(row["confidence"]),
                evidence_count=int(row["evidence_count"]),
                origin=str(row.get("origin") or "inferred"),
                triplet_exceptions=local_trips,
            )
        )
    return spans


def _stream_onsets(events) -> list[float]:
    by_stream: dict[tuple, list[float]] = defaultdict(list)
    for event in events:
        by_stream[_stream_key(event)].append(_onset(event))
    pooled = []
    for group in by_stream.values():
        pooled.extend(_collapse_onsets(group))
    return sorted(pooled)


def infer_interpretation_spans(
    events,
    meter,
    profile: InterpretationProfile,
    *,
    tempo_map=None,
) -> list[InterpretationSpan]:
    """Aggregate phrase-window evidence into feel spans.

    Chord mates in one stream count once. Consecutive events in the global
    list are never treated as a pair; pairing is per stream in beat space.
    """
    del tempo_map  # Beat-space events already carry the map; seconds stay untouched.
    profile = profile or InterpretationProfile()
    prior = profile.style_prior()
    onsets = _stream_onsets(events)
    start, end = _piece_span(onsets, meter)
    compound = _is_compound(meter)
    triplet_beats = _triplet_beats(onsets)
    override = profile.user_feel_override()
    if compound and override in {
        RhythmicFeel.SWING_EIGHTHS,
        RhythmicFeel.SWING_SIXTEENTHS,
        RhythmicFeel.SHUFFLE,
    }:
        override = None
    windows = []
    cursor = start
    while cursor < end - 1e-6:
        remaining = end - cursor
        if remaining < WINDOW_BEATS * 0.5 and windows:
            windows[-1]["end"] = end
            break
        window_end = min(end, cursor + WINDOW_BEATS)
        picked = _pick_window(
            onsets,
            start=cursor,
            end=window_end,
            prior=prior,
            profile=profile,
            triplet_beats=triplet_beats,
            compound=compound,
        )
        picked["start"] = cursor
        picked["end"] = window_end
        windows.append(picked)
        cursor = window_end
    if override in {
        RhythmicFeel.SWING_EIGHTHS,
        RhythmicFeel.SWING_SIXTEENTHS,
        RhythmicFeel.SHUFFLE,
    } and not compound:
        unit = 0.25 if override == RhythmicFeel.SWING_SIXTEENTHS else 0.5
        ratio = profile.swing_ratio
        if ratio is None:
            ratio = SHUFFLE_RATIO_PRIOR if override == RhythmicFeel.SHUFFLE else DEFAULT_SWING_RATIO
        evidence = sum(int(w["evidence_count"]) for w in windows)
        return [
            InterpretationSpan(
                start_beat=start,
                end_beat=end,
                feel=override.value,
                subdivision_unit=unit,
                ratio=float(ratio),
                confidence=1.0,
                evidence_count=max(evidence, 1),
                origin="user_override",
                triplet_exceptions=triplet_beats,
            )
        ]
    if override == RhythmicFeel.STRAIGHT:
        evidence = sum(int(w["evidence_count"]) for w in windows)
        return [
            InterpretationSpan(
                start_beat=start,
                end_beat=end,
                feel="straight",
                subdivision_unit=0.5,
                ratio=None,
                confidence=1.0,
                evidence_count=evidence,
                origin="user_override",
                triplet_exceptions=triplet_beats,
            )
        ]
    return _merge_windows(windows, triplet_beats)


def _classify_onset(beat: float, span: InterpretationSpan) -> str:
    if span.feel == "straight" or span.ratio is None:
        return "exception"
    if span.triplet_exception_at(beat):
        return "triplet"
    pair = span.pair_length()
    frac = (float(beat) % pair) / pair
    target = performed_offbeat_fraction(span.ratio)
    if frac <= DOWNBEAT_FRAC or frac >= 1.0 - DOWNBEAT_FRAC:
        return "downbeat"
    if abs(frac - target) <= SWING_OFFBEAT_WINDOW:
        return "swing_offbeat"
    if abs(frac - DOTTED_FRAC) + 0.02 < abs(frac - target) and abs(frac - DOTTED_FRAC) <= 0.07:
        return "dotted"
    if abs(frac - STRAIGHT_FRAC) + 0.02 < abs(frac - target) and abs(frac - STRAIGHT_FRAC) <= 0.08:
        return "straight"
    if abs(frac - TRIPLET_OFF_FRAC) <= 0.05 and span.triplet_exception_at(beat):
        return "triplet"
    return "ambiguous"


def span_at(spans: Iterable[InterpretationSpan], beat: float) -> InterpretationSpan | None:
    moment = float(beat)
    for span in spans:
        if span.contains(moment, end_inclusive=True):
            return span
    return None


def apply_written_timing(events, spans: list[InterpretationSpan]):
    """Rewrite score beats only. Seconds and note identity stay the same."""
    if not spans or not events:
        return list(events)
    from mir.types import copy_event

    out = []
    for event in events:
        if getattr(event, "score_timing_locked", False):
            out.append(event)
            continue
        perf_start = getattr(event, "performed_start_beat", None)
        if perf_start is None:
            perf_start = float(event.start_beat)
        else:
            perf_start = float(perf_start)
        perf_dur = getattr(event, "performed_duration_beats", None)
        if perf_dur is None:
            perf_dur = float(event.duration_beats)
        else:
            perf_dur = float(perf_dur)
        perf_end = perf_start + max(perf_dur, 1e-6)
        span = span_at(spans, perf_start)
        changes = {
            "performed_start_beat": perf_start,
            "performed_duration_beats": perf_dur,
        }
        if (
            span is None
            or span.feel == "straight"
            or span.ratio is None
            or _classify_onset(perf_start, span) in {"exception", "triplet", "dotted", "straight", "ambiguous"}
        ):
            out.append(copy_event(event, **changes))
            continue
        written_start = map_beat_through_swing(
            perf_start, pair_length=span.pair_length(), ratio=span.ratio
        )
        pair = span.pair_length()
        if perf_dur <= pair * 1.25:
            end_span = span_at(spans, perf_end) or span
            if (
                end_span.feel != "straight"
                and end_span.ratio is not None
                and not end_span.triplet_exception_at(perf_end)
            ):
                written_end = map_beat_through_swing(
                    perf_end, pair_length=end_span.pair_length(), ratio=end_span.ratio
                )
            else:
                written_end = written_start + perf_dur
            written_dur = max(written_end - written_start, 1e-4)
        else:
            written_dur = max(perf_dur, 1e-4)
        out.append(
            copy_event(
                event,
                start_beat=float(written_start),
                duration_beats=float(written_dur),
                **changes,
            )
        )
    return out


def summarize_spans(spans: list[InterpretationSpan]) -> dict[str, Any]:
    if not spans:
        return {
            "rhythmic_feel": "straight",
            "confidence": 0.0,
            "spans": [],
            "origin": "inferred",
            "evidence_count": 0,
        }
    swing = [s for s in spans if s.feel in {"swing_eighths", "swing_sixteenths", "shuffle"}]
    if swing and len(swing) == len(spans):
        dominant = max(swing, key=lambda s: s.end_beat - s.start_beat)
        feel = dominant.feel
    elif swing:
        feel = "mixed"
    else:
        feel = "straight"
    origins = {s.origin for s in spans}
    origin = "user_override" if origins == {"user_override"} else (
        "mixed" if len(origins) > 1 else next(iter(origins))
    )
    return {
        "rhythmic_feel": feel,
        "confidence": max((s.confidence for s in spans), default=0.0),
        "spans": [s.to_dict() for s in spans],
        "origin": origin,
        "evidence_count": sum(s.evidence_count for s in spans),
        "ratio": next((s.ratio for s in swing if s.ratio is not None), None),
    }


def indication_for_span(span: InterpretationSpan, *, previous_feel: str | None) -> str | None:
    """Visible marking at a section boundary. Whole-piece straight stays unmarked."""
    if span.feel in {"swing_eighths", "shuffle"}:
        return "Swing"
    if span.feel == "swing_sixteenths":
        return "Swing 16ths"
    if span.feel == "straight" and previous_feel in {
        "swing_eighths",
        "swing_sixteenths",
        "shuffle",
    }:
        return "Straight"
    return None
