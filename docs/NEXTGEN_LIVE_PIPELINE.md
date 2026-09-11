# Next-gen live pipeline

This increment wires `PipelineOrchestrator` into production behind
`NEXTGEN_PIPELINE_MODE` and adds the first real parallel evidence path:

full-mix MT3 ∥ audio analysis ∥ HTTP stem separation → stem Basic Pitch →
deterministic fusion.

`UnderstandingPipeline` remains the interpretation / MusicXML export engine.
Ensemble engraving is still off.

The **first production cutover** sets `NEXTGEN_PIPELINE_MODE=live` with
separation, stem transcription, and fusion **off**. That promotes the
orchestrator without new external models. See
[`docs/NEXTGEN_LIVE_CUTOVER_CHECKLIST.md`](NEXTGEN_LIVE_CUTOVER_CHECKLIST.md).

## Modes (`NEXTGEN_PIPELINE_MODE`)

Default: **`legacy`**.

| Mode | Job owner | Full-mix AMT | Beat tracker | Separation | Score artifacts |
|---|---|---|---|---|---|
| `legacy` | `transcription.get_engine()` → `UnderstandingPipeline` | one MT3 (polyphonic) | one prefetch inside the pipeline | not run | unchanged from PR #50 |
| `shadow` | same production transcribe, then orchestrator analysis | **same single** MT3 | **no second pass** | **not run** | MusicXML / `raw.mid` / `score.mid` untouched |
| `live` | `PipelineOrchestrator` | one MT3 (polyphonic) | one prefetch, injected into interpretation | HTTP separator when polyphonic and enabled | current score path; fused/stems are extra artifacts |

Shadow may write `manifest.json`, `provenance.json`, timing already produced by
the production pass, and interpretation JSON. It must not send another MT3
request, beat-track again, run Basic Pitch on the mix, or alter the job result.

## Actual live path (FULL_SONG / polyphonic)

```text
tasks.process_job
      ↓
engine.job_runner.run_job          NEXTGEN_PIPELINE_MODE=live
      ↓
PipelineOrchestrator.run_audio
      ↓
INGEST
      ↓
PREPROCESS                         AudioNormalizer (once)
      ├───────────────┬────────────────┐
      ▼               ▼                ▼
ANALYZE_AUDIO    TRANSCRIBE_GLOBAL   SEPARATE
BeatTracker.track    MT3 (once)      HTTP SEPARATION_ENDPOINT
MusicalTimeMap         │                │
      │               │                ▼
      │               │          TRANSCRIBE_STEMS
      │               │          Basic Pitch (pitched stems only)
      │               │          drums → no pitched MIDI
      └───────────────┴────────┬───────┘
                               ▼
                         RECONCILE
                         MT3-first deterministic fusion
                               ▼
                     UnderstandingPipeline.complete_audio
                     (interpretation + MusicXML / score MIDI)
                               ▼
                       ArtifactManifest + provenance
```

Solo / `SOLO_PIANO` / `SOLO_INSTRUMENT` (resolved `solo`) skip GPU separation.

AUTO is not a new classifier in this increment. Existing
`solo` vs `polyphonic` is the routing signal.

## Stage trace

Each stage writes `StageResult` with `status`, `started_at`, `finished_at`,
`duration_ms`, `requested_backend`, `actual_backend`, `fallback`, `error`,
`model`, `model_version`. A failed separator is `status=failed` even when the
job continues on full-mix MT3. Provenance: `{job}.provenance.json`.

Telemetry splits:

| Stage | What is measured |
|---|---|
| PREPROCESS | normalize + wav write |
| ANALYZE_AUDIO | classifier + segmenter + beat tracker (`tracker_ms`) |
| TRANSCRIBE_GLOBAL | MT3 wall time; RunPod `delayTime` → `queue_ms`, `executionTime` → `execution_ms` when present |
| SEPARATE | HTTP separator wall time |
| TRANSCRIBE_STEMS | per-stem Basic Pitch |
| RECONCILE | fusion |
| INTERPRET_SCORE | MIR layers; `export_ms` is MusicXML write |

No warmup request is issued.

