"""Distribution helpers and musical characteristic bins."""

from __future__ import annotations

from statistics import mean, median, pstdev
from typing import Any, Sequence


def percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    if f == c:
        return xs[f]
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def distribution(values: Sequence[float]) -> dict[str, float | None]:
    xs = [float(v) for v in values]
    if not xs:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "std": None,
            "p10": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    return {
        "count": len(xs),
        "mean": mean(xs),
        "median": median(xs),
        "std": pstdev(xs) if len(xs) > 1 else 0.0,
        "p10": percentile(xs, 10),
        "p25": percentile(xs, 25),
        "p75": percentile(xs, 75),
        "p90": percentile(xs, 90),
        "p95": percentile(xs, 95),
        "min": min(xs),
        "max": max(xs),
    }


def tempo_bin(bpm: float | None) -> str:
    if bpm is None:
        return "unknown"
    if bpm < 80:
        return "<80"
    if bpm < 110:
        return "80-110"
    if bpm < 140:
        return "110-140"
    if bpm < 170:
        return "140-170"
    return ">=170"


def duration_bin_ms(duration_sec: float) -> str:
    ms = duration_sec * 1000.0
    if ms < 125:
        return "<125ms"
    if ms < 250:
        return "125-250ms"
    if ms < 500:
        return "250-500ms"
    if ms < 1000:
        return "500-1000ms"
    return ">=1000ms"


def register_bin(pitch: int) -> str:
    if pitch < 48:
        return "bass_<48"
    if pitch <= 71:
        return "middle_48-71"
    return "treble_>=72"


def polyphony_bin(n: int) -> str:
    if n <= 1:
        return "1"
    if n == 2:
        return "2"
    if n == 3:
        return "3"
    return "4+"


def pitch_error_bucket(semitones: int) -> str:
    a = abs(int(semitones))
    if a == 0:
        return "exact"
    if a == 1:
        return "±1"
    if a == 2:
        return "±2"
    if a % 12 == 0:
        return "octave"
    return "larger"


def bin_counts(items: Sequence[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """items: (bin_label, classification) → nested counts."""
    out: dict[str, dict[str, int]] = {}
    for b, cls in items:
        out.setdefault(b, {})
        out[b][cls] = out[b].get(cls, 0) + 1
    return out


def summarize_bins(bin_map: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    rows = []
    for label, counts in sorted(bin_map.items()):
        total = sum(counts.values())
        missed = counts.get("MISSED", 0)
        matched = counts.get("MATCH", 0) + counts.get("OFFSET_ERROR", 0)
        rows.append(
            {
                "bin": label,
                "total": total,
                "matched": matched,
                "missed": missed,
                "classes": counts,
                "miss_rate": (missed / total) if total else None,
            }
        )
    return rows
