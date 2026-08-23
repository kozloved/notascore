# Music Understanding Engine — Architecture Report

See the approved migration plan for module order, metrics, and safety constraints.

## Current pipeline (legacy)

```
Audio upload → Basic Pitch → librosa tempo + refine → pretty_midi → music21 quantize → MusicXML
```

Live code: `audio2score-week4/backend/transcription.py`

## Target pipeline

```
Audio → Audio Intelligence → Transcription Backends → MIDICleaner → CMR → MIDI Intelligence → Notation → MusicXML
MIDI file ────────────────────────────────────────────────┘
```

## Package layout

```
audio2score-week4/backend/
  audio_engine/       # Audio Intelligence Layer
  mir/                # Common Musical Representation + MIDI Intelligence
  notation_engine/    # MusicXML from MusicalEvent[]
  adapters/           # Basic Pitch, MT3 (future), classical DSP
  transcription.py    # Facade: legacy | understanding pipeline
  benchmark/          # Metrics, fixtures, before/after harness
```

## Convergence contract

All backends emit `MusicalEvent[]` + `TempoMap` + `ScoreMeta`. Notation never imports Basic Pitch or MT3.

## Feature flags

| Variable | Values | Default |
|----------|--------|---------|
| `TRANSCRIPTION_PIPELINE` | `legacy` \| `understanding` | `understanding` |
| `TRANSCRIPTION_PIPELINE_FALLBACK` | `0` \| `1` | `1` |
| `TRANSCRIPTION_BACKEND` | `basic_pitch` \| `classical_dsp` \| `mt3` | `basic_pitch` |
| `TRANSCRIPTION_USE_CLEANER` | `0` \| `1` | `0` |
| `TRANSCRIPTION_SHADOW_CLEANER` | `0` \| `1` | `0` |
| `TRANSCRIPTION_USE_NORMALIZER` | `0` \| `1` | `1` |
| `TRANSCRIPTION_USE_BEAT_TRACKER` | `0` \| `1` | `1` |
| `TRANSCRIPTION_USE_PIANO_ANALYZER` | `0` \| `1` | `1` |
| `TRANSCRIPTION_USE_MIR_LAYERS` | `0` \| `1` | `1` |

## Phase 2 — Enhanced legacy path (implemented)

Production stays on `TRANSCRIPTION_PIPELINE=legacy` while audio intelligence modules
run **before and after** Basic Pitch:

```
Audio → Normalizer → Basic Pitch → MIDICleaner → PianoAnalyzer (if piano)
     → BeatTracker seed + onset refine → quantize → MusicXML
```

**Why this order:** normalization stabilizes Basic Pitch input; cleaner removes
micro-notes; beat tracker improves tempo seed for quantization; piano analyzer
refines dynamics from onset strength.

**Rollout:** flags default to `1`. Disable individually for A/B (`TRANSCRIPTION_USE_*=0`).

**Next (Phase 3):** promote `TRANSCRIPTION_PIPELINE=understanding` when benchmark
F1 ≥ 0.85 vs enhanced legacy and OSMD readability passes.

## Phase 3 — Understanding pipeline (implemented)

Default pipeline is now **`understanding`** with **`TRANSCRIPTION_PIPELINE_FALLBACK=1`**
so production jobs fall back to enhanced legacy if the full MIR path fails.

```
Audio → Normalizer → Classifier → Basic Pitch → MIDICleaner → PianoAnalyzer
     → CMR (beats) → Hand/Voice/Dynamics/Articulation/Phrases → Notation → MusicXML
```

**Validate before/after deploy:**

```bash
cd audio2score-week4/backend
./.venv/bin/python -m benchmark.run_pipeline_benchmark
./.venv/bin/python -m pytest tests/test_understanding_pipeline.py -q
```

**Rollback:** set `TRANSCRIPTION_PIPELINE=legacy` and restart worker.

## How to enable MIDICleaner safely

1. Keep `TRANSCRIPTION_PIPELINE=legacy`.
2. Set `TRANSCRIPTION_SHADOW_CLEANER=1` and restart the worker — logs note-count deltas without changing results.
3. Run synthetic before/after:

```bash
cd audio2score-week4/backend
./.venv/bin/python -m benchmark.run_cleaner_benchmark
./.venv/bin/python -m pytest tests/test_cleaner_before_after.py -q
```

4. When fixtures pass and shadow logs look sane on real uploads, set `TRANSCRIPTION_USE_CLEANER=1`.
5. Only then consider `TRANSCRIPTION_PIPELINE=understanding`.

## Promotion criteria

**MIDICleaner → default on legacy path** when:

- All cleaner fixtures reach F1 ≥ 0.99 vs expected
- Readability score does not decrease on fixtures
- Shadow mode on real piano uploads shows fewer micro-notes / dupes without deleting melodic material

**Understanding pipeline → default** when:

- Cross-pipeline F1 vs legacy ≥ 0.85 on shared fixtures (unless intentionally editorial)
- Reference MIDI F1 (when available) ≥ legacy
- Score readability rubric + OSMD smoke pass

**MT3** only after CMR + cleaner + tempo map are stable.

## Quality metrics

- Pitch / onset F-measure (50 ms tolerance)
- Note precision / recall
- Pedal CC IoU (piano)
- Readability: micro-note count, near-duplicate onsets, chord onset spread
- Score readability rubric (OSMD smoke)

## Migration rules

1. Characterization tests before algorithm swaps
2. Shadow mode until metrics beat baseline
3. One module at a time
4. MT3 only after CMR + cleaner + tempo map are stable
