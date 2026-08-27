# Checkpoint 9A — Transcription Experiments

**Status:** Experiment / measurement only. Production transcription defaults unchanged.

**Branch:** `cursor/checkpoint-9a-transcription-experiments-a247`  
**Base:** Checkpoint 8 (`44e3371` on `cursor/checkpoint-8-transcription-forensics`)  
**Experiment run:** `evaluation/experiment_results/cp9a_full_matrix`  
**Basic Pitch:** `0.4.0`

---

## Executive Summary

Checkpoint 9A swept **19 opt-in configurations** (audio preprocessing, Basic Pitch parameters, and limited combinations) across the **3 real DAW development cases**, measuring onset+pitch F1 against `reference_raw.mid` in absolute time.

> **LIMITED DEVELOPMENT CORPUS** — only three cases. Do not overfit. Rankings are directional evidence for Checkpoint 9B.

**Main finding:** No configuration produced a robust, multi-case improvement large enough to justify a production change. The best mean F1 was `A5_trim_silence` (0.161, Δ+0.019 vs baseline 0.142) with improvements on all three cases and no regressions — still a tiny absolute F1 and below the conservative “promising” bar. Lowering Basic Pitch thresholds mostly **increased false positives**. Raising thresholds / trimming edge silence gave only marginal gains.

**Verdict: NO CONFIGURATION CHANGE JUSTIFIED.**

**Recommended Checkpoint 9B: B — Expand development corpus first** (then reconsider A5-style preprocessing and/or alternative backends).

---

## Baseline Validation

Did experiment baseline reproduce Checkpoint 8?

**YES.** Exact match within tolerance:

| Case | F1 | Expected | Pred notes | Expected pred | Status |
|---|---:|---:|---:|---:|---|
| Case1 | 0.125 | 0.125 | 9 | 9 | ok |
| Case2 | 0.200 | 0.200 | 16 | 16 | ok |
| Case3 | 0.102 | 0.102 | 35 | 35 | ok |

Control path: production `AudioNormalizer` (mono, DC, 22050 Hz, peak 0.95) + production Basic Pitch defaults (onset 0.6, frame 0.4, min_note_ms 127.70). Experiment adapter does **not** read `BASIC_PITCH_*` env overrides.

---

## Experiment Matrix

### Baseline

| Name | Description |
|---|---|
| `basic_pitch_baseline` | Production normalizer + production BP defaults (control) |

### Axis A — audio representation (BP fixed at production)

| Name | Description |
|---|---|
| `A1_mono_native` | Mono only; native SR; no peak / DC / trim |
| `A2_mono_peak_native` | Mono + peak 0.95; native SR |
| `A3_resample_22050` | Mono + DC + 22050, **no** peak (isolates peak vs A0) |
| `A4_resample_44100` | Mono + DC + 44100 + peak (BP reloads at 22050) |
| `A5_trim_silence` | 22050 + peak + **alignment-preserving** edge silence zeroing |

Production already does mono + 22050 + peak, so A2/A4 often collapse toward baseline when the source is already near that path. A3 isolates peak normalization. A5 is the only audio variant with a clear positive signal.

### Axis B — Basic Pitch parameters (preprocess = production)

Supported `predict()` params only (basic-pitch 0.4.0). No monkey-patching.

| Name | onset | frame | min_note_ms |
|---|---:|---:|---:|
| `B1_lower_onset` | 0.5 | 0.4 | 127.70 |
| `B2_higher_onset` | 0.7 | 0.4 | 127.70 |
| `B3_lower_frame` | 0.6 | 0.3 | 127.70 |
| `B4_higher_frame` | 0.6 | 0.5 | 127.70 |
| `B5_lower_min_note` | 0.6 | 0.4 | 58.0 |
| `B6_lower_onset_frame` | 0.5 | 0.3 | 127.70 |
| `B7_conservative_higher` | 0.7 | 0.5 | 127.70 |

