# Real-world audio evaluation (Checkpoint 7)

Measure NotaScore against DAW-created WAV + reference MIDI pairs.

This package does **not** change production transcription algorithms. Existing
synthetic `benchmark/` gates and `benchmark/realworld/` observational harness
remain unchanged.

## Quick start

From `audio2score-week4/backend`:

```bash
# Repo-safe synthetic fixture (proves the harness)
python -m evaluation.runner --prepare-fixture

# Your DAW cases
python -m evaluation.runner --case piano_001
python -m evaluation.runner --split development
python -m evaluation.runner --split holdout
python -m evaluation.runner --split real_world
python -m evaluation.runner --all

# Baselines
python -m evaluation.runner --split development --save-baseline checkpoint-7-baseline
python -m evaluation.runner --split development --compare-baseline checkpoint-7-baseline
```

## Where to put files

```
evaluation/development/<case_id>/
    input.wav          # required (also .mp3/.flac/.mid)
    reference.mid      # required ground-truth performance MIDI
    case.yaml          # optional metadata
```

Same layout under `evaluation/holdout/` and `evaluation/real_world/`.

Audio and MIDI are **gitignored** by default so DAW assets are not committed.

### Minimum case

Only `input.wav` + `reference.mid` are required. Without `case.yaml`, the
directory name is the case id and note metrics are still computed.

### Optional `case.yaml`

```yaml
id: piano_sixteenth_120
title: Sixteenth note threshold
instrument: piano
reference:
  midi: reference.mid
expected:
  meter: "4/4"
  tempo_bpm: 120
tags:
  - piano
  - duration
  - sixteenth
performance_id: piano_sixteenth_120_perf   # paired renders share this
```

## Corpus splits

| Split | Meaning |
|---|---|
| `development` | Diagnose failures; guide future improvements |
| `holdout` | Generalization only — do not tune against individual cases |
| `real_world` | Real recordings / difficult practical material |

**Paired renders:** the same reference performance rendered under different
conditions (clean / soft / loud / pedal) may share one `performance_id` or one
reference MIDI path. Different renders of the same performance **must not** be
split between `development` and `holdout`. The runner warns on leakage.

## Outputs

```
evaluation/results/<run_id>/
    results.json
    report.md
    <case_id>/
        raw_transcription.mid
        cleaned.mid
        structured.mid
        output.musicxml
        metrics.json
        diagnostics.json
        report.md
```

Stage reports highlight the first pipeline stage where onset+pitch F1 drops.

Holdout aggregate reports are marked **HOLDOUT EVALUATION**.

## DAW test design (recommended families)

1. **Note duration** — whole, half, quarter, eighth, sixteenth, 32nd, dotted, staccato, multiple tempos
2. **Piano textures** — melody, melody+bass, block/broken chords, octaves, melody-in-chords, polyphonic RH, hand crossing, dense polyphony
3. **Meter** — 2/4, 3/4, 4/4, 6/8
4. **Rhythm** — straight, syncopation, triplets, dotted, sixteenths
5. **Paired renders** — same MIDI → clean / different piano / soft / loud / pedal

## Reference MIDI

Ground truth for the intended performance. May include multiple tracks, tempo
maps, time signatures, channels, and LH/RH tracks. Evaluation normalizes to
musical note events in memory and **never mutates** the original file.

If hand track names are absent, hands are reported as `NOT_EVALUATED`.

## Metrics

Configurable musical tolerances (default onset 50 ms). Reports onset F1,
onset+pitch F1, optional offset F1, timing/duration errors, meter, tempo,
hands, and pipeline stage counts.


## Stage diagnostics

Stage MIDIs are **snapshots from the single production pipeline run**:

1. `transcription` — Basic Pitch notes (`pipeline.last_raw_notes`)
2. `post_cleaner` — after MIDICleaner
3. `post_piano` — after PianoAnalyzer (same as cleaned when piano analysis is skipped)
4. `structured` — MIR structure events

The evaluator does **not** re-invoke Basic Pitch for diagnostics.

## Relation to `benchmark/realworld`

`benchmark/realworld` is an older observational harness for ad-hoc local audio.
`evaluation/` is the Checkpoint 7 corpus + baseline + stage-diagnostics system.
Prefer `evaluation/` for new DAW cases; keep `benchmark/realworld` for its existing smoke tests.

## Design doc

See `docs/CHECKPOINT_7_EVALUATION_DESIGN.md`.
