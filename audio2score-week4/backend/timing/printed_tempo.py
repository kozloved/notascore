"""Printed tempo is not performance tempo.

Rubato produces a dense PerformanceTempoMap. Score annotations fire only on
persistent trends, not per-bar jitter.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreTempoAnnotation:
    beat: float
    bpm: int | None
    mark: str  # metronome | rit | a_tempo
    reason: str


def printed_tempo_annotations(
    beat_bpms: list[tuple[float, float]],
    *,
    min_change_ratio: float = 0.12,
    min_hold_beats: float = 8.0,
) -> list[ScoreTempoAnnotation]:
    """Collapse a performance BPM series into sparse printed marks."""
    if not beat_bpms:
        return []
    from statistics import median

    opening = float(beat_bpms[0][1])
    current = opening
    marks = [ScoreTempoAnnotation(float(beat_bpms[0][0]), int(round(opening)),
                                  "metronome", "opening_tempo")]
    pending = []
    for beat, bpm in beat_bpms[1:]:
        if abs(bpm - current) / max(current, 1e-6) < min_change_ratio:
            pending = []
            continue
        # A tempo excursion must itself persist; time spent at the previous
        # tempo is not evidence that a single slow beat is a new region.
        if pending and abs(bpm - median(v for _, v in pending)) / max(bpm, 1e-6) >= min_change_ratio:
            pending = []
        pending.append((float(beat), float(bpm)))
        if beat - pending[0][0] < min_hold_beats:
            continue
        new_bpm = float(median(v for _, v in pending))
        start = pending[0][0]
        if new_bpm < current:
            marks.append(ScoreTempoAnnotation(start, None, "rit", "persistent_slowing"))
        marks.append(ScoreTempoAnnotation(start, int(round(new_bpm)),
                                         "metronome", "persistent_tempo_region"))
        current = new_bpm
        pending = []
    return marks