### Axis C — limited combinations (≤6)

Selected from plausible complementarity (best audio tendencies × threshold / min-note levers), not a Cartesian product:

| Name | Parents |
|---|---|
| `C1_mono_native_lower_onset_frame` | A1 + B6 |
| `C2_mono_peak_lower_onset` | A2 + B1 |
| `C3_resample_44100_lower_onset_frame` | A4 + B6 |
| `C4_mono_native_lower_min_note` | A1 + B5 |
| `C5_production_audio_library_defaults` | baseline + B6 + B5 |
| `C6_trim_lower_onset_frame` | A5 + B6 |

### Deferred alternative

| Name | Status |
|---|---|
| `ALT_classical_dsp_future` | **Skipped** — repo has `ClassicalDspBackend`; not executed in 9A |

---

## Aggregate Ranking

Primary key: **macro mean onset+pitch F1** (equal case weight).

| Rank | Experiment | Mean F1 | Δ F1 | Precision | Recall | FP | FN | Regressions |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `A5_trim_silence` | 0.161 | +0.019 | 0.150 | 0.175 | 47 | 37 | 0 |
| 2 | `C6_trim_lower_onset_frame` | 0.151 | +0.009 | 0.133 | 0.175 | 52 | 37 | 1 |
| 3 | `B5_lower_min_note` | 0.149 | +0.007 | 0.131 | 0.175 | 56 | 37 | 1 |
| 4 | `B7_conservative_higher` | 0.149 | +0.007 | 0.140 | 0.161 | 43 | 38 | 0 |
| 5 | `B4_higher_frame` | 0.147 | +0.005 | 0.136 | 0.161 | 44 | 38 | 1 |
| 6 | `C4_mono_native_lower_min_note` | 0.147 | +0.005 | 0.127 | 0.175 | 57 | 37 | 2 |
| 7 | `B2_higher_onset` | 0.145 | +0.002 | 0.132 | 0.161 | 52 | 38 | 0 |
| 8 | `A1_mono_native` | 0.143 | +0.001 | 0.129 | 0.161 | 53 | 38 | 1 |
| 9 | `A2_mono_peak_native` | 0.142 | +0.000 | 0.128 | 0.161 | 53 | 38 | 0 |
| 10 | `A4_resample_44100` | 0.142 | +0.000 | 0.128 | 0.161 | 53 | 38 | 0 |
| 11 | `basic_pitch_baseline` | 0.142 | — | 0.128 | 0.161 | 53 | 38 | 0 |
| 12 | `A3_resample_22050` | 0.140 | −0.002 | 0.124 | 0.161 | 54 | 38 | 1 |
| 13 | `B1_lower_onset` | 0.138 | −0.004 | 0.121 | 0.161 | 55 | 38 | 1 |
| 14 | `C2_mono_peak_lower_onset` | 0.138 | −0.004 | 0.121 | 0.161 | 55 | 38 | 1 |
| 15 | `C1_mono_native_lower_onset_frame` | 0.137 | −0.005 | 0.120 | 0.161 | 56 | 38 | 1 |
| 16 | `B3_lower_frame` | 0.134 | −0.008 | 0.116 | 0.161 | 57 | 38 | 1 |
| 17 | `B6_lower_onset_frame` | 0.131 | −0.011 | 0.111 | 0.161 | 59 | 38 | 1 |
| 18 | `C3_resample_44100_lower_onset_frame` | 0.131 | −0.011 | 0.111 | 0.161 | 59 | 38 | 1 |
| 19 | `C5_production_audio_library_defaults` | 0.126 | −0.016 | 0.104 | 0.161 | 62 | 38 | 2 |

No experiment was marked `promising=True` under the conservative rule (meaningful mean ΔF1, multi-case improvement or strong single-case gain without catastrophe, recall not collapsing).

---

## Per-Case Results

### Case1 (melody @ 160)

