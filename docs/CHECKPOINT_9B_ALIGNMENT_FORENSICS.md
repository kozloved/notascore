# Checkpoint 9B — Evaluation Alignment Forensics

**Status:** Diagnostic only. Production transcription, tolerances, Cleaner, tempo/meter, and benchmark gates unchanged.

**Branch:** `cursor/checkpoint-9b-alignment-forensics-a247`  
**Base:** Checkpoint 9A (`f16d64f`)  
**Run:** `evaluation/alignment_diagnostics/cp9b_alignment`  
**Predictions reused:** `evaluation/results/20260827T070444Z/*/transcription.mid` (no Basic Pitch re-run)

---

## Executive Summary

Checkpoint 9A’s ~0.10–0.20 onset+pitch F1 is **not primarily a 50 ms tolerance artifact**. Widening tolerance to 300 ms only lifts macro F1 from **0.142 → 0.221**.

The dominant issue on **Case1 and Case2** is a **MIDI tempo-meta / seconds-conversion mismatch**: all three `reference_raw.mid` files embed **120 BPM** meta while the DAW performances are at **160 / 138 / 88**. Reinterpreting Case1/Case2 reference times by `meta/expected` jumps F1 to **0.875 / 0.867**.

**Case3** does **not** follow that pattern (tempo reinterpret hurts). It shows partial timing sensitivity (best combined F1 ~0.41) plus substantial genuine pitch/spurious errors.

**Root cause: D — MIXED ROOT CAUSES**  
(Case1/Case2 = time-base conversion; Case3 = mostly remaining transcription difficulty after alignment probes.)

---

## Key Finding

| Question | Answer |
|---|---|
| Are terrible F1 scores real transcription failure? | **Partly.** On Case1/Case2, evaluation was comparing against **wrong absolute seconds** from MIDI tempo meta. After correction, Basic Pitch is actually ~0.87 F1. |
| Is official 50 ms tolerance too strict? | **No** as the main cause — macro ΔF1 only +0.079 out to 300 ms. |
| Constant latency offset? | **No** for Case1/Case2 (best offset 0). Case3 prefers ~+1.36 s but only reaches F1 0.20. |
| Half/double musical tempo? | **Do not confuse** with this. Scale recovery at **1.33 / 1.15** matches `expected/meta`, not 0.5/2.0 notation equivalence. |

---

## Audio / MIDI Duration Table

| Case | Audio Duration | SR / ch / frames | Reference Duration | Predicted Duration | Ratio Audio/Reference | Ratio Predicted/Reference |
|---|---:|---|---:|---:|---:|---:|
| Case1 | 13.665 s | 48000 / 2 / 655918 | 15.052 s | 13.428 s | 0.908 | 0.892 |
| Case2 | 12.701 s | 48000 / 2 / 609664 | 11.943 s | 12.454 s | 1.064 | 1.043 |
| Case3 | 9.149 s | 48000 / 2 / 439136 | 7.094 s | 8.794 s | **1.290** | 1.240 |

Case1 reference duration is stretched vs audio (~15.1 vs 13.7), consistent with 160→120 meta stretch (factor 160/120 ≈ 1.333).

---

## MIDI Time Conversion Audit

### Production method

```
normalize_reference_midi
  → ingest_midi
    → pretty_midi.PrettyMIDI
      → NoteEvent.start_time = float(Note.start)   # already seconds
```

There is **no** application tick→seconds math for F1. `TempoMap` is for later notation/beats only.

pretty_midi converts ticks using the **file tempo map**. If ticks were authored at musical tempo T but the file embeds meta M, absolute seconds are wrong by **M/T** relative to audio.

### Corpus tempo meta

| Case | PPQ | MIDI meta BPM | Expected BPM | Meta/Expected | First ref onset | First pred onset | Audio first non-silent |
|---|---:|---:|---:|---:|---:|---:|---:|
| Case1 | 96 | **120** | 160 | 0.750 | 0.000 | 0.010 | 0.000 |
| Case2 | 96 | **120** | 138 | 0.870 | 0.005 | 0.012 | 0.000 |
| Case3 | 96 | **120** | 88 | 1.364 | **1.500** | 0.173 | 0.160 |

