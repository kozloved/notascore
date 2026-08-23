"""Readability + cleaner before/after metrics."""

from __future__ import annotations

from dataclasses import dataclass

from mir.types import NoteEvent


@dataclass
class ReadabilityReport:
    note_count: int
    micro_note_count: int
    duplicate_near_onset_count: int
    chord_cluster_spread_ms_mean: float
    score: float


def count_micro_notes(notes: list[NoteEvent], min_duration_sec: float = 0.04) -> int:
    return sum(1 for n in notes if n.duration < min_duration_sec)


def count_near_duplicate_onsets(
    notes: list[NoteEvent], threshold_sec: float = 0.025
) -> int:
    by_pitch: dict[int, list[NoteEvent]] = {}
    for n in notes:
        by_pitch.setdefault(n.pitch, []).append(n)
    dupes = 0
    for group in by_pitch.values():
        group = sorted(group, key=lambda n: n.start_time)
        for a, b in zip(group, group[1:]):
            if abs(b.start_time - a.start_time) <= threshold_sec:
                dupes += 1
    return dupes


def mean_chord_cluster_spread_ms(
    notes: list[NoteEvent], window_sec: float = 0.05
) -> float:
    if len(notes) < 2:
        return 0.0
    sorted_notes = sorted(notes, key=lambda n: n.start_time)
    spreads: list[float] = []
    i = 0
    while i < len(sorted_notes):
        start = sorted_notes[i].start_time
        j = i + 1
        while j < len(sorted_notes) and sorted_notes[j].start_time - start <= window_sec:
            j += 1
        cluster = sorted_notes[i:j]
        if len(cluster) >= 2:
            spreads.append((cluster[-1].start_time - cluster[0].start_time) * 1000)
        i = j
    if not spreads:
        return 0.0
    return sum(spreads) / len(spreads)


def readability_report(
    notes: list[NoteEvent],
    min_duration_sec: float = 0.04,
) -> ReadabilityReport:
    micro = count_micro_notes(notes, min_duration_sec)
    dupes = count_near_duplicate_onsets(notes)
    spread = mean_chord_cluster_spread_ms(notes)
    # Higher is better: penalize micro-notes, dupes, and chord spread.
    score = 1.0
    score -= min(0.4, micro * 0.1)
    score -= min(0.3, dupes * 0.1)
    score -= min(0.3, spread / 100.0)
    return ReadabilityReport(
        note_count=len(notes),
        micro_note_count=micro,
        duplicate_near_onset_count=dupes,
        chord_cluster_spread_ms_mean=spread,
        score=max(0.0, score),
    )