| Experiment | Pred | F1 | ΔF1 | FP | FN |
|---|---:|---:|---:|---:|---:|
| baseline | 9 | 0.125 | — | 8 | 6 |
| A5_trim_silence | 8 | 0.133 | +0.008 | 7 | 6 |
| B7_conservative_higher | 9 | 0.125 | 0.000 | 8 | 6 |
| B5_lower_min_note | 9 | 0.125 | 0.000 | 8 | 6 |
| B6_lower_onset_frame | 9 | 0.125 | 0.000 | 8 | 6 |
| C6_trim_lower_onset_frame | 8 | 0.133 | +0.008 | 7 | 6 |

Most BP tweaks leave Case1 unchanged. Edge-silence zeroing removes one spurious note.

### Case2 (chords @ 138)

| Experiment | Pred | F1 | ΔF1 | FP | FN |
|---|---:|---:|---:|---:|---:|
| baseline | 16 | 0.200 | — | 13 | 11 |
| A5_trim_silence | 15 | 0.207 | +0.007 | 12 | 11 |
| B2_higher_onset | 15 | 0.207 | +0.007 | 12 | 11 |
| B5_lower_min_note | 17 | 0.194 | −0.006 | 14 | 11 |
| B6_lower_onset_frame | 22 | 0.167 | −0.033 | 19 | 11 |
| C6_trim_lower_onset_frame | 20 | 0.176 | −0.024 | 17 | 11 |

Lower thresholds hurt Case2 (more spurious chord fragments). Higher onset / trim help slightly.

### Case3 (waltz @ 88)

| Experiment | Pred | F1 | ΔF1 | FP | FN |
|---|---:|---:|---:|---:|---:|
| baseline | 35 | 0.102 | — | 32 | 21 |
| A5_trim_silence | 32 | 0.143 | +0.041 | 28 | 20 |
| B5_lower_min_note | 38 | 0.129 | +0.027 | 34 | 20 |
| B7_conservative_higher | 25 | 0.122 | +0.021 | 22 | 21 |
| B6_lower_onset_frame | 35 | 0.102 | 0.000 | 32 | 21 |
| C6_trim_lower_onset_frame | 32 | 0.143 | +0.041 | 28 | 20 |

Case3 is the most sensitive. Gains are still small in absolute F1 and often case-specific.

---

## Audio Preprocessing Results

| Finding | Evidence |
|---|---|
| Production path already includes mono + 22050 + peak | A2 and A4 match baseline mean F1 exactly |
| Skipping peak (A3) slightly hurts | Δ −0.002 |
| Native mono without peak (A1) ≈ baseline | Δ +0.001, 1 regression |
| **Edge silence zeroing (A5) is the best audio lever** | Δ +0.019, **3/3 improved**, 0 regressions, FP −6 |

A5 preserves duration (zeros edges in place) so absolute-time matching remains valid.

---

## Basic Pitch Parameter Results

| Finding | Evidence |
|---|---|
| Lower onset / frame **hurts** mean F1 | B1 −0.004, B3 −0.008, B6 −0.011 via extra FPs |
| Higher onset / frame / conservative | Tiny gains (B2 +0.002, B4 +0.005, B7 +0.007); mostly Case3 FP reduction |
| Lower min note length | Slight mean gain (+0.007) from Case3, **regresses Case2** |
| Library-like thresholds are worse than production | B6 and C5 rank near the bottom |

Production’s stricter-than-library thresholds (0.6/0.4 vs 0.5/0.3) look directionally correct on this corpus; further tightening helps little; loosening adds ghosts.

---

## Combined Experiments

Combining A5 with lower thresholds (`C6`) **dilutes** A5’s gain (Δ +0.009, regresses Case2). Other combinations that pair “looser BP” with audio variants land at or below baseline. Combinations do not unlock a breakthrough.

---

## Error Taxonomy Changes (vs baseline)

