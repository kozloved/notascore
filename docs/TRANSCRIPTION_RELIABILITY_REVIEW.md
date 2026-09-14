# Transcription reliability review

Status: implemented on `cursor/transcription-reliability-eval-d331`.
Reviewed commit (historical reference, not a reset target): `595a0a0ca97d51587b86d8109868d9fee77907c4` (`origin/main` at branch time).
No repository `AGENTS.md` was present.

This document records what was implemented, what was already true on current main, tests actually run in this agent, and remaining gaps. It does not treat historical test output as newly run.

## 1. Implemented changes

| Phase | Commit | Summary |
|---|---|---|
| 1 | `94e8465` | Own transcription results so empty/drum-only MT3 MIDI can fall back to Basic Pitch without publishing MT3 bytes as a successful result. |
| 2 | `d85632f` | Capture original notes before optional filtering; apply the same derived-view gate on direct and live paths; keep filtering off. |
| 3 | `45b3011` | Evaluate through `engine.job_runner.run_job` by default; fail the process on regressions, missing required cases, execution errors, and all-skipped runs. |
| 4 | `0043238` | Named Basic Pitch comparison profiles; production defaults unchanged; Classical DSP marked non-operational. |
| 5 | `fe39711` | Persist RunPod provider job IDs and resume them on worker recovery; per-job timings; uncertain submission is distinct from “no job”. |
| 6 | `abe17b6` | Paired-corpus schema, composition leakage, ten-slot inventory, and this report. |

Hard invariants kept:

- Original provider MIDI bytes and checksum are hashed before parse.
- Original notes are stored before filtering or notation.
- Corrections, filtering, and score interpretations remain derived views.
- Basic Pitch is never labeled MT3 (`actual_backend` follows the successful attempt).
- Source note IDs and instrument/track identity are unchanged.
- Performed timing stays independent of written notation.
- Experimental models, confidence filtering, stem fusion, and production transcription thresholds were not enabled.
- This work does not merge or deploy.

## 2. Findings already fixed on current main

None of the six reported defects were already fixed on `595a0a0`. After fetch, `origin/main` matched that SHA. Newer hands/voice/barline work on that commit was left intact.

Still present before this branch:

1. Empty/drum-only MT3 left `prepared.backend` as MT3 and failed provenance after Basic Pitch fallback.
2. Direct pipeline filtered before the raw snapshot; live orchestration skipped that filter; amplitude was treated as confidence.
3. Evaluation constructed a shared `UnderstandingPipeline` and ignored baseline regressions in the process exit code.
4. Production Basic Pitch used `minimum_note_length=127.70` ms and `maximum_frequency=2093` Hz for mix and pitched stems, with no named comparison profiles.
5. RunPod `/run` was not persisted; recovery submitted another GPU job. Timings lived in `_LAST_PROVIDER_TIMING`.
6. Corpus leakage only keyed `performance_id`; there was no paired composition/score vs performed-timing workflow.

## 3. Tests actually run

Evidence classes used in this agent:

| Class | What it covers |
|---|---|
| Code inspection | Current main vs the reported defects; adapter/orchestrator/evaluation/database paths. |
| Mocked transport tests | Empty/drum-only MT3 HTTP fixtures; RunPod `/run`+`/status` resume; evaluation CLI with fake cases. |
| Actual model inference | Checkpoint 7 synthetic fixture (`piano_quarters_120`) through Basic Pitch in isolated evaluation tests. |
| Live GPU / RunPod | Not run. `test_runpod_live_adapter_if_configured` skips without `MT3_ENDPOINT` + `MT3_API_KEY`. |
| Browser / staging / production | Not run. These changes are backend/evaluation, not UI. |

Phase-local pytest (this agent, `audio2score-week4/backend/.venv/bin/pytest`):

- Combined required suite after all six phases, **newly run**:
  `test_transcription_fallback.py`, `test_confidence_filter_paths.py`,
  `test_live_orchestrator_job.py`, `test_evaluation_gate.py`,
  `test_evaluation_checkpoint7.py`, `test_basic_pitch_backend.py`,
  `test_basic_pitch_profiles.py`, `test_mt3_runpod.py`,
  `test_provider_jobs.py`, `test_paired_corpus.py`,
  `test_export_integrity.py`, `test_hands_rhythm_metrics.py`,
  `test_lifecycle_phase1.py`, `test_publish_fencing.py`,
  `test_production_validation.py`, `test_quantizer_identity.py`,
  `test_performance_foundation.py`, `test_notation_integrity.py`
  → **223 passed, 1 skipped** (12.68s). The skip is the live RunPod integration
  test without credentials.
