# Checkpoint 8 — Transcription Forensics

**Status:** Read-only diagnostic infrastructure. No production algorithm changes.

**Branch:** `cursor/checkpoint-8-transcription-forensics`  
**Base:** Checkpoint 7B (`244f0a3` on `cursor/checkpoint-7b-two-reference-eval`)  
**Forensics run:** `evaluation/results/20260827T064145Z`

---

## Executive Summary

On the three real DAW development cases, **quality already collapses at Basic Pitch transcription**. Cleaner is mostly a no-op (Case1/Case2) and **hurts** Case3. Half-tempo on Case1/Case2 is real for the meter/tempo path, but **does not explain note F1 failure**: matched onset errors are ~7–20 ms (within the 50 ms tolerance). Zero offset F1 is **not** merely a strict-tolerance artifact for these cases—matched notes show hundreds of milliseconds of duration/offset error. Dominant patterns are **missed reference notes** and **spurious predictions**, with additional pitch/onset confusion on the waltz case and fragmentation/merging on the chordal case.

---

## Corpus

Auto-discovered under `evaluation/development/` (nested `NotaTestSamples/`):

| Case | Description | Raw notes | Score notes | Expected tempo | Predicted tempo |
|---|---|---|---|---|---|
| Case1 | 160 F melody piano | 7 | 7 | 160 | 80.1 (HALF) |
| Case2 | 138 C chords piano | 14 | 14 | 138 | 68.75 (HALF) |
| Case3 | 88 D waltz piano | 24 | 24 | 88 | 87.95 (CORRECT) |

References were not renamed, moved, or mutated. Diagnostics write under `evaluation/results/<run_id>/<case>/diagnostics/`.

---

## Forensic architecture

```
evaluation/forensics/
  classify.py     Hungarian 1-1 matching + fragment/merge taxonomy
  taxonomy.py     Labels + CSV row schema
  midi_out.py     Category + overlay MIDIs
  cleaner.py      Harmful vs beneficial removals
  offset.py       Multi-tolerance offset diagnostics
  tempo.py        Tempo ratio + causality check vs absolute onsets
  analyze.py      Per-case + corpus orchestration
  runner.py       CLI: python -m evaluation.forensics
```

**Matching strategy:** cost = onset distance + pitch penalty; forbidden if onset gap > 0.35 s; optimal assignment via `scipy.optimize.linear_sum_assignment`; then semantic labels (MATCH / ONSET_ERROR / PITCH_ERROR / …); then override to FRAGMENTED / MERGED when local many-to-one / one-to-many evidence exists. Production F1 matching is unchanged.

---

## Stage-of-failure analysis

| Case | Trans F1 | Cleaner ΔF1 | Primary failure | Notes |
|---|---|---|---|---|
| Case1 | 0.125 | 0.000 | **transcription** | 9 pred vs 7 ref; cleaner unchanged |
| Case2 | 0.200 | 0.000 | **transcription** | 16 pred vs 14 ref; cleaner unchanged |
| Case3 | 0.102 | −0.034 | **transcription** | Cleaner further drops recall/precision |

All three: `primary_failure_stage = transcription`.

---

## Error taxonomy (transcription aggregate)

| Category | Count |
|---|---|
| Reference notes | 45 |
| Predicted notes | 60 |
| Matched (MATCH + OFFSET_ERROR) | 6 |
| False negatives (MISSED) | 18 |
| False positives (SPURIOUS) | 31 |
| Pitch errors | 5 |
| Onset errors | 9 |
| Offset errors | 6 |
| Fragmented refs | 3 |
| Merged refs | 4 |
| Duplicates / extra fragments | 7 |

Pitch-error buckets on paired notes: exact 15, ±2: 1, octave 1, larger 3.

---

## False negatives

- **Case1:** 5/7 reference notes MISSED; all refs are long (≥1000 ms); miss_rate 0.71 in that duration bin.
- **Case2:** 5 MISSED + 3 FRAGMENTED + 4 MERGED on long chordal notes; polyphony 3–4+ shows higher miss rates (0.43–0.50).
- **Case3:** 8/22 notes shorter than 125 ms were MISSED (miss_rate 0.36). Middle register carries most misses.

Observation (not a causal claim): short notes and dense/chordal textures coincide with more misses in this tiny corpus.

---

## False positives

- Spurious predictions dominate (31 aggregate SPURIOUS).
- Case3: 19 spurious vs 24 references; predicted count 35.
- Case1/Case2: 7 and 5 spurious respectively after taxonomy (F1 FP counts are higher because F1 uses greedy onset+pitch matching without fragment/merge reassignment).

---

## Pitch errors

