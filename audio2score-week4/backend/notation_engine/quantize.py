"""Snap CMR events onto a notation grid (beat space)."""

from __future__ import annotations

from dataclasses import replace

from mir.types import MusicalEvent

DEFAULT_DIVISORS = (4, 3)
MIN_DURATION = 0.25  # sixteenth
# Triplet wins only when it is clearly closer than the 16th grid. A 0.33-beat
# pickup on a straight scale otherwise becomes tuplets and 32nd ties.
TRIPLET_WIN_RATIO = 0.6
# If a note covers this fraction of the gap to the next onset, it fills that
# beat instead of becoming a dotted eighth + 16th rest.
FILL_SLOT_FRACTION = 0.55


def snap_to_grid(value: float, divisors: tuple[int, ...] = DEFAULT_DIVISORS) -> float:
    """Snap a quarterLength to 1/divisor grids. Prefer binary (4) on ties."""
    if value <= 0:
        return 0.0
    binary = divisors[0]
    best = round(value * binary) / binary
    best_err = abs(best - value)
    for divisor in divisors[1:]:
        snapped = round(value * divisor) / divisor
        err = abs(snapped - value)
        if err + 1e-9 < best_err * TRIPLET_WIN_RATIO:
            best, best_err = snapped, err
    return float(best)


def beat_phase_offset(starts: list[float], steps: int = 48) -> float:
    """Shift that puts typical onsets onto integer beats (downbeat phase)."""
    if len(starts) < 3:
        return 0.0
    best_phase = 0.0
    best_err = float("inf")
    for i in range(-steps // 2, steps // 2):
        phase = i / steps
        err = 0.0
        for start in starts:
            shifted = start - phase
            err += abs(shifted - round(shifted))
        err /= len(starts)
        if err < best_err:
            best_err = err
            best_phase = phase
    if best_err > 0.22:
        return 0.0
    return float(best_phase)


def quantize_events(
    events: list[MusicalEvent],
    divisors: tuple[int, ...] = DEFAULT_DIVISORS,
    min_duration: float = MIN_DURATION,
) -> list[MusicalEvent]:
    if not events:
        return []
    phase = beat_phase_offset([e.start_beat for e in events])
    shifted = [
        replace(ev, start_beat=ev.start_beat - phase) for ev in events
    ]
    starts = sorted({round(ev.start_beat, 6) for ev in shifted})

    def _next_start(start: float) -> float | None:
        for later in starts:
            if later > start + 1e-6:
                return later
        return None

    quantized: list[MusicalEvent] = []
    for ev in shifted:
        start_raw = ev.start_beat
        end_raw = ev.start_beat + ev.duration_beats
        nxt = _next_start(start_raw)
        duration_raw = ev.duration_beats
        if nxt is not None:
            slot = nxt - start_raw
            if slot > 0 and end_raw <= nxt + 0.06 and duration_raw >= FILL_SLOT_FRACTION * slot:
                duration_raw = slot
        elif duration_raw >= 0.75:
            duration_raw = max(duration_raw, float(round(duration_raw)))
        start = snap_to_grid(start_raw, divisors)
        end = snap_to_grid(start_raw + duration_raw, divisors)
        duration = max(min_duration, end - start)
        quantized.append(replace(ev, start_beat=start, duration_beats=duration))
    return sorted(quantized, key=lambda e: (e.start_beat, e.pitch))
