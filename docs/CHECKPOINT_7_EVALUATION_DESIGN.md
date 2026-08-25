# Checkpoint 7 — Real-World Audio Evaluation Infrastructure

**Status:** Design (Checkpoint 7). Measurement only — no production algorithm changes.

**Baseline commit:** `2460047` (stable engine). Branch: `cursor/checkpoint-7-realworld-eval-279b`.

**Existing related work:** `benchmark/realworld/` remains an observational local-audio harness. Checkpoint 7 adds a separate `evaluation/` package with corpus splits, stage diagnostics, and baselines. Both may coexist; this checkpoint does not replace the synthetic `benchmark/` gate.

---

## 1. Current pipeline stages

Canonical Fast path (`UnderstandingPipeline.transcribe`):

```
Audio
  → AudioNormalizer
  → InstrumentClassifier / AudioSegmenter
  → Transcription backend (Basic Pitch)     → RAW notes
  → MIDICleaner                             → CLEANED notes
  → PianoAnalyzer (optional velocity/pedal)
  → tempo / beat / MeterArbitrator
  → CMR events + HandSeparator + VoiceSeparator + dynamics/articulation/phrases
                                            → STRUCTURED events
  → NotationPlan / NotationWriter           → MusicXML (+ score MIDI)
```

Inspectable production artifacts already written under `bp_<job_id>/`:

| Artifact | Meaning |
|---|---|
| `{id}_norm.wav` | Normalized audio fed to Basic Pitch |
| `{id}.raw.mid` | Post-clean / post-MIR notes (seconds) |
| `{id}.score.mid` | Notation-oriented MIDI |
| `{id}.musicxml` | Final score |
| `{id}.debug.json` | Counts, cleaner suppressions, meter, hands |

**Constraint:** Checkpoint 7 does **not** modify Basic Pitch, MeterArbitrator, Cleaner, HandSeparator, NotationPlanner, quantization, or voice separation. Stage MIDIs for raw/cleaned are captured by re-invoking those production components from the evaluation package (same code paths, no algorithm edits).

---

## 2. Proposed evaluator architecture

Package root (run from `audio2score-week4/backend`):

```
evaluation/
  runner.py          CLI entry (python -m evaluation.runner)
  corpus.py          Case discovery, splits, paired-render leakage checks
  schema.py          case.yaml / optional metadata loading
  normalize.py       Reference MIDI → comparable note events (no mutation)
  matching.py        Configurable onset/pitch/offset matching
  metrics.py         Note / meter / tempo / hand / pipeline metrics
  stages.py          Per-stage capture + first-degradation diagnostics
  execute.py         One-case pipeline run + metric assembly
  baselines.py       Save / compare named baselines
  report.py          results.json + report.md (+ per-case report.md)
  fixture.py         Repo-safe synthetic case generator
  development/       DAW cases (WAV/MIDI gitignored)
  holdout/
  real_world/
  results/           Run outputs (gitignored)
  baselines/         Named baseline snapshots (gitignored by default)
```

Flow per case:

```
case.yaml + input audio + reference.mid
  → normalize reference (in memory)
  → UnderstandingPipeline (production, read-only)
  → stage capture (raw / cleaned / structured / musicxml)
  → match each stage vs reference
  → metrics.json + diagnostics.json + report.md
  → aggregate results.json / report.md
```

---

## 3. Corpus format

```
evaluation/
  development/<case_id>/
    input.wav          # or .mp3 / .flac / .mid (gitignored audio)
    reference.mid      # ground-truth performance (gitignored)
    case.yaml          # optional metadata (may be committed as templates)
  holdout/...
  real_world/...
```

**Minimum files:** audio input + `reference.mid`. Metadata is optional.

Example `case.yaml`:

```yaml
id: piano_sixteenth_120
title: Sixteenth note threshold
instrument: piano
reference:
  midi: reference.mid
expected:
  meter: "4/4"
  tempo_bpm: 120
tags: [piano, duration, sixteenth]
# Optional: shared performance identity for paired renders
performance_id: piano_sixteenth_120_perf
```

**Splits**

| Split | Purpose |
|---|---|
| `development` | Diagnose failures; guide future work |
| `holdout` | Generalization check — do not tune against individual cases |
| `real_world` | Real recordings / hard practical material |

**Paired renders:** Multiple audio renders may share one logical reference via `performance_id` (or identical resolved reference path). The same performance **must not** appear in both `development` and `holdout`.

---

## 4. Metric definitions

Tolerances are configurable (defaults in `evaluation/defaults.py`):

- Onset tolerance: 50 ms (musical, not exact timestamps)
- Offset tolerance: 100 ms (when offset F1 is computed)
- Pitch tolerance: 0 semitones
- Tempo absolute error threshold for “match”: 3 BPM
- Baseline regression epsilon: 0.01 F1 (insignificant float noise)

**Notes (per stage and final):** reference/predicted counts, matched, FP, FN; onset P/R/F1; onset+pitch P/R/F1; onset+pitch+offset F1 when meaningful; mean/median onset error (ms); pitch error rate; duration error (ms).

**Meter:** predicted, expected (from YAML or reference MIDI time signature), confidence, reason, status `correct` | `incorrect` | `not_evaluated`.

**Tempo:** reference BPM (YAML or MIDI tempo map), predicted BPM, absolute error.

**Hands:** When reference tracks provide LH/RH labels — accuracy, LH→RH / RH→LH confusion. Otherwise `NOT_EVALUATED` (never invent ground truth).

**Pipeline:** raw/cleaned/structured note counts, NotationPlan success, `fallback_used`, `notation_path`, cleaner suppressions, MusicXML success.

---

## 5. Baseline strategy

```bash
python -m evaluation.runner --split development --save-baseline checkpoint-7-baseline
python -m evaluation.runner --split development --compare-baseline checkpoint-7-baseline
```

Per case vs baseline primary metric (onset+pitch F1): `IMPROVED` | `REGRESSED` | `UNCHANGED` | `NEW`. Aggregate deltas printed and written into the report. Holdout reports are clearly marked **HOLDOUT EVALUATION**.

---

## 6. Files to change / add

| Path | Action |
|---|---|
| `docs/CHECKPOINT_7_EVALUATION_DESIGN.md` | Design (this file) |
| `audio2score-week4/backend/evaluation/**` | New evaluation package |
| `audio2score-week4/backend/tests/test_evaluation_*.py` | Focused unit/integration tests |
| `audio2score-week4/backend/requirements.txt` | Add `PyYAML` for manifests |
| `audio2score-week4/.gitignore` | Ignore corpus audio/MIDI + results |

**Explicitly not changed:** `mir/*` algorithm modules, Basic Pitch adapter logic, MeterArbitrator, Cleaner, HandSeparator, NotationPlanner, quantizer, voice separator, production writer behavior.

**Preserved:** Existing `benchmark/` synthetic suite and `benchmark/realworld/` observational harness + their tests.

---

## 7. CLI

```bash
python -m evaluation.runner --split development
python -m evaluation.runner --split holdout
python -m evaluation.runner --split real_world
python -m evaluation.runner --case piano_001
python -m evaluation.runner --all
python -m evaluation.runner --prepare-fixture   # repo-safe synthetic case
```

---

## 8. Success criteria

- New DAW case = drop files + optional YAML; no Python required
- Stage diagnostics identify the first degrading pipeline stage
- WAV/MIDI corpus gitignored; fixtures generated for CI
- `pytest`, `benchmark.runner --mode midi`, `benchmark.runner --mode fast` still pass
- No production transcription algorithm edits