Taxonomy uses Checkpoint 8 Hungarian classification (SPURIOUS / MISSED / pitch / fragment / merge).

| Experiment | ΔFN | ΔFP | ΔPitch | ΔFrag | ΔMerge | ΔDup |
|---|---:|---:|---:|---:|---:|---:|
| A5_trim_silence | −1 | −5 | +1 | −1 | 0 | −2 |
| B7_conservative_higher | +1 | −10 | +1 | 0 | −2 | 0 |
| B5_lower_min_note | 0 | +3 | 0 | 0 | 0 | +1 |
| B6_lower_onset_frame | 0 | +6* | — | — | — | — |
| C6_trim_lower_onset_frame | −1 | −2 | +1 | +1 | −1 | +1 |

\*F1 FP count for B6: +6 (53→59).

A5 reduces both spurious notes and one miss without destroying recall. B7 cuts many FPs but does not recover misses (FN flat / +1 taxonomy). No experiment substantially closes the Checkpoint 8 miss gap (taxonomy FN ≈ 18 aggregate).

---

## Best Candidate

**`A5_trim_silence`** — strongest directional result:

- Mean F1 0.161 (Δ +0.019)
- Improves **all three** cases
- 0 regressions
- FP −6, FN −1

Still **not** production-ready:

1. Absolute F1 remains ~0.16 (failure mode intact).
2. Corpus n=3 → high overfitting risk.
3. ΔF1 just under the conservative 0.02 “meaningful” bar used by the harness.
4. Effect may be source/render-specific (leading silence / loudness), not a general BP fix.

---

## No-Winner Scenario

**NO CONFIGURATION CHANGE JUSTIFIED**

Threshold and light preprocessing knobs do not repair transcription-stage collapse on these DAW cases. Do not flip production defaults from this matrix alone.

---

## Recommended Checkpoint 9B

**Choice: B — Expand development corpus first**

Rationale:

1. Only three real cases; any “winner” is statistically fragile.
2. Best candidate (A5) is promising but small; needs confirmation on more textures (short notes, dense polyphony, non-piano if in scope).
3. After corpus growth, re-rank; if BP/preprocess still saturates near ~0.2 F1, escalate to **C — alternative transcription backend** (`classical_dsp` / MT3), already present in-repo.
4. Option **D** (audio/source characteristics) remains relevant for Case1/Case2 half-tempo and possible render quirks, but is secondary to getting more labeled cases.
5. Option **A** (adopt into production) is **not** justified now.

---

## Architecture (opt-in only)

```
evaluation/experiments/
  config.py          ExperimentConfig / PreprocessConfig / TranscriptionParams
  registry.py        Named matrix (baseline, A*, B*, C*, ALT*)
  preprocess.py      Experiment-only audio variants (alignment-preserving trim)
  transcription.py   ExperimentBasicPitchAdapter (explicit params; no env)
  metrics.py         F1 + taxonomy + macro ranking / anti-overfit
  reports.py         JSON + markdown
  runner.py          CLI
```

```bash
cd audio2score-week4/backend
python -m evaluation.experiments.runner --list
python -m evaluation.experiments.runner --split development --experiment basic_pitch_baseline
python -m evaluation.experiments.runner --split development --experiment all --save-results --report
```

Results: `evaluation/experiment_results/<run_id>/` (gitignored). Production `benchmark.runner`, `evaluation.runner`, and pipeline defaults are untouched.

---

## Tempo separation

Beat-tracker tempo is recorded as diagnostic metadata only. Note matching uses **absolute seconds**. No half-tempo correction was applied during Checkpoint 9A.

---

## Production safety

| Area | Changed? |
|---|---|
| `adapters/basic_pitch_backend.py` defaults | No |
| `audio_engine/normalizer.py` | No |
| Cleaner / MeterArbitrator / NotationPlanner / HandSeparator | No |
| Corpus audio / reference MIDI | No |
| Benchmark baselines | No |
