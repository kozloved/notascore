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
    marks: list[ScoreTempoAnnotation] = []
    start_beat, region_bpm = beat_bpms[0]
    for beat, bpm in beat_bpms[1:]:
        held = beat - start_beat >= min_hold_beats
        changed = abs(bpm - region_bpm) / max(region_bpm, 1e-6) >= min_change_ratio
        if changed and held:
            marks.append(
                ScoreTempoAnnotation(
                    beat=start_beat,
                    bpm=int(round(region_bpm)),
                    mark="metronome",
                    reason="persistent_tempo_region",
                )
            )
            if bpm < region_bpm:
                marks.append(
                    ScoreTempoAnnotation(
                        beat=beat,
                        bpm=None,
                        mark="rit",
                        reason="persistent_slowing",
                    )
                )
            start_beat, region_bpm = beat, bpm
    last_bpm = int(round(region_bpm))
    opening = int(round(beat_bpms[0][1]))
    if marks and last_bpm == opening and any(m.mark == "rit" for m in marks):
        marks.append(
            ScoreTempoAnnotation(
                beat=start_beat,
                bpm=None,
                mark="a_tempo",
                reason="return_to_opening_tempo",
            )
        )
    else:
        marks.append(
            ScoreTempoAnnotation(
                beat=start_beat,
                bpm=last_bpm,
                mark="metronome",
                reason="persistent_tempo_region",
            )
        )
    # Drop adjacent duplicates at the same printed integer.
    collapsed: list[ScoreTempoAnnotation] = []
    for mark in marks:
        if collapsed and collapsed[-1].bpm == mark.bpm and collapsed[-1].mark == mark.mark:
            continue
        collapsed.append(mark)
    return collapsed