Automated tests prove constant-tempo MIDIs at 60/120/160 BPM and a tempo-change MIDI round-trip to the same absolute seconds via `ingest_midi`.

---

## Baseline at Normal Tolerance (50 ms)

| Case | Onset F1 | Onset+Pitch F1 | P | R | Matched | FP | FN |
|---|---:|---:|---:|---:|---:|---:|---:|
| Case1 | 0.250 | **0.125** | 0.111 | 0.143 | 1 | 8 | 6 |
| Case2 | 0.200 | **0.200** | 0.188 | 0.214 | 3 | 13 | 11 |
| Case3 | 0.203 | **0.102** | 0.086 | 0.125 | 3 | 32 | 21 |

Matches Checkpoint 8 / 9A.

---

## Tolerance Sweep

Official production tolerance **unchanged** (still 50 ms). Diagnostic only.

| Tol (ms) | Macro onset F1 | Macro onset+pitch F1 | Precision | Recall | FP | FN |
|---:|---:|---:|---:|---:|---:|---:|
| 25 | 0.173 | 0.131 | 0.119 | 0.147 | 54 | 39 |
| 50 | 0.218 | **0.142** | 0.128 | 0.161 | 53 | 38 |
| 80 | 0.218 | 0.154 | 0.138 | 0.175 | 52 | 37 |
| 100 | 0.263 | 0.176 | 0.157 | 0.202 | 50 | 35 |
| 150 | 0.286 | 0.199 | 0.176 | 0.230 | 48 | 33 |
| 200 | 0.350 | 0.199 | 0.176 | 0.230 | 48 | 33 |
| 300 | 0.395 | **0.221** | 0.195 | 0.258 | 46 | 31 |

**Δ F1 50→300 ms = +0.079** — *not* a dramatic jump. Case1/Case2 are flat across tolerances (pitches don’t meet under stretched time). Case3 rises 0.102→0.339 (timing-sensitive subset).

Interpretation: **0.14 → 0.22 is “genuine mismatch / wrong time base,” not “50 ms too strict.”**

---

## Offset Search (±300 ms; Case3 widened by start delta)

| Case | F1@0 | Best offset (ms) | F1@best | Δ F1 |
|---|---:|---:|---:|---:|
| Case1 | 0.125 | 0 | 0.125 | 0.000 |
| Case2 | 0.200 | 0 | 0.200 | 0.000 |
| Case3 | 0.102 | **1364** | 0.203 | +0.102 |

No shared latency. Case3’s ~1.3 s start gap (ref starts at 1.5 s, pred ~0.17 s) helps little for onset+pitch.

---

## Time-Scale Search

| Case | F1@1.0 | Best scale | F1@best | Δ F1 |
|---|---:|---:|---:|---:|
| Case1 | 0.125 | **1.33** | **0.875** | **+0.750** |
| Case2 | 0.200 | **1.15** | **0.867** | **+0.667** |
| Case3 | 0.102 | 0.98 | 0.136 | +0.034 |

Best scales ≈ `expected/meta` (160/120=1.333, 138/120=1.150).

---

## Tempo-Meta Reinterpret Diagnostic

Scale reference absolute times by `meta/expected` (equivalent to correcting pretty_midi’s wrong tempo):

| Case | Meta | Expected | Scale ref | F1 baseline | F1 after | Δ F1 |
|---|---:|---:|---:|---:|---:|---:|
| Case1 | 120 | 160 | 0.750 | 0.125 | **0.875** | **+0.750** |
| Case2 | 120 | 138 | 0.870 | 0.200 | **0.867** | **+0.667** |
| Case3 | 120 | 88 | 1.364 | 0.102 | 0.000 | −0.102 |

This is a **DAW export / MIDI tempo-map mismatch**, not musical half/double-tempo equivalence.

---

## Combined Search

| Case | Zero F1 | Best offset-only | Best scale-only | Best combined |
|---|---:|---|---|---|
| Case1 | 0.125 | 0 ms → 0.125 | ×1.33 → 0.875 | ×1.33, 0 ms → **0.875** |
| Case2 | 0.200 | 0 ms → 0.200 | ×1.15 → 0.867 | ×1.15, 0 ms → **0.867** |
| Case3 | 0.102 | ~10–1364 ms → ≤0.20 | ×0.98 → 0.136 | ×0.74, −240 ms → **0.407** |

