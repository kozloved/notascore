"""Invertible seconds ↔ beats map from explicit beat times (rubato-capable)."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor, isfinite

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

    def for_score(self, first_note_sec: float, *, downbeat_times=(), beats_per_bar=None):
        """Translate the origin by whole beats, preserving the rubato curve.

        Only measured downbeats with matching tracker bar units establish bar
        phase. Without that evidence, retain the existing phase and extend
        backwards if necessary; an offbeat first note stays an offbeat.
        """
        first = self.seconds_to_beats(first_note_sec)
        start = min(0, floor(first))
        if beats_per_bar in (2, 3, 4):
            indices = [self.seconds_to_beats(t) for t in sanitize_beat_times(downbeat_times)]
            indices = [round(b) for b in indices if abs(b - round(b)) < 0.05]
            # Inconsistent downbeat evidence must not rotate the bar grid.
            if indices and all((b - indices[0]) % beats_per_bar == 0 for b in indices):
                anchor = indices[0]
                start = anchor - ceil((anchor - first) / beats_per_bar) * beats_per_bar
        if start == 0:
            return self
        end = max(len(self.beat_times), start + 2)
        return MusicalTimeMap(
            tuple(self.beats_to_seconds(i) for i in range(start, end)),
            source=self.source,
        )

    def with_stride(self, stride: int) -> "MusicalTimeMap":
        """Keep every Nth beat (0.5× tempo uses stride=2). Seconds unchanged."""
        step = max(1, int(stride))
        times = self.beat_times[::step]
        if len(times) < 2:
            return self
        return MusicalTimeMap(times, source=f"{self.source}:stride{step}")

    def with_subdivisions(self, factor: int) -> "MusicalTimeMap":
        """Insert equal subdivisions between beats (2.0× tempo uses factor=2)."""
        n = max(1, int(factor))
        if n == 1:
            return self
        times: list[float] = []
        for a, b in zip(self.beat_times, self.beat_times[1:]):
            times.append(a)
            span = b - a
            for k in range(1, n):
                times.append(a + span * k / n)
        times.append(self.beat_times[-1])
        return MusicalTimeMap.from_beat_times(times, source=f"{self.source}:x{n}")


def assert_roundtrip(time_map: MusicalTimeMap, times: list[float], *, tol: float = ROUNDTRIP_TOLERANCE_SEC) -> None:
    for t in times:
        back = time_map.beats_to_seconds(time_map.seconds_to_beats(t))
        if abs(back - t) > tol:
            raise AssertionError(f"roundtrip {t} -> {back} exceeds {tol}")