- Isolated Checkpoint 7 fixture (`piano_quarters_120`) exercises real Basic Pitch
  inference on synthetic audio. That is not a paired-recording quality claim.

## 4. Migrations and configuration

Database (SQLite/Postgres via SQLAlchemy `init_db()`):

- New nullable job columns: `provider_job_id`, `provider_input_sha256`, `provider_config_sha256`.
- Added on startup through `_ensure_provider_job_columns()`. No separate migration script.
- Existing attempt fencing is unchanged. Requeue after lease expiry does **not** clear the provider job ID.

Evaluation CLI (`python -m evaluation.runner`):

- `--execution-path` defaults to `production` (`engine.job_runner.run_job`).
- `--mode` selects solo/Basic Pitch or polyphonic/MT3 (`fast`/`quality` remain aliases).
- `--pipeline-mode` sets `NEXTGEN_PIPELINE_MODE` for a case and restores it afterward.
- `--gate` and `--compare-baseline` fail on `REGRESSED` and missing required cases.
- All-skipped runs fail unless `--allow-all-skipped` is set (and `--gate` still fails them).
- Isolated stage tests still pass an explicit `UnderstandingPipeline` into `evaluate_case`.

Basic Pitch:

- Production profile is still onset 0.6, frame 0.4, min length 127.70 ms, 27.5–2093 Hz.
- `BASIC_PITCH_*` environment overlays are preserved and recorded in `env_overrides`.
- Optional `BASIC_PITCH_PROFILE` and `BASIC_PITCH_STEM_PROFILES` (default off).

Filtering and fusion remain **off**.

## 5. Remaining risks and blocked checks

**RunPod submission/persist crash window.** After `/run` returns a job id, that id is persisted before polling. A crash between a successful `/run` HTTP response and a durable row write can still start a second GPU job on recovery. Lost POST responses are now `provider_submission_uncertain` and are **not** retried as if no job exists. This is not exactly-once execution.

**Live GPU.** Empty/drum-only fallback, resume-on-recovery, and polyphonic evaluation were proven with mocked HTTP, not a real YourMT3 worker.

**Paired recordings.** All ten initial slots are missing audio, performed-note MIDI, score MusicXML, alignment, source, and permitted-use metadata. Inventory refuses quality claims until those exist.

**Production evaluation default.** The CLI now uses `run_job`. Isolated Checkpoint 7 tests still inject a pipeline. A production-path run against real audio was not executed here beyond a mocked `run_job` unit test plus the isolated Basic Pitch fixture.

**Stem profiles.** Pitched stems still share production Basic Pitch defaults unless `BASIC_PITCH_STEM_PROFILES=1`. That flag stays off.

**Classical DSP / Transkun / BeatThis.** Marked non-operational. Selecting `TRANSCRIPTION_BACKEND=classical_dsp` now fails clearly instead of running an unsupported stack.

## 6. Next recommended musical improvement

Justified by a **measured configuration fact**, not by a new inference bake-off:

Production Basic Pitch `minimum_note_length` is **127.70 ms**. A sixteenth note at 120 BPM is **125 ms**. The production profile can therefore drop legitimate short notes, ornaments, and repeated attacks before any later musical stage runs.

Do **not** ship `short_notes` (40 ms) or `ornaments` (30 ms) as production defaults yet. Those profiles exist only for comparison, and this agent did not run real Basic Pitch inference across a paired set.

Recommended next experiment, once the first ten paired recordings exist:

1. Keep production defaults as the control.
2. Run `--execution-path production --mode solo` on the paired development split.
3. Compare `production` vs `short_notes` vs `ornaments` using `evaluation.basic_pitch_profiles`, reporting **precision and recall** (not recall alone) on `short_notes`, `ornaments`, `repeated_attacks`, `high_piano`, `bass`, and `quiet_passages`.
4. Promote a profile only if inferred results improve F1 without a precision collapse, and only for the instruments that actually benefit.

Until that measured run exists, the winning profile is unknown.
