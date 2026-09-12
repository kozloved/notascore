# Phase 3 baseline and FP gate (2026-09-12)

## Frozen harness baseline

- Name: `phase3-dev-fixture`
- Path: `audio2score-week4/backend/evaluation/baselines/phase3-dev-fixture.json`
- Case: synthetic `development/piano_quarters_120` (`evaluation.runner --prepare-fixture`)
- Pipeline: Basic Pitch + conservative validation + performance quantization
- Federation: OFF
- Primary metric: `onset_pitch_f1 = 1.000` on the synthetic fixture

Reproduce:

```bash
cd audio2score-week4/backend
.venv/bin/python -m evaluation.runner --prepare-fixture --compare-baseline phase3-dev-fixture
```

## Highest-impact measured failure (historical Case1–3)

From `evaluation/results/20260827T064145Z/forensics_report.md`:

- Stage: transcription (Basic Pitch)
- Taxonomy: 31 false positives vs 18 false negatives
- Aggregate raw onset+pitch F1 ≈ 0.142

## Focused improvement (gated)

`mir/confidence_gate.py` drops notes below `NOTASCORE_MIN_NOTE_CONFIDENCE` (default 0.45)
when `NOTASCORE_DROP_LOW_CONFIDENCE=1`.

- Default: OFF (production path unchanged)
- Wired after Basic Pitch transcription in `mir/pipeline.py`
- Unit proof: `tests/test_phase3_confidence_gate.py`
- Does not invent attacks; only removes low-confidence predicted notes

Enable for comparison runs only after corpus gates pass:

```bash
NOTASCORE_DROP_LOW_CONFIDENCE=1 \
  .venv/bin/python -m evaluation.runner --prepare-fixture --compare-baseline phase3-dev-fixture
```

Real-audio Case1–3 deltas remain deferred to a non-sandboxed corpus rerun with
licensed references; this commit freezes the harness baseline and the gated FP filter.
