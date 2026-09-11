# Next-gen rebuild baseline

Recorded **before** architectural changes. Do not treat later green tests as
proof that this snapshot was wrong. Thresholds were not tuned to obtain these
results.

| Field | Value |
|---|---|
| Git | `5a6ca7bff174d344a7e029c3b830cb4a9903466f` (`main`) |
| Message | Merge pull request #47 from kozloved/codex/performance-foundation |
| Date recorded | 2026-09-11 |
| Production tree | `audio2score-week4/` |

## Commands run

From `audio2score-week4/backend`:

```sh
python -m pytest -q tests/test_performance_foundation.py \
  tests/test_performance_score.py tests/test_performance_cli.py \
  tests/test_quantizer_identity.py tests/test_score_ab.py
# 46 passed

python -m pytest -q tests/test_regression_benchmark.py \
  tests/test_canonical_benchmark.py tests/test_hand_separator.py \
  tests/test_voice_preservation.py tests/test_notation_plan_production.py \
  tests/test_midi_ingest.py tests/test_meter_quantizer.py \
  tests/test_forensic_preservation.py tests/test_raw_midi.py \
  tests/test_tempo_map.py tests/test_meter_arbitrator.py
# 111 passed

python -m benchmark.runner --mode midi --subset ci
# MIDI ingest: 21/21 passed, 0 fallbacks, 0 regressions

python -m benchmark.run_suite
# 4/4 structure cases PASS

python -m evaluation.score_ab benchmark/corpus --out /tmp/nextgen-baseline/score-ab-synthetic
# 21/21 adaptive=ok, performance=ok
```

## MIDI ingest CI gate (`--mode midi --subset ci`)

All 21 cases F1 1.00, NotationPlan fallbacks 0, false legitimate-note removals 0.

Hand accuracy is still the structure-separator metric (hands stripped, then
Viterbi), not Fast-audio hands. Known non-gated ambiguity remains:

| case | hands | meter_eval |
|---|---:|---|
| midi_chords_and_melody | 0.62 | 4/4 |
| octave_doubling | 0.67 | 4/4 `[METER_AMBIGUOUS]` |
| polyphonic_rh | 0.83 | 4/4 |

Development A/B from `PERFORMANCE_SCORE.md` (unchanged; not re-run here
because those MIDI files are gitignored):

| Case | Adaptive onset F1 | Performance onset F1 | Adaptive offset F1 | Performance offset F1 |
|---|---:|---:|---:|---:|
| Case1 | 1.000 | 0.857 | 0.571 | 0.857 |
| Case2 | 1.000 | 0.929 | 0.071 | 0.786 |
| Case3 | 1.000 | 1.000 | 1.000 | 1.000 |

Do not relax gates to hide Case1/Case2 onset regressions.

## Raw MIDI preservation hashes

Probe MIDI (8 notes, 120 BPM) SHA-256:

```
05506f9f7264bf465c10393db692d7285a90047628636236e21329ca46a1c2b2  (122 bytes)
```

| Artifact | SHA-256 | Equals source? |
|---|---|---|
| CLI source `.mid` | `05506f9f…a1c2b2` | — |
| `PerformanceSnapshot.midi_sha256` | `05506f9f…a1c2b2` | yes |
| Pipeline `{job}.raw.mid` | `05506f9f…a1c2b2` | yes |
| Pipeline `{job}.validated.mid` (no cleaner mutations) | `05506f9f…a1c2b2` | yes |
| `{job}.score.mid` / CLI score MIDI | `3917b5ed…24b2e03` (191 bytes) | **no** |

Invariant held: `raw.mid != score.mid`, and raw bytes equal the original file.

CI corpus `input.mid` hashes:

