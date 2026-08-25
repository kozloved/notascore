"""Repo-safe synthetic fixture for smoke-evaluating the harness."""

from __future__ import annotations

from pathlib import Path

from benchmark.fixtures.audio import render_notes_wav
from benchmark.fixtures.catalog import all_cases
from benchmark.fixtures.generate import note_to_ref, write_midi
from evaluation.corpus import PACKAGE_DIR

FIXTURE_ID = "piano_quarters_120"
DEFAULT_SPLIT = "development"


def fixture_case_yaml() -> str:
    return """\
id: piano_quarters_120
title: Synthetic C major quarters (repo-safe fixture)
instrument: piano
reference:
  midi: reference.mid
expected:
  meter: "4/4"
  tempo_bpm: 100
tags:
  - piano
  - duration
  - quarter
  - fixture
notes: >
  Generated additive-synthesis fixture for Checkpoint 7 harness validation.
  Not a real recording. Safe to regenerate locally.
"""


def prepare_fixture(
    *,
    split: str = DEFAULT_SPLIT,
    root: Path | None = None,
) -> Path:
    """Write one synthetic WAV + reference MIDI + case.yaml under a split."""
    base = Path(root) if root is not None else PACKAGE_DIR
    case_dir = base / split / FIXTURE_ID
    case_dir.mkdir(parents=True, exist_ok=True)

    spec = next(c for c in all_cases() if c.case_id == "c_major_quarters")
    notes = [note_to_ref(n, float(spec.tempo_bpm)) for n in spec.notes]
    render_notes_wav(notes, case_dir / "input.wav", sample_rate=22050)
    write_midi(spec, case_dir / "reference.mid")
    (case_dir / "case.yaml").write_text(fixture_case_yaml(), encoding="utf-8")
    return case_dir
