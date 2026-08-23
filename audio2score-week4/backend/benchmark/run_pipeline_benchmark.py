#!/usr/bin/env python3
"""Compare legacy vs understanding pipeline on shared fixtures.

Usage (from backend/):
  python -m benchmark.run_pipeline_benchmark
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Match production enhanced-legacy settings for a fair comparison.
os.environ["TRANSCRIPTION_USE_CLEANER"] = "1"
os.environ["TRANSCRIPTION_USE_NORMALIZER"] = "1"
os.environ["TRANSCRIPTION_USE_BEAT_TRACKER"] = "1"
os.environ["TRANSCRIPTION_USE_PIANO_ANALYZER"] = "1"
os.environ["TRANSCRIPTION_USE_MIR_LAYERS"] = "1"

from benchmark.fixtures import ALL_CLEANER_FIXTURES, notes_from_dicts
from benchmark.harness import BenchmarkHarness
from benchmark.note_extract import notes_from_midi
from benchmark.readability import readability_report
from mir.pipeline import UnderstandingPipeline
from transcription import BasicPitchEngine


def _write_test_audio(path: Path, duration_sec: float = 2.0) -> None:
    sr = 22050
    t = np.linspace(0, duration_sec, int(sr * duration_sec))
    sf.write(str(path), 0.2 * np.sin(2 * np.pi * 440 * t), sr)


def run() -> int:
    harness = BenchmarkHarness()
    results = []

    print("Legacy vs understanding pipeline benchmark")
    print("=" * 60)

    for fixture in ALL_CLEANER_FIXTURES:
        raw_notes = notes_from_dicts(fixture["raw"])
        fixture_name = fixture["name"]

        with patch(
            "adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes",
            return_value=list(raw_notes),
        ):
            audio_dir = Path("/tmp/notascore_benchmark")
            audio_dir.mkdir(exist_ok=True)
            audio_path = audio_dir / f"{fixture_name}.wav"
            _write_test_audio(audio_path)

            legacy_job = f"legacy-{fixture_name}"
            understanding_job = f"understanding-{fixture_name}"

            BasicPitchEngine().transcribe(audio_path, legacy_job)
            UnderstandingPipeline().transcribe(audio_path, understanding_job)

            legacy_midi = audio_dir / f"bp_{legacy_job}" / f"{legacy_job}.mid"
            understanding_midi = (
                audio_dir / f"bp_{understanding_job}" / f"{understanding_job}.mid"
            )

            legacy_out = notes_from_midi(legacy_midi)
            understanding_out = notes_from_midi(understanding_midi)

            result = harness.compare_note_lists(
                legacy_notes=legacy_out,
                understanding_notes=understanding_out,
                reference=notes_from_dicts(fixture.get("expected_after", fixture["raw"])),
                fixture_name=fixture_name,
            )
            results.append(result)

            leg_read = readability_report(legacy_out)
            und_read = readability_report(understanding_out)

            print(f"\nFixture: {fixture_name}")
            print(
                f"  notes: legacy={result.legacy_note_count} "
                f"understanding={result.understanding_note_count}"
            )
            print(f"  cross-pipeline F1: {result.cross_pipeline_f1:.2f}")
            print(
                f"  readability: legacy={leg_read.score:.2f} "
                f"understanding={und_read.score:.2f}"
            )
            if result.understanding_vs_reference:
                ref = result.understanding_vs_reference
                print(
                    f"  understanding vs reference F1: {ref.f1:.2f} "
                    f"(P={ref.precision:.2f} R={ref.recall:.2f})"
                )

    promote = harness.should_promote(results, min_f1_vs_legacy=0.85)
    print("\n" + "=" * 60)
    print(f"Promote understanding pipeline: {'YES' if promote else 'NO'}")
    print("Criteria: cross-pipeline F1 ≥ 0.85 on all fixtures.")
    return 0 if promote else 1


if __name__ == "__main__":
    raise SystemExit(run())