```
melody_simple/c_major_quarters            0d5275a90417887a6ec0bba54fcf1949fa0f1cf54618b76f48b043bd7ac1b462
melody_simple/g_major_eighths             71273edb82826d72a40ffa13051807e14dacd0103f79fe3d6328df763bc931f8
midi_ingest/midi_3_4                      7c2318e07283ff5be9b36859909948a4f9b7e23d389e1f9033039a92c51e4d68
midi_ingest/midi_6_8                      126bbb1d64c8a75de0799e1455a5f2eaf98281d59cef253458f1de8111528be3
midi_ingest/midi_chords_and_melody        c4ad15eeedf6d42c177eccc9b185b1a31b5bcadb56ba360bbc5318c1a4abc440
midi_ingest/midi_rh_lh_tracks             63d6b9190f22dbadcc99eeee8103569c7c5307cf78650990d7ab0974128660f8
piano_chords/c_major_block_chords         23e8aabcda6cb211ecdf72a6e0133c6970308c1bcae6f9b5192b6f132dc9f5ef
piano_chords/octave_doubling              9ae4a33884c28b55c621e0ba41bd4239aff1da6af6b8c6df3b3baa8090f3363d
piano_simple/melody_and_bass              de76aa46964aa820df7b2825dfb61cfde11c0385e9acb70ffee78764c11e30f4
piano_two_hands/hand_crossing             a881ce46c3ea48806f485119628812f22ed89e5e399eaa82f669dd86535b359d
piano_two_hands/middle_register           dbda444ee94a45c66fd0efda8968ddb8be872e31fe8410fb5cf132699e01f468
piano_two_hands/polyphonic_rh             926934f98a5cb5a034481c57b4c9b9df1f1173c5062ec0f855c9efcc9cf5e46a
piano_two_hands/two_hand_scale            f573c9d15ceadff76cdcbf0d0b3f06e41e9bc15f19d15b2fe9aa6c6c13f16843
rhythm/compound_6_8                       c0b701b9b5d9647da3fe542d838ea53d42e519eadc9814a411c4ede8ffd76063
rhythm/dotted                             016302e7c00996b37f62bf80c08ca8e22c6d55d10ab8e6b12956c7a8fe01f9bd
rhythm/eighths                            64de46b653a3e580467bd536a6a76a0e8a9735b1c6a4738adc402276476d2230
rhythm/quarters                           41567adade4182cd5eca77efe5adfdfc724fd7d97e2d7355bb0e73988ee276f2
rhythm/sixteenths                         f713f79b9cd40debbcb2124d8cd50709abb01d04bb17950573c71a6fbbfe42e3
rhythm/syncopation                        bed818b02913ebd3fb87a5592be3ecfe9785a66ec3207dab152c4869861960ec
rhythm/triplets                           edda21b1206e6c680cce5e737bd4349af9b80b8d6125a9071f06acb4ca1c9448
rhythm/waltz_3_4                          88b56ce48b89bec0e2dd6da52ec162667401dd12855a19745e1e45d239109c06
```

## What is production code

Live request path: `audio2score-week4/frontend` → `backend/main.py` → RQ
`tasks.process_job` → `transcription.get_engine()` →
`mir.pipeline.UnderstandingPipeline` → `notation_engine.writer`.

| Area | Location | Role |
|---|---|---|
| API / jobs | `audio2score-week4/backend/main.py`, `tasks.py`, `job_queue.py` | Upload, queue, result URLs |
| Orchestrator today | `mir/pipeline.py` | Audio/MIDI → MusicXML |
| Immutable MIDI | `mir/performance.py`, `mir/raw_midi.py` | Snapshot + byte-identical `.raw.mid` |
| Interpretation | `mir/performance_score.py`, `mir/adaptive_quantizer.py` | Default `performance` quantizer |
| Hands / voices | `mir/hand_separator.py`, `mir/pm2s_hands.py`, `mir/voice_separator.py` | Viterbi + optional PM2S |
| Meter | `mir/meter.py`, `mir/meter_arbitrator.py` | 2/4 3/4 4/4 6/8 12/8 |
| Tempo | `audio_engine/beat_tracker.py`, `mir.types.TempoMap` | Beat tracker + piecewise BPM |
| Adapters | `adapters/basic_pitch_backend.py`, `adapters/mt3_backend.py`, `mir/midi_ingest.py` | Solo / polyphonic / MIDI |
| GPU worker | `mt3-worker/` | YourMT3 RunPod image (MIDI out) |
| Export | `notation_engine/` | NotationPlan → MusicXML / score MIDI |
| UI | `audio2score-week4/frontend` | OSMD render, jsPDF, MIDI listen, editor |
| Eval | `evaluation/`, `benchmark/` | Stage gates, MIDI corpus, A/B |

