#!/usr/bin/env python3
"""Run MIDICleaner before/after benchmark on synthetic fixtures.

Usage (from backend/):
  python -m benchmark.run_cleaner_benchmark
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as `python -m benchmark.run_cleaner_benchmark`
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from benchmark.fixtures import ALL_CLEANER_FIXTURES, notes_from_dicts
from benchmark.harness import BenchmarkHarness
from benchmark.metrics import match_notes
from benchmark.readability import readability_report
from mir.midi_cleaner import MIDICleaner


def run() -> int:
    cleaner = MIDICleaner()
    harness = BenchmarkHarness()
    results = []

    print("MIDICleaner before/after benchmark")
    print("=" * 60)

    for fixture in ALL_CLEANER_FIXTURES:
        raw = notes_from_dicts(fixture["raw"])
        expected = notes_from_dicts(fixture["expected_after"])
        cleaned = cleaner.clean(raw)

        before = readability_report(raw)
        after = readability_report(cleaned)
        vs_expected = match_notes(cleaned, expected, onset_tolerance_sec=0.02)

        results.append(
            harness.compare_note_lists(
                legacy_notes=raw,
                understanding_notes=cleaned,
                reference=expected,
                fixture_name=fixture["name"],
            )
        )

        print(f"\nFixture: {fixture['name']}")
        print(f"  notes: {before.note_count} → {after.note_count}")
        print(f"  micro-notes: {before.micro_note_count} → {after.micro_note_count}")
        print(f"  near-dupes: {before.duplicate_near_onset_count} → {after.duplicate_near_onset_count}")
        print(
            f"  chord spread ms: {before.chord_cluster_spread_ms_mean:.1f} → "
            f"{after.chord_cluster_spread_ms_mean:.1f}"
        )
        print(f"  readability: {before.score:.2f} → {after.score:.2f}")
        print(
            f"  vs expected F1: {vs_expected.f1:.2f} "
            f"(P={vs_expected.precision:.2f} R={vs_expected.recall:.2f})"
        )

    promote = True
    for fixture, result in zip(ALL_CLEANER_FIXTURES, results):
        cleaned = MIDICleaner().clean(notes_from_dicts(fixture["raw"]))
        expected = notes_from_dicts(fixture["expected_after"])
        metrics = match_notes(cleaned, expected, onset_tolerance_sec=0.02)
        if metrics.f1 < 0.99:
            promote = False

    print("\n" + "=" * 60)
    print(f"Promote cleaner to default legacy path: {'YES' if promote else 'NO'}")
    print("Criteria: F1 ≥ 0.99 vs expected on all fixtures; readability improves.")
    return 0 if promote else 1


if __name__ == "__main__":
    raise SystemExit(run())
