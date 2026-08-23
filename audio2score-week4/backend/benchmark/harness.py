"""Benchmark harness: legacy vs understanding pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from benchmark.metrics import NoteMetrics, match_notes
from mir.types import NoteEvent


@dataclass
class BenchmarkResult:
    fixture: str
    legacy_note_count: int = 0
    understanding_note_count: int = 0
    cross_pipeline_f1: float = 0.0
    legacy_vs_reference: NoteMetrics | None = None
    understanding_vs_reference: NoteMetrics | None = None
    details: dict = field(default_factory=dict)


class BenchmarkHarness:
    """Compare pipelines on fixtures with optional reference MIDI notes."""

    def compare_note_lists(
        self,
        legacy_notes: list[NoteEvent],
        understanding_notes: list[NoteEvent],
        reference: list[NoteEvent] | None = None,
        fixture_name: str = "unknown",
    ) -> BenchmarkResult:
        cross = match_notes(understanding_notes, legacy_notes)
        result = BenchmarkResult(
            fixture=fixture_name,
            legacy_note_count=len(legacy_notes),
            understanding_note_count=len(understanding_notes),
            cross_pipeline_f1=cross.f1,
        )
        if reference:
            result.legacy_vs_reference = match_notes(legacy_notes, reference)
            result.understanding_vs_reference = match_notes(
                understanding_notes, reference
            )
        return result

    def should_promote(
        self,
        results: list[BenchmarkResult],
        min_f1_vs_legacy: float = 0.85,
        min_reference_f1: float = 0.0,
    ) -> bool:
        if not results:
            return False
        for r in results:
            if r.cross_pipeline_f1 < min_f1_vs_legacy:
                return False
            if r.understanding_vs_reference and min_reference_f1 > 0:
                if r.understanding_vs_reference.f1 < min_reference_f1:
                    return False
        return True
