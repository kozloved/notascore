"""Printed tempo is not performance tempo.

Rubato produces a dense PerformanceTempoMap. Score annotations fire only on
persistent trends, not per-bar jitter. Gradual slowing becomes rit; a held
slower plateau becomes a metronome mark; returning near the opening tempo
becomes a tempo. Playback keeps the full curve separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median


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

    opening = float(beat_bpms[0][1])
    current = opening
    marks = [
        ScoreTempoAnnotation(
            float(beat_bpms[0][0]), int(round(opening)), "metronome", "opening_tempo"
        )
    ]
    pending: list[tuple[float, float]] = []
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
        values = [v for _, v in pending]
        new_bpm = float(median(values))
        start = pending[0][0]
        spread = (max(values) - min(values)) / max(abs(median(values)), 1e-6)
        near_opening = abs(new_bpm - opening) / max(opening, 1e-6) < min_change_ratio
        gradual = len(values) >= 4 and spread >= min_change_ratio * 0.5
        if near_opening and new_bpm >= current:
            marks.append(
                ScoreTempoAnnotation(start, None, "a_tempo", "return_to_opening")
            )
            current = opening
        elif new_bpm < current and gradual:
            # Continuous slowing inside the held region — expressive marking.
            marks.append(
                ScoreTempoAnnotation(start, None, "rit", "persistent_slowing")
            )
            current = new_bpm
        else:
            # Discrete new plateau (faster or slower). Print BPM, not Italian.
            marks.append(
                ScoreTempoAnnotation(
                    start,
                    int(round(new_bpm)),
                    "metronome",
                    "persistent_tempo_region",
                )
            )
            current = new_bpm
        pending = []
    return marks
