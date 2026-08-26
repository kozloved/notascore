# Checkpoint 7B — Two-Reference Evaluation

**Status:** Measurement / infrastructure only. No production algorithm changes.

**Branch:** `cursor/checkpoint-7b-two-reference-eval`  
**Starting commit:** `6f3cc65` (NotaTestSamples fixtures present)  
**Run used for corpus numbers below:** `evaluation/results/20260826T184619Z`

---

## Architecture

Checkpoint 7 scored every pipeline stage against a single `reference.mid`.
Real DAW workflows provide **two** immutable MIDI truths:

| File | Meaning | Used for |
|---|---|---|
| `reference_raw.mid` | Exact performance MIDI that rendered `input.wav` | Pitch / onset / offset F1, FP/FN, raw + cleaner (+ post-piano) stages |
| `reference_score.mid` | Intended quantized musical score | Structured / score-level comparison when meaningful |

```
REFERENCE_RAW ──► transcription ──► cleaner ──► post_piano
REFERENCE_SCORE ──────────────────────────────► structured (when evaluable)
```

Raw stages are **never** compared to `reference_score.mid`.
Structured notes are **never** compared to the raw performance MIDI unless both
roles resolved to the same legacy `reference.mid` (explicit fallback).

Results use explicit namespaces:

```yaml
metrics:
  raw: { onset_f1, onset_pitch_f1, onset_pitch_offset_f1, false_positives, ... }
  cleaner: { ... }
  cleaner_delta: { onset_pitch_f1, onset_f1 }
  score: { status: evaluated|unavailable, quantized_note_f1, ... }
```

If score comparison is not meaningful, the harness reports
`score_evaluation: unavailable` with a reason — it does **not** invent a score F1.

---

## Reference precedence

For each case directory (and optional `case.yaml`):

### `reference_raw`

1. Manifest `reference.raw` / `reference_raw` / `reference_raw_midi`
2. Filename `reference_raw.mid` / `.midi`
3. Pattern `*_raw.mid` / `*-raw.mid`
4. Legacy fallback: `reference.mid` / `ref.mid`

### `reference_score`

1. Manifest `reference.score` / `reference_score` / …
2. Filename `reference_score.mid` / `.midi`
3. Pattern `*_q.mid`, `*_score.mid`, `*_quant*.mid`
4. Legacy fallback: `reference.mid` / `ref.mid`

If **both** are missing → case is skipped (`missing reference MIDI`).

Every run reports:

- `raw_source` / `score_source`
- `raw_legacy_fallback` / `score_legacy_fallback`
- `same_file`
- `raw_note_count` / `score_note_count`

---

## Backward compatibility

| Layout | Files | Behavior |
|---|---|---|
| A Legacy | `input.wav` + `reference.mid` | Both roles fall back to `reference.mid`; `same_file=true` |
| B Raw-only | `reference_raw.mid` | Raw metrics only; score `unavailable` |
| C Score-only | `reference_score.mid` | Score metrics only; raw stages not scored vs score MIDI |
| D Preferred | both | Full dual evaluation |

Checkpoint 7 fixture `piano_quarters_120` (legacy `reference.mid`) still runs.

Nested discovery is supported (e.g. `development/NotaTestSamples/Case1`).

---

## Test corpus results

Three real DAW cases under `evaluation/development/NotaTestSamples/`
(discovered automatically; IDs not hardcoded). References were **not** renamed,
moved, or mutated. Manifests map DAW filenames → raw/score roles.

### Case1 — 160 F melody piano

| Field | Value |
|---|---|
| Raw / score note counts | 7 / 7 |
| References differ | yes (distinct files) |
| Expected meter / tempo | 4/4 @ 160 bpm |
| Predicted meter / tempo | 4/4 @ 80.1 bpm |
| Raw onset F1 | 0.250 |
| Raw onset+pitch F1 | 0.125 |
| Raw onset+pitch+offset F1 | 0.000 |
| FP / FN | 8 / 6 |
| Cleaner onset+pitch F1 | 0.125 (Δ 0.000) |
| Score quantized note F1 | 0.125 |
| Earliest quality loss | **transcription (Basic Pitch)** — F1 already 0.12; cleaner unchanged |

### Case2 — 138 C chords piano

| Field | Value |
|---|---|
| Raw / score note counts | 14 / 14 |
| References differ | yes |
| Expected meter / tempo | 4/4 @ 138 bpm |
| Predicted meter / tempo | 4/4 @ 68.75 bpm |
| Raw onset F1 | 0.200 |
| Raw onset+pitch F1 | 0.200 |
| Raw onset+pitch+offset F1 | 0.000 |
| FP / FN | 13 / 11 |
| Cleaner onset+pitch F1 | 0.200 (Δ 0.000) |
| Score quantized note F1 | 0.200 |
| Earliest quality loss | **transcription (Basic Pitch)** — F1 0.20; cleaner unchanged |

### Case3 — 88 D waltz piano

| Field | Value |
|---|---|
| Raw / score note counts | 24 / 24 |
| References differ | yes |
| Expected meter / tempo | 3/4 @ 88 bpm |
| Predicted meter / tempo | 3/4 @ 87.95 bpm |
| Raw onset F1 | 0.203 |
| Raw onset+pitch F1 | 0.102 |
| Raw onset+pitch+offset F1 | 0.000 |
| FP / FN | 32 / 21 |
| Cleaner onset+pitch F1 | 0.068 (Δ −0.034) |
| Score quantized note F1 | 0.068 |
| Earliest quality loss | **transcription first** (F1 0.10 already poor); **cleaner then worsens** (0.10 → 0.07). Stage-to-stage first drop reported at `post_cleaner`. |

Meter was correct on all three cases. Tempo halved on Case1/Case2 (≈ half of expected), accurate on Case3.

---

## Aggregate results

From `python -m evaluation.runner --split development` (run `20260826T184619Z`):

| Metric | Value |
|---|---|
| Mean raw onset F1 | 0.218 |
| Mean raw onset+pitch F1 | 0.142 |
| Mean raw onset+pitch+offset F1 | 0.000 |
| Total false positives | 53 |
| Total false negatives | 38 |
| Mean cleaner Δ onset+pitch F1 | −0.011 |
| Mean score quantized note F1 | 0.131 |
| Meter correct | 3 / 3 |

---

## Limitations

What this checkpoint **does not** yet measure well:

1. **Measure / bar alignment** — reported as `unavailable` (no dedicated alignment metric).
2. **True rhythmic-value classification** — score metrics currently reuse note-onset matching against quantized MIDI, not symbolic duration labels (quarter/eighth/…).
3. **Final MusicXML note-for-note vs score** — structured events are the score proxy; MusicXML tree diff is not implemented.
4. **Offset F1** — 0.0 across these three cases; duration errors dominate after onset+pitch matches.
5. **Hand evaluation** — requires labeled LH/RH tracks in the reference; not present on these DAW files.
6. **Why F1 is low** — measurement only. Half-tempo on Case1/Case2 and heavy FP rates are diagnosed, not fixed.
7. **Score F1 is not independent of transcription quality** — when raw detection is wrong, structured/score F1 usually stays low.

---

## Validation commands

```bash
cd audio2score-week4/backend
python -m pytest -q
python -m benchmark.runner --mode midi
python -m benchmark.runner --mode fast
python -m evaluation.runner --split development
```

Production algorithms (Basic Pitch, Cleaner, MeterArbitrator, HandSeparator,
NotationPlanner, quantization, voice separation) were **not** modified.
