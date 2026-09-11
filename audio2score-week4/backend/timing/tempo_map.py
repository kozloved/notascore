"""Invertible seconds ↔ beats map from explicit beat times (rubato-capable)."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

EPS = 1e-9
ROUNDTRIP_TOLERANCE_SEC = 1e-4


def sanitize_beat_times(times) -> list[float]:
    """Drop NaN/inf and non-increasing samples. Does not snap to a grid."""
    cleaned: list[float] = []
    for raw in times:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if not isfinite(value):
            continue
        if not cleaned or value > cleaned[-1] + EPS:
            cleaned.append(value)
    return cleaned


@dataclass(frozen=True)
class MusicalTimeMap:
    """Piecewise-linear map. Beat n sits at beat_times[n] seconds.

    Extrapolates using the first/last inter-beat interval. This is a
    coordinate transform, not a quantizer: fractional beats are preserved.
    """

    beat_times: tuple[float, ...]
    confidence: tuple[float, ...] = ()
    source: str = "explicit_beats"

    def __post_init__(self):
        times = list(self.beat_times)
        if len(times) < 2:
            raise ValueError("MusicalTimeMap needs at least two beat times")
        if any(not isfinite(t) for t in times):
            raise ValueError("Beat times must be finite")
        if any(b - a <= EPS for a, b in zip(times, times[1:])):
            raise ValueError("Beat times must be strictly increasing")

    @classmethod
    def from_beat_times(cls, times, *, source: str = "explicit_beats") -> "MusicalTimeMap":
        cleaned = sanitize_beat_times(times)
        if len(cleaned) < 2:
            raise ValueError("Need at least two increasing finite beat times")
        return cls(tuple(cleaned), source=source)

    @classmethod
    def from_bpm(cls, bpm: float, *, duration_sec: float, origin: float = 0.0) -> "MusicalTimeMap":
        interval = 60.0 / max(float(bpm), 1e-6)
        n = max(2, int(duration_sec / interval) + 2)
        times = tuple(origin + i * interval for i in range(n))
        return cls(times, source=f"constant_bpm:{bpm}")

    @classmethod
    def from_tempo_map(cls, tempo_map, *, duration_sec: float) -> "MusicalTimeMap":
        """Sample integer beats from an existing TempoMap (including MIDI tempi)."""
        duration = max(float(duration_sec), 1e-6)
        if tempo_map is None:
            return cls.from_bpm(120.0, duration_sec=duration)
        end_beat = float(tempo_map.seconds_to_beats(duration))
        n = max(2, int(end_beat) + 2)
        times: list[float] = []
        prev = -1.0
        for i in range(n):
            t = float(tempo_map.beats_to_seconds(float(i)))
            if not isfinite(t):
                continue
            if t <= prev + EPS:
                t = prev + 1e-4
            times.append(t)
            prev = t
        return cls.from_beat_times(times, source="tempo_map")

    def seconds_to_beats(self, time_sec: float) -> float:
        t = float(time_sec)
        if not isfinite(t):
            raise ValueError("time_sec must be finite")
        times = self.beat_times
        if t <= times[0]:
            interval = times[1] - times[0]
            return (t - times[0]) / interval
        if t >= times[-1]:
            interval = times[-1] - times[-2]
            return (len(times) - 1) + (t - times[-1]) / interval
        lo, hi = 0, len(times) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if times[mid] <= t:
                lo = mid
            else:
                hi = mid
        span = times[hi] - times[lo]
        frac = 0.0 if span <= EPS else (t - times[lo]) / span
        return lo + frac

    def beats_to_seconds(self, beat: float) -> float:
        b = float(beat)
        if not isfinite(b):
            raise ValueError("beat must be finite")
        times = self.beat_times
        if b <= 0:
            interval = times[1] - times[0]
            return times[0] + b * interval
        last = float(len(times) - 1)
        if b >= last:
            interval = times[-1] - times[-2]
            return times[-1] + (b - last) * interval
        idx = int(b)
        frac = b - idx
        return times[idx] + frac * (times[idx + 1] - times[idx])

    def interval_bpms(self) -> list[tuple[float, float]]:
        times = self.beat_times
        rows: list[tuple[float, float]] = []
        for i, (a, b) in enumerate(zip(times, times[1:])):
            dt = b - a
            if dt <= EPS:
                continue
            rows.append((float(i), 60.0 / dt))
        return rows


def assert_roundtrip(time_map: MusicalTimeMap, times: list[float], *, tol: float = ROUNDTRIP_TOLERANCE_SEC) -> None:
    for t in times:
        back = time_map.beats_to_seconds(time_map.seconds_to_beats(t))
        if abs(back - t) > tol:
            raise AssertionError(f"roundtrip {t} -> {back} exceeds {tol}")