Case3’s best combined (~0.41) still leaves majority errors — residual genuine transcription issues.

---

## Per-Case Error Taxonomy (original timing)

### Case1 — `TIME_BASE_OR_MIDI_CONVERSION`
EXACT_MATCH 1 · MISSED 5 · SPURIOUS 7 · (after tempo fix: F1 0.875)

### Case2 — `TIME_BASE_OR_MIDI_CONVERSION`
EXACT_MATCH 3 · FRAGMENTED 3 · MERGED 4 · DUPLICATE 7 · MISSED 11 · SPURIOUS 13 · (after tempo fix: F1 0.867)

### Case3 — `PARTIAL_ALIGNMENT_ISSUE`
EXACT_MATCH 3 · PITCH_CORRECT_OUTSIDE_TOL 9 · WRONG_OCTAVE 2 · MISSED 8 · SPURIOUS 19

---

## Nearest-Neighbor Diagnostics

| Case | Median onset err (ms) | Mean abs (ms) | p90 abs (ms) | Pitch exact / ±1 / ±2 / oct / other |
|---|---:|---:|---:|---|
| Case1 | 10.2 | 389.7 | 511 | 2 / 0 / 4 / 0 / 1 |
| Case2 | −644 | 587.6 | 1035 | 5 / 0 / 0 / 0 / 9 |
| Case3 | 18.5 | 154.6 | 268 | 6 / 0 / 0 / 3 / 15 |

Case1/2 nearest-neighbor absolute errors are hundreds of ms — consistent with systematic scale stretch, not jitter.

---

## Piano Roll Diagnostics

Under `evaluation/alignment_diagnostics/cp9b_alignment/<case>/`:

- `pianoroll_original.png`
- `pianoroll_best_offset.png`
- `pianoroll_best_scale.png`
- `pianoroll_best_combined.png`
- `pianoroll_tempo_meta_reinterpret.png` (Case1/Case2)
- `note_summary.txt`

---

## Half/Double Tempo Interpretation

| Concept | Meaning |
|---|---|
| **Performance time** | Absolute seconds of audio / correctly converted MIDI |
| **Notation tempo** | 120 BPM quarters vs 60 BPM eighths can be musically equivalent |

A wrong **notation** tempo estimate must **not** change raw onset+pitch F1 if both streams are in true absolute seconds.

What we observed is different:

- MIDI **meta tempo 120** with ticks authored at **160/138** → pretty_midi seconds are wrong.
- Scale ≈ 1.33 / 1.15 recovers F1 — this is **time-base conversion**, not “tempo equivalence.”
- It is **not** the same as half-tempo beat tracking on Case1/Case2 (Checkpoint 8 already showed half-tempo does not explain note F1 when times are absolute).

---

## Root Cause Decision

**D — MIXED ROOT CAUSES**

| Case | Classification | Evidence |
|---|---|---|
| Case1 | **C** time-base / MIDI conversion | Scale 1.33 / tempo-meta reinterpret → F1 0.875 |
| Case2 | **C** time-base / MIDI conversion | Scale 1.15 / tempo-meta reinterpret → F1 0.867 |
| Case3 | Partial alignment + residual failure | Tolerance helps modestly; best combined ~0.41; many spurious/pitch errors |

Macro tolerance sweep alone would have looked like Case A; the tempo-meta diagnostic reveals Case C for 2/3 of the corpus.

---

## Recommended Next Checkpoint

**Fix reference MIDI seconds / corpus export (Case C path), then re-measure transcription.**

1. Re-export or rewrite `reference_raw.mid` with correct tempo meta (or store absolute-second ground truth independent of wrong meta).
2. Re-run evaluation + Checkpoint 8/9A metrics on corrected references.
3. Only then decide whether Basic Pitch still needs a backend comparison (Case A leftover, especially Case3).
4. Do **not** silently widen official onset tolerance or apply production offset/scale hacks.

Optional immediate hygiene: add a corpus validator that fails when `midi_meta_bpm` disagrees with `case.yaml` expected tempo by more than a small epsilon.

---

## How to run

```bash
cd audio2score-week4/backend
python -m evaluation.alignment --split development
python -m pytest -q tests/test_evaluation_checkpoint9b_alignment.py
```

Production algorithms were not modified.
