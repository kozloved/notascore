"""Snap CMR events onto a notation grid (beat space)."""

from __future__ import annotations

from dataclasses import replace

from mir.types import MusicalEvent

DEFAULT_DIVISORS = (4, 3)
MIN_DURATION = 0.25  # sixteenth


def snap_to_grid(value: float, divisors: tuple[int, ...] = DEFAULT_DIVISORS) -> float:
    """Snap a quarterLength to 1/divisor grids. Prefer binary (4) on ties."""
    if value <= 0:
        return 0.0
    best = round(value * divisors[0]) / divisors[0]
    best_err = abs(best - value)
    for divisor in divisors[1:]:
        snapped = round(value * divisor) / divisor
        err = abs(snapped - value)
        if err + 1e-9 < best_err:
            best, best_err = snapped, err
    return float(best)


def quantize_events(
    events: list[MusicalEvent],
    divisors: tuple[int, ...] = DEFAULT_DIVISORS,
    min_duration: float = MIN_DURATION,
) -> list[MusicalEvent]:
    quantized: list[MusicalEvent] = []
    for ev in events:
        start = snap_to_grid(ev.start_beat, divisors)
        end = snap_to_grid(ev.start_beat + ev.duration_beats, divisors)
        duration = max(min_duration, end - start)
        quantized.append(
            replace(ev, start_beat=start, duration_beats=duration)
        )
    return sorted(quantized, key=lambda e: (e.start_beat, e.pitch))