Live provenance (`{job}.provenance.json`) records `pipeline_mode`,
`orchestrator`, a `transcription` identity block (`provider_raw_sha256`,
`saved_raw_sha256`, `raw_identity_match`), and stage timings. It must not
contain API keys or credential-bearing URLs. MT3 provider SHA mismatch is
a hard fail (`raw_transcription_identity_violation`).

## Separation provider

**Enabled adapter:** HTTP `HttpSeparator` (`SEPARATION_ENDPOINT`).

**Disabled:** in-process RoFormer / MelBand-RoFormer checkpoints (license +
must not load a large model into the FastAPI/RQ worker). See
`docs/MODEL_LICENSES.md`.

Request body:

```json
{
  "audio_base64": "...",
  "filename": "job_norm.wav",
  "job_id": "...",
  "requested_stems": ["vocals", "piano", "guitar", "bass", "drums", "other"]
}
```

Response `stems` may omit labels. Missing stems are not invented. Unsupported
labels are ignored with a warning.

Stem audio is stored as `{job}.stem.{id}.wav` and listed on `ArtifactManifest`
(`kind=audio/stem`, `stem_id`, `storage_key`, `source_stage=SEPARATE`).

## Stem transcription

| Stem | Transcriber |
|---|---|
| piano | Basic Pitch now; Transkun slot later (`NEXTGEN_TRANSKUN=0`) |
| guitar, bass, vocals, other | Basic Pitch |
| drums | skipped (no fake pitched notes) |

Per-stem MIDI: `{job}.raw.{stem}.mid`. The full-mix `{job}.raw.mid` is never
overwritten.

## Fusion policy

Existing `transcription_fed.reconcile.reconcile_transcriptions`:

- Full-mix MT3 is the timing anchor (`keep_global_timing=True`).
- Matching stem evidence adds instrument identity, confidence, and provenance.
- Full-mix-only notes are kept.
- Weak stem-only ghosts stay in diagnostics, not in the fused performance.
- High-confidence stem-only notes may become derived candidates.
- Piano C4 and bass C4 at the same time stay two notes.

Artifacts: `{job}.fused.mid`, `{job}.fused.json`, `{job}.fusion.json`.
These are **not** named `raw.mid`.

Score generation still uses the full-mix interpretation while
`NEXTGEN_ENSEMBLE_RENDER=0`. Mixed GM programs are not flattened to piano to
force a score.

## Feature flags

| Flag | Default | Meaning |
|---|---|---|
| `NEXTGEN_PIPELINE_MODE` | `legacy` | `legacy` \| `shadow` \| `live` |
| `NEXTGEN_SEPARATION` / `NEXTGEN_SEPARATION_ENABLED` | `0` | Allow a separator to run |
| `NEXTGEN_SEPARATION_BACKEND` | `auto` | `http` if `SEPARATION_ENDPOINT` is set, else skip/RoFormer stub |
| `SEPARATION_ENDPOINT` | unset | External separator worker |
| `NEXTGEN_STEM_TRANSCRIPTION_ENABLED` | `0` | Basic Pitch on pitched stems |
| `NEXTGEN_FUSION_ENABLED` | `0` | Write fused performance artifacts |
| `NEXTGEN_ENSEMBLE_RENDER` | `0` | Multi-part score (still off) |
| `NEXTGEN_TRANSKUN` | `0` | Piano specialist slot |
| `NEXTGEN_BEAT_THIS` | `0` | Beat This! slot |
| `NEXTGEN_WRITE_MANIFEST` | `1` | `{job}.manifest.json` |

## API

Existing `/jobs/{id}/result?format=musicxml|midi|midi_score` is unchanged
(`midi` is still full-mix raw).

Added formats: `fused_midi`, `fused_json`, `manifest`, `provenance`, `tempo`.

Added routes:

- `GET /jobs/{id}/artifacts`
- `GET /jobs/{id}/artifacts/{filename}`

## What is real vs disabled

| Piece | Status |
|---|---|
| Orchestrator as job owner | real, behind `live` |
| MusicalTimeMap reuse | real (one tracker call) |
| HTTP separator adapter | real contract; off until endpoint + flag |
| In-process RoFormer | disabled |
| Stem Basic Pitch | real, behind flag |
| Transkun | disabled slot |
| Deterministic fusion | real, behind flag |
| Ensemble MusicXML | disabled |
| Beat This! | disabled |
| MuseScore PDF | disabled |
