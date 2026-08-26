# Where to put files

```
evaluation/development/<case_id>/
    input.wav              # required
    reference_raw.mid      # preferred: performance MIDI used to render audio
    reference_score.mid    # preferred: quantized notation MIDI
    case.yaml              # optional metadata
```

## Two-reference layouts (Checkpoint 7B)

| Layout | Files | Behavior |
|---|---|---|
| Legacy | `reference.mid` | Both raw and score fall back to it (reported) |
| Raw-only | `reference_raw.mid` | Raw metrics only; score marked unavailable |
| Score-only | `reference_score.mid` | Score metrics only; raw not compared to score |
| Preferred | both `reference_raw.mid` + `reference_score.mid` | Full dual evaluation |

**Never mutate** either reference MIDI or `input.wav`. Nested folders
(e.g. `development/NotaTestSamples/Case1`) are discovered automatically.

Same layout under `evaluation/holdout/` and `evaluation/real_world/`.

Audio and MIDI are **gitignored** by default so DAW assets are not committed
(except intentionally versioned fixtures under `NotaTestSamples/`).

### Minimum case

`input.wav` plus at least one of `reference_raw.mid`, `reference_score.mid`,
or legacy `reference.mid`. Without `case.yaml`, the directory name is the
case id.

### Optional `case.yaml`

```yaml
id: piano_sixteenth_120
title: Sixteenth note threshold
instrument: piano
reference:
  raw: reference_raw.mid
  score: reference_score.mid
expected:
  meter: "4/4"
  tempo_bpm: 120
tags:
  - piano
  - duration
  - sixteenth
performance_id: piano_sixteenth_120_perf   # paired renders share this
```

Legacy manifests may still use `reference: { midi: reference.mid }`.