- Case1: 1 pitch error (±2).
- Case2: 0 pitch errors in taxonomy (failures are miss/fragment/merge).
- Case3: 4 pitch errors including 1 octave and 3 larger — concurrent with many onset errors.

---

## Timing errors

- Case-mean onset error on F1-matched pairs: mean ~12 ms (median ~10 ms) — **within** 50 ms tolerance when a match exists.
- Case3 taxonomy shows many ONSET_ERROR / EARLY / LATE pairs outside tolerance (signed onset distribution wide: p10 −161 ms, p90 +225 ms).
- So: when notes match, timing is fine; when they do not, Case3 often has large onset deviations rather than pure absences.

---

## Fragmentation / merging

- Concentrated in **Case2** (chords): 3 fragmented refs, 4 merged refs, 7 extra fragments.
- Case1/Case3: none under current detectors.

---

## Tempo forensics

| Case | Status | Ratio | Mean matched onset error | Tempo explains note F1? |
|---|---|---|---|---|
| Case1 | HALF_TEMPO | 0.501 | 10.2 ms | **No** |
| Case2 | HALF_TEMPO | 0.498 | 6.9 ms | **No** |
| Case3 | CORRECT | 0.999 | — | N/A |

Note matching uses **absolute seconds**. Half-tempo is a real downstream meter/tempo problem, but it is **not** the cause of low onset+pitch F1 on these cases.

---

## Offset forensics

Production onset+pitch+offset F1 remains 0 at 50–100 ms for all three.

| Case | Verdict | Evidence |
|---|---|---|
| Case1 | genuine_duration_failure | 1 onset+pitch match; mean duration error 538 ms; F1 still 0 at 500 ms |
| Case2 | genuine_duration_failure | 3 matches; mean duration error 1022 ms; F1 0.13 only at 500 ms |
| Case3 | systematic_offset_bias | 3 matches; mean signed offset +256 ms (late note-offs); F1 rises to 0.10 at 500 ms |

**Conclusion:** zero offset F1 is primarily **real duration/release mismatch** (and sparse onset+pitch matches), not a metric bug. Piano audio note-offs vs MIDI offsets are a plausible contributor but not proven here.

---

## Cleaner forensics

| Case | Removed | Harmful | Beneficial | ΔF1 | Helps? |
|---|---|---|---|---|---|
| Case1 | 0 | 0 | 0 | 0.000 | neutral |
| Case2 | 0 | 0 | 0 | 0.000 | neutral |
| Case3 | 4 | 2 | 2 | −0.034 | **hurts** |

Aggregate: mean ΔF1 −0.011; 0 helped / 1 hurt / 2 neutral.

**Conclusion:** Cleaner does not rescue transcription failure; on Case3 it removes some correct notes.

---

## Evidence tables (quick)

### Onset error (case means of matched pairs, ms)

mean 12.3 · median 10.2 · p90 17.8 · max 19.7

### Duration error (case means, ms)

mean 608 · median 538 · p90 925

### Cleaner

harmful 2 · beneficial 2 · mean ΔF1 −0.011

---

## Recommended next checkpoint

| Candidate | Evidence | Frequency | Impact | Confidence | Complexity | Priority |
|---|---|---|---|---|---|---|
| **Basic Pitch / transcription recovery** | Failure at transcription on 3/3; high miss + spurious | High | High | High | Medium–High | **1** |
| Short-note detection | Case3: 8/22 notes <125 ms missed | Medium (1 case) | Medium | Medium | Medium | 2 |
| Chord/polyphony recovery | Case2 fragment/merge + poly miss rates | Medium (1 case) | Medium | Medium | Medium | 3 |
| Audio preprocessing investigation | Strings mis-tag Case1/2; possible render/input issues | Unknown | Medium | Low | Low–Med | 4 |
| Alternate transcription backend | Same as (1) but larger change | — | High | Medium | High | 5 |
| Cleaner modification | Only Case3 hurts; not root cause | Low | Low | High | Low | 6 |
| Tempo repair | Half-tempo real but ≠ note F1 cause | 2/3 | Medium (notation) | High (non-causal for F1) | Medium | 7 |
| Quantization work | Downstream of broken notes | High | Low now | High | Medium | 8 |

**Choose one:** Checkpoint 9 should attack **transcription-stage note detection quality** (Basic Pitch settings / preprocessing / alternate backend evaluation)—still measurement-first if desired, but that is the highest-leverage subsystem. Do **not** start with Cleaner, tempo, or quantization.

---

## How to run

```bash
cd audio2score-week4/backend
python -m evaluation.forensics --split development
python -m pytest -q
python -m benchmark.runner --mode midi
python -m benchmark.runner --mode fast
python -m evaluation.runner --split development
```

Production algorithms were not modified.
