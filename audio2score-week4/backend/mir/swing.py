"""Swing-aware feel inference and reversible written/playback mapping.

Work is in normalized beat coordinates from the tempo map, never in fixed
millisecond thresholds. Genre/style is a prior. User overrides win. Sparse or
conflicting evidence falls back to straight notation.

Written vs performed mapping (ratio r:1, subdivision pair length P = 2U)::

    performed offbeat fraction  f_p = r / (r + 1)
    written offbeat fraction    f_w = 1 / 2

    f_written(f) =
        f * (f_w / f_p)                         if 0 <= f <= f_p
        f_w + (f - f_p) * ((1-f_w)/(1-f_p))     if f_p < f <= 1

The inverse (written → playback) swaps f_p and f_w. Source timestamps
(seconds) are never rewritten. Long sustained ends are not pulled onto
swing slots. Score playback applies this inverse exactly once.

Compound meters (6/8, 9/8, 12/8) are not classified as swing: equal eighths
there are the ordinary pulse, not a binary long-short pair.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from math import gcd
from statistics import median, pstdev
from typing import Any, Iterable

from mir.interpretation_profile import (
    InterpretationProfile,
    RhythmicFeel,
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
TRIPLET_THIRD_FRAC = 1.0 / 3.0
MIN_RATIO = 1.15
MAX_RATIO = 2.55  # 3:1 (0.75) is a dotted rhythm, not swing
UNISON_MATCH = 0.04

COMPOUND_METERS = {"6/8", "9/8", "12/8"}
SWING_FEELS = {"swing_eighths", "swing_sixteenths", "shuffle"}


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
    triplet_exceptions: tuple[tuple[float, float, str | None], ...] = ()
    unmapped_streams: tuple[str, ...] = ()
    maps_written_timing: bool = True

    def contains(self, beat: float, *, end_inclusive: bool = False) -> bool:
        moment = float(beat)
        if end_inclusive:
            return self.start_beat - 1e-9 <= moment <= self.end_beat + 1e-9
        return self.start_beat - 1e-9 <= moment < self.end_beat - 1e-9

    def triplet_exception_at(self, beat: float, stream_key: str | None = None) -> bool:
        moment = float(beat)
        for item in self.triplet_exceptions:
            start = float(item[0])
            end = float(item[1])
            owner = item[2] if len(item) > 2 else None
            if start - 1e-9 <= moment < end + 1e-9:
                if owner is None or stream_key is None or owner == stream_key:
                    return True
        return False

    def stream_unmapped(self, stream_key: str | None) -> bool:
        if stream_key is None:
            return False
        return stream_key in self.unmapped_streams

    def pair_length(self) -> float:
        return max(2.0 * float(self.subdivision_unit), 1e-6)

    def to_dict(self) -> dict[str, Any]:
        trips = []
        for start, end, owner in self.triplet_exceptions:
            item = [round(float(start), 4), round(float(end), 4)]
            if owner:
                item.append(owner)
            trips.append(item)
        return {
            "start_beat": round(float(self.start_beat), 6),
            "end_beat": round(float(self.end_beat), 6),
            "feel": self.feel,
            "subdivision_unit": float(self.subdivision_unit),
            "ratio": None if self.ratio is None else round(float(self.ratio), 4),
            "confidence": round(float(self.confidence), 4),
            "evidence_count": int(self.evidence_count),
            "origin": self.origin,
            "triplet_exceptions": trips,
            "unmapped_streams": list(self.unmapped_streams),
            "maps_written_timing": bool(self.maps_written_timing),
        }


def span_from_dict(item: InterpretationSpan | dict | None) -> InterpretationSpan | None:
    if item is None:
        return None
    if isinstance(item, InterpretationSpan):
        return item
    trips = []
    for raw in item.get("triplet_exceptions") or ():
        if isinstance(raw, dict):
            trips.append(
                (
                    float(raw.get("start") or raw.get("start_beat") or 0.0),
                    float(raw.get("end") or raw.get("end_beat") or 0.0),
                    raw.get("stream"),
                )
            )
        else:
            start = float(raw[0])
            end = float(raw[1])
            owner = raw[2] if len(raw) > 2 else None
            trips.append((start, end, owner))
    return InterpretationSpan(
        start_beat=float(item.get("start_beat") or 0.0),
        end_beat=float(item.get("end_beat") or 0.0),
        feel=str(item.get("feel") or "straight"),
        subdivision_unit=float(item.get("subdivision_unit") or 0.5),
        ratio=item.get("ratio"),
        confidence=float(item.get("confidence") or 0.0),
        evidence_count=int(item.get("evidence_count") or 0),
        origin=str(item.get("origin") or "inferred"),
        triplet_exceptions=tuple(trips),
        unmapped_streams=tuple(str(v) for v in (item.get("unmapped_streams") or ())),
        maps_written_timing=bool(item.get("maps_written_timing", True)),
    )


def spans_from_payload(items) -> list[InterpretationSpan]:
    out = []
    for item in items or ():
        parsed = span_from_dict(item)
        if parsed is not None:
            out.append(parsed)
    return out


def performed_offbeat_fraction(ratio: float) -> float:
    r = max(float(ratio), 1e-6)
    return r / (r + 1.0)


def simplest_ratio_parts(ratio: float) -> tuple[int, int]:
    """Reduce r:1 to coprime MusicXML <first>/<second> integers."""
    frac = Fraction(float(ratio)).limit_denominator(16)
    a, b = int(frac.numerator), int(frac.denominator)
    divisor = gcd(a, b) or 1
    return a // divisor, b // divisor


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


def stream_key(event) -> str:
    hand = getattr(event, "hand", None)
    hand_value = getattr(hand, "value", hand)
    voice = getattr(event, "voice", 0)
    track = str(getattr(event, "source_track_id", "") or "")
    return f"{track}|{hand_value}|{int(voice or 0)}"


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
    end = max(mql, (int(last / mql) + 1) * mql)
    if end - last > mql:
        end = last + 0.01
    return (start, end)


def _ratio_from_fraction(fraction: float) -> float:
    f = min(max(float(fraction), 0.51), 0.82)
    return f / max(1.0 - f, 1e-6)


def _onset_sets_match(left: list[float], right: list[float]) -> bool:
    if not left or not right:
        return False
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if len(shorter) / max(len(longer), 1) < 0.8:
        return False
    hits = 0
    for onset in shorter:
        if any(abs(onset - other) <= UNISON_MATCH for other in longer):
            hits += 1
    return hits / len(shorter) >= 0.85


def _dedup_streams(streams: dict[str, list[float]]) -> dict[str, list[float]]:
    """Unison / doubled tracks count once for rhythmic evidence."""
    keys = list(streams)
    keep: list[str] = []
    dropped: set[str] = set()
    for index, key in enumerate(keys):
        if key in dropped:
            continue
        keep.append(key)
        for other in keys[index + 1 :]:
            if other in dropped:
                continue
            if _onset_sets_match(streams[key], streams[other]):
                dropped.add(other)
    return {key: streams[key] for key in keep}


def _streams_from_events(events) -> dict[str, list[float]]:
    by_stream: dict[str, list[float]] = defaultdict(list)
    for event in events:
        by_stream[stream_key(event)].append(_onset(event))
    collapsed = {key: _collapse_onsets(group) for key, group in by_stream.items()}
    return _dedup_streams(collapsed)


def _window_score(
    fractions: list[float],
    *,
    target: float,
    prior: float,
    n: int,
    required: int,
) -> tuple[float, float]:
    if n <= 0 or not fractions:
        return (prior * 0.05, 0.0)
    residuals = [abs(f - target) for f in fractions]
    mean_res = sum(residuals) / len(residuals)
    spread = pstdev(fractions) if len(fractions) > 1 else 0.0
    consistency = max(0.0, 1.0 - spread * 3.0)
    closeness = max(0.0, 1.0 - mean_res / 0.22)
    evidence = min(1.0, n / max(float(required), 1.0))
    score = 0.55 * closeness + 0.25 * consistency + 0.12 * evidence + 0.08 * prior
    confidence = closeness * consistency * (0.55 + 0.45 * evidence)
    return (score, confidence)


def _triplet_beats(onsets: list[float], stream_id: str | None = None) -> tuple[tuple[float, float, str | None], ...]:
    by_beat: dict[int, list[float]] = defaultdict(list)
    for onset in onsets:
        beat = int(onset) if onset >= 0 else int(onset) - 1
        by_beat[beat].append(onset - beat)
    found = []
    expected = (0.0, TRIPLET_THIRD_FRAC, TRIPLET_OFF_FRAC)
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
            found.append((float(beat), float(beat) + 1.0, stream_id))
    return tuple(found)


def _offbeat_fractions(onsets: list[float], pair_length: float, triplet_beats) -> list[float]:
    pair = max(float(pair_length), 1e-6)
    out = []
    for onset in onsets:
        if any(start - 1e-9 <= onset < end for start, end, *_rest in triplet_beats):
            continue
        frac = (onset % pair) / pair
        if DOWNBEAT_FRAC < frac < (1.0 - DOWNBEAT_FRAC):
            out.append(frac)
    return out


def _required_observations(prior: StylePrior, window_beats: float, pair_length: float) -> int:
    possible = max(1, int(round(float(window_beats) / max(float(pair_length), 1e-6))))
    # A window cannot be asked for more offbeats than it can contain.
    return max(2, min(int(prior.min_observations), possible))


def _adaptive_window_beats(prior: StylePrior) -> float:
    return max(4.0, float(prior.min_observations))


def _hypothesis_for_window(
    fractions: list[float],
    *,
    prior: StylePrior,
    profile: InterpretationProfile,
    pair_length: float,
    feel: str,
    required: int,
) -> dict[str, Any]:
    n = len(fractions)
    if feel == "straight":
        score, conf = _window_score(
            fractions, target=STRAIGHT_FRAC, prior=prior.straight, n=n, required=required
        )
        return {
            "feel": "straight",
            "score": score,
            "confidence": conf,
            "evidence_count": n,
            "ratio": None,
            "subdivision_unit": pair_length / 2.0,
        }
    if feel == "dotted":
        score, conf = _window_score(
            fractions, target=DOTTED_FRAC, prior=prior.dotted, n=n, required=required
        )
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
    feel_prior = {
        "swing_eighths": prior.swing_eighths,
        "swing_sixteenths": prior.swing_sixteenths,
        "shuffle": prior.shuffle,
    }.get(feel, 0.1)
    target_frac = performed_offbeat_fraction(target_ratio)
    score, conf = _window_score(
        fractions, target=target_frac, prior=feel_prior, n=n, required=required
    )
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


def _candidates_for_pair_fractions(
    eighth_fractions: list[float],
    sixteenth_fractions: list[float],
    *,
    prior: StylePrior,
    profile: InterpretationProfile,
    required_eighth: int,
    required_sixteenth: int,
    compound: bool,
) -> list[dict[str, Any]]:
    candidates = [
        _hypothesis_for_window(
            eighth_fractions,
            prior=prior,
            profile=profile,
            pair_length=PAIR_EIGHTH,
            feel="straight",
            required=required_eighth,
        ),
        _hypothesis_for_window(
            eighth_fractions,
            prior=prior,
            profile=profile,
            pair_length=PAIR_EIGHTH,
            feel="dotted",
            required=required_eighth,
        ),
    ]
    if not compound:
        candidates.extend(
            [
                _hypothesis_for_window(
                    eighth_fractions,
                    prior=prior,
                    profile=profile,
                    pair_length=PAIR_EIGHTH,
                    feel="swing_eighths",
                    required=required_eighth,
                ),
                _hypothesis_for_window(
                    eighth_fractions,
                    prior=prior,
                    profile=profile,
                    pair_length=PAIR_EIGHTH,
                    feel="shuffle",
                    required=required_eighth,
                ),
                _hypothesis_for_window(
                    sixteenth_fractions,
                    prior=prior,
                    profile=profile,
                    pair_length=PAIR_SIXTEENTH,
                    feel="swing_sixteenths",
                    required=required_sixteenth,
                ),
            ]
        )
    return candidates


def _select_candidate(
    candidates: list[dict[str, Any]],
    *,
    prior: StylePrior,
    profile: InterpretationProfile,
    compound: bool,
    required: int,
) -> dict[str, Any]:
    override = profile.user_feel_override()
    if override is not None and not compound:
        named = [c for c in candidates if c["feel"] == override.value]
        if named:
            best = dict(max(named, key=lambda c: c["score"]))
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
    min_conf = prior.min_confidence
    margin = prior.apply_margin
    if profile.timing == TimingFeel.EXPRESSIVE:
        min_conf = min(0.95, min_conf + 0.05)
    swingish = best["feel"] in SWING_FEELS
    strong = (
        float(best["confidence"]) >= 0.72
        and int(best["evidence_count"]) >= 3
        and float(best["score"]) > float(straight["score"])
    )
    if swingish and not strong and (
        best["evidence_count"] < required
        or best["confidence"] < min_conf
        or best["score"] < straight["score"] + margin
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


def _pick_window(
    streams: dict[str, list[float]],
    *,
    start: float,
    end: float,
    prior: StylePrior,
    profile: InterpretationProfile,
    stream_triplets: dict[str, tuple],
    compound: bool,
) -> dict[str, Any]:
    window_beats = max(end - start, 1e-6)
    required_eighth = _required_observations(prior, window_beats, PAIR_EIGHTH)
    required_sixteenth = _required_observations(prior, window_beats, PAIR_SIXTEENTH)

    def _fractions(pair_length: float) -> tuple[list[float], dict[str, list[float]]]:
        pooled: list[float] = []
        per_stream: dict[str, list[float]] = {}
        for key, onsets in streams.items():
            local = [o for o in onsets if start - 1e-9 <= o < end]
            fracs = _offbeat_fractions(local, pair_length, stream_triplets.get(key, ()))
            per_stream[key] = fracs
            pooled.extend(fracs)
        return pooled, per_stream

    eighth_pooled, eighth_streams = _fractions(PAIR_EIGHTH)
    sixteenth_pooled, sixteenth_streams = _fractions(PAIR_SIXTEENTH)
    stream_picks: dict[str, dict[str, Any]] = {}
    for key in streams:
        stream_picks[key] = _select_candidate(
            _candidates_for_pair_fractions(
                eighth_streams.get(key, []),
                sixteenth_streams.get(key, []),
                prior=prior,
                profile=profile,
                required_eighth=max(2, min(required_eighth, max(len(eighth_streams.get(key, [])), 2))),
                required_sixteenth=max(2, min(required_sixteenth, max(len(sixteenth_streams.get(key, [])), 2))),
                compound=compound,
            ),
            prior=prior,
            profile=profile,
            compound=compound,
            required=max(2, min(required_eighth, max(len(eighth_streams.get(key, [])), 2))),
        )
    picked = _select_candidate(
        _candidates_for_pair_fractions(
            eighth_pooled,
            sixteenth_pooled,
            prior=prior,
            profile=profile,
            required_eighth=required_eighth,
            required_sixteenth=required_sixteenth,
            compound=compound,
        ),
        prior=prior,
        profile=profile,
        compound=compound,
        required=required_eighth,
    )
    # If streams disagree, keep swing from swinging voices and leave the
    # others unmapped instead of inventing a global compromise rhythm.
    unmapped = []
    swing_streams = [
        key
        for key, row in stream_picks.items()
        if row["feel"] in SWING_FEELS and int(row["evidence_count"]) >= 2
    ]
    straightish = [
        key
        for key, row in stream_picks.items()
        if row["feel"] not in SWING_FEELS and int(row["evidence_count"]) >= 2
    ]
    if swing_streams and straightish:
        picked = dict(
            max(
                (stream_picks[key] for key in swing_streams),
                key=lambda row: (row["score"], row["evidence_count"]),
            )
        )
        picked["origin"] = picked.get("origin") or "inferred"
        unmapped = list(straightish)
        picked["evidence_count"] = sum(int(stream_picks[k]["evidence_count"]) for k in swing_streams)
    picked["unmapped_streams"] = unmapped
    local_trips = []
    for key, trips in stream_triplets.items():
        for item in trips:
            if item[0] < end and item[1] > start:
                local_trips.append(item)
    picked["triplet_exceptions"] = tuple(local_trips)
    return picked


def _merge_windows(windows: list[dict[str, Any]]) -> list[InterpretationSpan]:
    if not windows:
        return []
    merged: list[dict[str, Any]] = []
    for row in windows:
        if (
            merged
            and merged[-1]["feel"] == row["feel"]
            and abs((merged[-1].get("ratio") or 0) - (row.get("ratio") or 0)) < 0.35
            and merged[-1]["subdivision_unit"] == row["subdivision_unit"]
            and set(merged[-1].get("unmapped_streams") or ()) == set(row.get("unmapped_streams") or ())
        ):
            merged[-1]["end"] = row["end"]
            merged[-1]["evidence_count"] += int(row["evidence_count"])
            merged[-1]["confidence"] = max(float(merged[-1]["confidence"]), float(row["confidence"]))
            if row.get("ratio") and merged[-1].get("ratio"):
                merged[-1]["ratio"] = (float(merged[-1]["ratio"]) + float(row["ratio"])) / 2.0
            trips = list(merged[-1].get("triplet_exceptions") or ())
            for item in row.get("triplet_exceptions") or ():
                if item not in trips:
                    trips.append(item)
            merged[-1]["triplet_exceptions"] = tuple(trips)
        else:
            merged.append(dict(row))
    spans = []
    for row in merged:
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
                triplet_exceptions=tuple(row.get("triplet_exceptions") or ()),
                unmapped_streams=tuple(row.get("unmapped_streams") or ()),
                maps_written_timing=True,
            )
        )
    return spans


def feel_limitations(meter, profile: InterpretationProfile) -> list[dict[str, Any]]:
    """User-visible limits. Never silently claim an unsupported override applied."""
    override = profile.user_feel_override() if profile is not None else None
    if _is_compound(meter) and override in {
        RhythmicFeel.SWING_EIGHTHS,
        RhythmicFeel.SWING_SIXTEENTHS,
        RhythmicFeel.SHUFFLE,
    }:
        name = _meter_name(meter)
        return [
            {
                "kind": "unsupported_feel",
                "policy": "rhythmic_feel",
                "reason": "compound_meter_blocks_swing",
                "requested": override.value,
                "applied": "straight",
                "meter": name,
                "user_message": (
                    f"Swing cannot be applied in {name}. Compound subdivisions "
                    "stay even; the feel setting was not used."
                ),
            }
        ]
    return []


def infer_interpretation_spans(
    events,
    meter,
    profile: InterpretationProfile,
    *,
    tempo_map=None,
) -> list[InterpretationSpan]:
    """Aggregate phrase-window evidence into feel spans.

    Chord mates in one stream count once. Consecutive events in the global
    list are never treated as a pair; pairing and triplet detection are
    per stream in beat space, then support is aggregated.
    """
    del tempo_map
    profile = profile or InterpretationProfile()
    prior = profile.style_prior()
    streams = _streams_from_events(events)
    onsets = sorted(v for group in streams.values() for v in group)
    start, end = _piece_span(onsets, meter)
    compound = _is_compound(meter)
    stream_triplets = {
        key: _triplet_beats(group, stream_id=key) for key, group in streams.items()
    }
    override = profile.user_feel_override()
    windows = []
    window_beats = _adaptive_window_beats(prior)
    hop = window_beats
    cursor = start
    while cursor < end - 1e-6:
        remaining = end - cursor
        if remaining < hop and windows:
            windows[-1]["end"] = end
            break
        window_end = min(end, cursor + window_beats)
        picked = _pick_window(
            streams,
            start=cursor,
            end=window_end,
            prior=prior,
            profile=profile,
            stream_triplets=stream_triplets,
            compound=compound,
        )
        picked["start"] = cursor
        picked["end"] = window_end
        windows.append(picked)
        if window_end >= end - 1e-9:
            break
        cursor += hop
    all_trips = tuple(item for trips in stream_triplets.values() for item in trips)
    if (
        override in {
            RhythmicFeel.SWING_EIGHTHS,
            RhythmicFeel.SWING_SIXTEENTHS,
            RhythmicFeel.SHUFFLE,
        }
        and not compound
    ):
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
                triplet_exceptions=all_trips,
                maps_written_timing=True,
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
                triplet_exceptions=all_trips,
                maps_written_timing=False,
            )
        ]
    if compound:
        evidence = sum(int(w["evidence_count"]) for w in windows)
        return [
            InterpretationSpan(
                start_beat=start,
                end_beat=end,
                feel="straight",
                subdivision_unit=0.5,
                ratio=None,
                confidence=0.85,
                evidence_count=evidence,
                origin="inferred",
                maps_written_timing=False,
            )
        ]
    return _merge_windows(windows)


def _classify_written_for_playback(
    beat: float, span: InterpretationSpan, stream_key_value: str | None = None
) -> str:
    """Classify a written onset that may need to be sounded swung.

    Conventional swing spelling places the offbeat at 1/2 of the pair. That
    must map to playback, not be treated as a straight exception.
    """
    if span.feel == "straight" or span.ratio is None:
        return "exception"
    if span.stream_unmapped(stream_key_value):
        return "straight"
    if span.triplet_exception_at(beat, stream_key_value):
        return "triplet"
    pair = span.pair_length()
    frac = (float(beat) % pair) / pair
    if frac <= DOWNBEAT_FRAC or frac >= 1.0 - DOWNBEAT_FRAC:
        return "downbeat"
    if abs(frac - DOTTED_FRAC) <= 0.07:
        return "dotted"
    if abs(frac - STRAIGHT_FRAC) <= 0.08:
        return "swing_offbeat"
    if min(abs(frac - TRIPLET_THIRD_FRAC), abs(frac - TRIPLET_OFF_FRAC)) <= 0.05:
        return "triplet"
    if abs(frac - performed_offbeat_fraction(span.ratio)) <= SWING_OFFBEAT_WINDOW:
        # Already in performed coordinates (e.g. a locked note).
        return "exception"
    return "ambiguous"


def _classify_onset(beat: float, span: InterpretationSpan, stream_key_value: str | None = None) -> str:
    if span.feel == "straight" or span.ratio is None:
        return "exception"
    if span.stream_unmapped(stream_key_value):
        return "straight"
    if span.triplet_exception_at(beat, stream_key_value):
        return "triplet"
    pair = span.pair_length()
    frac = (float(beat) % pair) / pair
    if frac <= DOWNBEAT_FRAC or frac >= 1.0 - DOWNBEAT_FRAC:
        return "downbeat"
    target = performed_offbeat_fraction(span.ratio)
    distances = {
        "swing_offbeat": abs(frac - target),
        "dotted": abs(frac - DOTTED_FRAC),
        "straight": abs(frac - STRAIGHT_FRAC),
        "triplet": min(abs(frac - TRIPLET_THIRD_FRAC), abs(frac - TRIPLET_OFF_FRAC)),
    }
    dotted_d = distances["dotted"]
    swing_d = distances["swing_offbeat"]
    straight_d = distances["straight"]
    # Compare competitors before the swing window. 0.75 is inside a 2:1
    # ±0.11 window but is a dotted pair, not a swung offbeat.
    if dotted_d + 0.015 < swing_d and dotted_d <= 0.07:
        return "dotted"
    if straight_d + 0.02 < swing_d and straight_d <= 0.08:
        return "straight"
    if (
        distances["triplet"] + 0.02 < swing_d
        and distances["triplet"] <= 0.05
        and span.triplet_exception_at(beat, stream_key_value)
    ):
        return "triplet"
    if swing_d <= SWING_OFFBEAT_WINDOW:
        return "swing_offbeat"
    return "ambiguous"


def span_at(spans: Iterable[InterpretationSpan], beat: float) -> InterpretationSpan | None:
    """Half-open [start, end). A note exactly at a boundary belongs to the next span."""
    moment = float(beat)
    ordered = sorted(spans, key=lambda span: (span.start_beat, span.end_beat))
    for span in ordered:
        if span.contains(moment, end_inclusive=False):
            return span
    return None


def _maps_span(span: InterpretationSpan | None) -> bool:
    return (
        span is not None
        and bool(span.maps_written_timing)
        and span.feel in SWING_FEELS
        and span.ratio is not None
    )


def _map_event(event, spans: list[InterpretationSpan], *, reverse: bool):
    from mir.types import copy_event

    if getattr(event, "score_timing_locked", False):
        return event
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
    source_start = float(event.start_beat)
    source_dur = float(event.duration_beats)
    if reverse:
        lookup = source_start
        origin_start = source_start
        origin_dur = source_dur
    else:
        lookup = perf_start
        origin_start = perf_start
        origin_dur = perf_dur
    span = span_at(spans, lookup)
    stream = stream_key(event)
    changes = {
        "performed_start_beat": perf_start,
        "performed_duration_beats": perf_dur,
    }
    classifier = _classify_written_for_playback if reverse else _classify_onset
    if not _maps_span(span) or classifier(lookup, span, stream) in {
        "exception",
        "triplet",
        "dotted",
        "straight",
        "ambiguous",
    }:
        return copy_event(event, **changes)
    mapped_start = map_beat_through_swing(
        origin_start, pair_length=span.pair_length(), ratio=span.ratio, reverse=reverse
    )
    pair = span.pair_length()
    origin_end = origin_start + max(origin_dur, 1e-6)
    if origin_dur <= pair * 1.25:
            end_span = span_at(spans, origin_end) or span
            end_class = (
                classifier(origin_end, end_span, stream)
                if _maps_span(end_span)
                else "exception"
            )
            if _maps_span(end_span) and end_class in {"downbeat", "swing_offbeat"}:
                mapped_end = map_beat_through_swing(
                    origin_end,
                    pair_length=end_span.pair_length(),
                    ratio=end_span.ratio,
                    reverse=reverse,
                )
            else:
                mapped_end = mapped_start + origin_dur
            mapped_dur = max(mapped_end - mapped_start, 1e-4)
    else:
        mapped_dur = max(origin_dur, 1e-4)
    return copy_event(
        event,
        start_beat=float(mapped_start),
        duration_beats=float(mapped_dur),
        **changes,
    )


def apply_written_timing(events, spans: list[InterpretationSpan]):
    """Rewrite score beats only. Seconds and note identity stay the same."""
    parsed = spans_from_payload(spans)
    if not parsed or not events:
        return list(events)
    return [_map_event(event, parsed, reverse=False) for event in events]


def apply_playback_timing(events, spans: list[InterpretationSpan]):
    """Map written beats onto sounded beats for score MIDI / browser playback.

    Original-performance playback must not use this. Tuplets, dotted pairs,
    straight exceptions, ties that are already unsplit attacks, and notes in
    unmapped streams keep their written times.
    """
    parsed = spans_from_payload(spans)
    if not parsed or not events:
        return list(events)
    active = [span for span in parsed if _maps_span(span)]
    if not active:
        return list(events)
    return [_map_event(event, active, reverse=True) for event in events]


def mark_spans_mapping(spans: list[InterpretationSpan], *, enabled: bool) -> list[InterpretationSpan]:
    out = []
    for span in spans:
        maps = bool(enabled) and span.feel in SWING_FEELS and span.ratio is not None
        if span.maps_written_timing == maps:
            out.append(span)
            continue
        out.append(
            InterpretationSpan(
                start_beat=span.start_beat,
                end_beat=span.end_beat,
                feel=span.feel,
                subdivision_unit=span.subdivision_unit,
                ratio=span.ratio,
                confidence=span.confidence,
                evidence_count=span.evidence_count,
                origin=span.origin,
                triplet_exceptions=span.triplet_exceptions,
                unmapped_streams=span.unmapped_streams,
                maps_written_timing=maps,
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
            "maps_written_timing": False,
        }
    swing = [s for s in spans if s.feel in SWING_FEELS]
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
        "maps_written_timing": any(s.maps_written_timing and s.feel in SWING_FEELS for s in spans),
    }


def indication_for_span(span: InterpretationSpan, *, previous_feel: str | None) -> str | None:
    """Visible marking at a section boundary. Whole-piece straight stays unmarked."""
    if span.feel in SWING_FEELS and not span.maps_written_timing:
        return None
    if span.feel in {"swing_eighths", "shuffle"}:
        return "Swing"
    if span.feel == "swing_sixteenths":
        return "Swing 16ths"
    if span.feel == "straight" and previous_feel in SWING_FEELS:
        return "Straight"
    return None