## What is legacy compatibility

- `transcription.BasicPitchEngine` and `TRANSCRIPTION_PIPELINE=legacy`
- `TRANSCRIPTION_PIPELINE_FALLBACK=1` (understanding → enhanced legacy)
- `notation_engine/quantize.py` 16th/triplet snap + music21 `score.quantize`
- `QuantizationMode.ADAPTIVE` / `STRICT_GRID` / `OFF` / `PM2S`
- Root `README.md` Fast/Quality language vs live Solo/Polyphonic
- `docs/CORE_ENGINE_AUDIT.md` (2026-08-24; MT3/MIDI claims are stale)

## What is dead or disconnected

- Root `backend/engines/*`, `backend/workers/mr_mt3_worker.py` — not on the live `sys.path`
- `frontend_redesign/` — mock UI
- `REMOTE_GPU_ARCHITECTURE.md` — one-line stub; live GPU contract is `mt3-worker/` + `adapters/mt3_backend.py`

Do not implement next-gen features in those trees.

## What is experimental / flagged off

- Gemini music analysis (`TRANSCRIPTION_ENABLE_GEMINI`, default off)
- PM2S rhythm/hands (opt-in; missing weights → identity/viterbi)
- `ClassicalDspBackend`
- Ensemble MIDI: performance mode **rejects** mixed GM programs (intentional)

## What the performance-foundation work already fixed

- Original MT3/customer MIDI bytes retained; `.raw.mid` is not a piano reconstruction
- Frozen `PerformanceSnapshot` with SHA-256, programs, controllers, bends, drums
- Short source notes not lengthened at CMR ingest
- Solo non-piano: one staff, no piano hands
- Score MIDI is a derived notation artifact, distinct from raw
- Independent `evaluation.stage_gate` for score vs transcription

## Duplicate abstractions still present

| Concern | Copy A | Copy B |
|---|---|---|
| Raw performance | `mir.models.RawPerformance` (mutable) | `mir.performance.PerformanceSnapshot` (frozen) |
| Tempo | `TempoMap` (BPM regions) | Beat times exist on tracker but often collapsed |
| Quantization | `performance_score` (default) | `adaptive_quantizer` + legacy music21 grid |
| Hands | Pipeline Viterbi/PM2S | **Performance quantizer re-runs Viterbi** on current main |
| Job artifacts | `{id}.raw.mid` / `.score.mid` / `.musicxml` / `.debug.json` | No typed manifest; storage keys are flat |
| Transcription | `adapters/*` | No capability router / fusion |

## Gaps versus the target product

Missing on this baseline (must be added, not faked):

- Stem separation (RoFormer family) — no adapter, no stems
- Transkun V2 piano specialist — no adapter
- Full-mix AMT **and** stem AMT as parallel evidence with reconciliation
- Typed stage orchestrator (ANALYZE / SEPARATE / TRANSCRIBE_* concurrent)
- Beat-time musical map (rubato): tracker exists, printed vs performance tempo is only partly separated (`snap_to_standard_tempo` for display)
- 9/8 meter candidate
- Artifact manifest
- Ensemble / per-part score (flagged deferred)
- Server PDF/SVG (PDF is client OSMD → jsPDF)
- Stem/score synchronized playback of separated audio

## Licensing notes at baseline

- In-tree MT3 path talks to a **remote** worker (`mt3-worker/`, YourMT3 / mt3-infer). Do not import that worker code into the VPS API process.
- Basic Pitch is already a production Solo dependency.
- RoFormer / Transkun / Beat This! checkpoints are **not** in this repo. Adapters must be disabled until code+weight licenses are documented as SaaS-compatible. Large weights must not be committed.

## Product invariants this rebuild must not break

```
original bytes == PerformanceSnapshot.midi_sha256 == {job}.raw.mid
{job}.raw.mid != {job}.score.mid
notation never mutates source pitch / note identity
mixed GM programs do not silently become piano
```
