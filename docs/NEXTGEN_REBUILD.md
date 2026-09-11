# Next-gen rebuild (foundations increment)

This increment adds typed stages around the existing production engine. It does
**not** replace `UnderstandingPipeline`, rewrite quantization, vendor Transkun /
RoFormer / Beat This!, or switch live jobs off `transcription.get_engine()`.

Live jobs remain:

```text
audio2score-week4/frontend
  → backend/main.py / tasks.process_job
  → transcription.get_engine()
  → mir.pipeline.UnderstandingPipeline
```

Root `backend/engines/` is still a disconnected stub. Do not implement there.

## Layers (unchanged invariant)

```text
original audio / MIDI bytes
    ↓ immutable
raw transcription / PerformanceSnapshot / {job}.raw.mid
    ↓ derived
validated performance
    ↓ derived
interpreted performance (beats, hands, voices, roles)
    ↓ derived
NotationPlan / score MIDI / MusicXML
```

`raw.mid != score.mid`. Notation never mutates source pitch or note identity.

## New packages (`audio2score-week4/backend/`)

| Package | Role |
|---|---|
| `engine/` | `PipelineOrchestrator`, `StageResult`, `ArtifactManifest`, `InterpretedPerformance` |
| `timing/` | `MusicalTimeMap` (seconds ↔ beats), printed tempo vs performance tempo, Beat This! adapter (disabled), existing tracker adapter, fusion |
| `transcription_fed/` | Capability router (MT3 / Basic Pitch / MIDI / Transkun stub), bipartite reconciliation |
| `separation/` | `StemSeparator` protocol, RoFormer adapter that **skips** unless licensed |

## Feature flags (all off except the manifest)

| Flag | Default | Meaning |
|---|---|---|
| `NEXTGEN_SEPARATION` | 0 | Run RoFormer. Still refuses if no checkpoint. Never invents stems. |
| `NEXTGEN_TRANSKUN` | 0 | Piano specialist. Raises until licensed + wired. |
| `NEXTGEN_BEAT_THIS` | 0 | Beat This! analyzer. madmom/librosa remains production. |
| `NEXTGEN_ENSEMBLE_RENDER` | 0 | Multi-part score. Mixed GM programs still raise in performance mode. |
| `NEXTGEN_WRITE_MANIFEST` | 1 | Write `{job}.manifest.json` from the orchestrator path. |

See `docs/MODEL_LICENSES.md`. Checkpoints are never committed.

## Concurrent evidence (not stems-only)

Separation and full-mix AMT are parallel **slots**. Stem AMT runs only when a
separator actually produced audio. Reconciliation keeps unmatched full-mix notes
and drops weak unmatched specialist ghosts.

## What this increment changes in production MIR

- Default performance quantizer **consumes** pipeline hands/voices instead of
  always re-running Viterbi. Unlabeled piano still infers. Non-piano stays
  `UNKNOWN` hands.
- Named MIDI RH/LH tracks set `hand_locked` in `PerformanceSnapshot.to_notes()`.
- Meter candidates include **9/8**. Explicit file `9/8` is authoritative.
  12/8 may still collapse to 6/8 on ties (existing MVP prior).

## Explicitly not in this increment

- Real RoFormer / Transkun / Beat This! inference
- Switching `tasks.py` onto `PipelineOrchestrator` for live audio jobs
- Server MuseScore PDF/SVG
- Pedal-aware written duration
- Joint probabilistic hand/voice/rhythm search
- Rewriting `adaptive_quantizer` (it remains the alternate engine)
- Flattening ensembles into piano

Those wait on licenses, checkpoints, and tests — not on faked outputs.

## Checkpoint: musical time in production

`UnderstandingPipeline` now maps note seconds through `MusicalTimeMap`
(beat timestamps). `stabilize_tempo_map` remains for printed/display tempo
only. See `docs/MUSICAL_TIME_INTEGRATION.md`.
