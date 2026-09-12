# Engine review and next three Cursor phases

## Current baseline

Reviewed and fast-forwarded local `main` from `20809b7` to remote `8d75b37` on 2026-09-12. Six commits changed 30 files. The checkout was clean before the pull. This document supersedes the implementation plan in `CURSOR_ENGINE_HANDOFF_2026-09-12.md`; that document remains historical evidence.

The update implements important parts of the previous plan: database compare-and-swap for edits and worker attempts, immutable publication paths, performance-sidecar editor initialization, frozen note/event records, explicit returned notation results, production-only quantizer entry points, stale claim recovery, and attempt cleanup. Preserve these changes and the existing attack-integrity tests.

## Fixes made during this review

These changes are in the working tree on top of `8d75b37`, not committed or pushed. Preserve them when preparing Cursor branches.

- **Worker scratch isolation:** published keys were unique, but local attempts still generated sidecars in the same `bp_<job>` directory. An expired worker could replace the winning worker's MIDI before upload. Every invocation now copies its input into a private temporary workspace and cleans it up after processing. Remote downloads also receive unique local names. The original upload remains intact.
- **Editor response consistency:** a save could combine its own notes with a revision fetched after another writer committed. Responses now use the revision actually committed by that request, retaining useful conflict detection for the next save.
- **Lossless and failure-safe reset:** reset now loads the canonical original performance model before its compare-and-swap. It retains source identity and seconds timing, and an unreadable original no longer clears a valid existing edit before returning an error.
- **Nested local cleanup:** deleting a result could attempt to unlink an edit directory as a file. Cleanup handles these directories explicitly.
- **Edited MIDI fidelity:** overlapping same-pitch voices now use separate MIDI instruments/channels. Export resolution is 960 PPQ so rounding at the supported minimum tempo stays within the existing 2 ms validator tolerance. This is not a complete MIDI tempo-map or arbitrary-channel solution.
- **Unsupported fused ensemble fallback:** live fusion previously sent multiple instruments to the solo score planner and failed the entire job. The orchestrator now checks compatibility before interpretation, keeps fused artifacts/review evidence, and explicitly uses full-mix notes for notation if fusion is incompatible. It records a warning and the actual interpretation source. Compatible fusion continues to drive notation. Unsupported full-mix ensembles still fail the existing guard; this does not implement ensemble engraving or suppress arbitrary planner errors.

Five lifecycle regressions and two MIDI regressions were reproduced as failures before the fixes. A remote-download isolation test was added. The four failing live-orchestration cases also failed on an untouched archive of `8d75b37` (4 failed, 5 passed). The ensemble test now asserts the explicit full-mix fallback, preserved fusion additions, and warning; a new test asserts compatible fusion still drives interpretation.

## Remaining findings driving the plan

1. Worker progress writes occur at stage boundaries, not periodically during long inference. Claim recovery only runs when another invocation arrives; there is no demonstrated scheduler that rescues every abandoned job. `updated_at` also mixes general metadata updates with lease health. Immediate bundle deletion can race readers that already captured the old pointer. Remote object listing has no pagination. Publication still lacks a verified manifest of required artifacts and hashes.
2. Editor data is not yet a complete canonical score contract. Meter loading expects `ratio`, while meter candidate rows use `meter`, and candidates are not necessarily the selected decision. The initial editor reads the full-mix performance snapshot even when notation was produced from reconciled notes. Track IDs are clamped to four tracks, long durations to 32 beats, and voices are reassigned. Missing tempo evidence silently substitutes 120 BPM. The seconds-based MIDI path preserves absolute timings but emits a constant-tempo MIDI rather than the full tempo event map, and finite MIDI channels need explicit allocation. Browser autosave clears its dirty flag after an in-flight request even if newer local edits arrived.
3. Job ownership is improved but still shallow: `NotationResult.copy()` shares `plan`, `QuantizationResult.copy()` shares `report`, and nested diagnostics remain mutable. Some pipeline coordination still reads `last_*`. Export integrity measures fidelity to supplied notes, not accuracy against audio. Ensemble routing and score readability require a measured rollout, not just a passing unit suite.

## Phase 1 — Make job and editor lifecycle reliable

**Outcome:** long jobs, process crashes, retries, downloads, autosave, and reset cannot silently lose accepted work.

**Scope:** `backend/database.py`, `tasks.py`, `storage.py`, `publishing.py`, editor handlers in `main.py`, queue/recovery integration, `frontend/hooks/useScoreEditor.ts`, and lifecycle tests. Read the frontend `AGENTS.md` before changing it.

1. Add dedicated lease timestamps and an attempt-fenced heartbeat that runs during inference and upload. Implement a bounded recovery scan/requeue policy with backoff, retry limits, and observable terminal errors. Fenced-out workers must stop or discard all subsequent work.
2. Validate required output files and hashes, then atomically publish a versioned manifest pointer. Define required artifacts per engine/mode; optional diagnostics must not be mistaken for required performance evidence. Test partial upload, corrupt output, DB failure, and deletion during processing.
3. Replace immediate deletion of previously committed bundles with delayed, reachability-aware collection. Include active claims, in-flight readers/download expiry, partially staged bundles, nested local edits, remote pagination, and deletion of all job artifacts. Separate cleanup failures from transcription failures.
4. Serialize autosave or use a generation counter: acknowledge only the submitted edit generation, retain newer dirty state, prevent old requests from mutating a newly opened score, and make reset use the client's expected revision. Handle 409 by preserving local changes and offering reload/reapply.

**Acceptance:** deterministic tests against real SQLite CAS and the deployed database type; one winner for competing writers; a slow live worker is not reclaimed; a killed worker is eventually retried without manual invocation; stale workers cannot publish; an old reader can finish during a save/reset; pagination removes all eligible objects; edits made while a save is in flight are eventually saved; stale reset cannot erase a newer edit. Exercise local storage and a paginated remote-storage fake, then a staging multi-worker smoke run.

**Cursor prompt:** Implement Phase 1 from this file on a branch starting from the reviewed working-tree fixes. Begin with failing lease, reader/GC, and autosave race tests. Keep attempt fencing and private scratch directories. Do not change transcription or quantization policy. Deliver a reviewable commit with migration/recovery behavior, test results, and unresolved risks.

## Phase 2 — Establish one lossless editable performance contract

**Outcome:** opening, changing pitch, saving, resetting, downloading, and reopening describe the same musical performance and the same chosen score source.

**Scope:** `mir/performance.py`, `mir/job.py`, `mir/pipeline.py`, `timing/service.py`, `score_edits.py`, API models, frontend editor/playback models, and export/reimport tests.

1. Introduce a versioned canonical sidecar with selected meter, beat origin/pickup, full exact tempo map, source IDs, instrument/program, staff and voice assignment, beat positions, seconds positions, and provenance. Explicitly distinguish full-mix evidence, accepted reconciled score notes, and printed notation. Save the selected meter rather than inferring it from the first candidate.
2. Define pitch-only versus timing-edit semantics. Preserve untouched fields exactly; reject unsupported sizes/ranges explicitly instead of silently clamping tracks, duration, or tempo. Handle missing/corrupt legacy sidecars with explicit degraded provenance and a tested migration path.
3. Export full tempo events and exact note timings together. Allocate overlapping unisons across safe MIDI channels, excluding the percussion channel, with defined behavior when channel capacity is exhausted. Preserve programs and validate using an independent parser. Do not use the current constant-tempo seconds export as proof of tempo-map fidelity.
4. Make returned stage results independent through immutable nested types or well-defined defensive copies. Derive compatibility diagnostics from those results and eliminate reads of mutable `last_*` state as stage inputs. Keep one pipeline instance per job unless reentrancy is implemented and tested.

**Acceptance:** API GET → pitch edit → PUT → MIDI/XML download → reimport, then reset and repeat. Cover actual selected 3/4 and 6/8 meters, tempo changes inside beats, pickups, >512-point curves, >32-beat held notes, repeated/unison overlaps with different releases, multiple programs, >4 tracks, and missing legacy evidence. Check exact source multiplicity, selected score source, staff/voice/program, timing within documented MIDI tick tolerance, and tempo event equivalence. Nested diagnostic mutation must not change exported artifacts. Browser playback must match downloaded MIDI timing.

**Cursor prompt:** Implement Phase 2 after Phase 1 is integrated. Treat canonical schema and migration as the first deliverable, then integrate API/editor/export. Preserve original audio/MIDI evidence and all attack-integrity gates. Demonstrate a pitch-only round trip through the real API, not just helper functions. Report supported limits and remaining degradation explicitly.

## Phase 3 — Improve transcription and engraving against a fixed corpus

**Outcome:** measurable accuracy and readable scores, with explicit confidence and conservative fallback when the engine is uncertain.

**Scope:** existing `evaluation/`, `benchmark/`, fusion/reconciliation, timing and meter selection, notation planner/writer, and production readiness checks. Reuse `docs/PRODUCTION_SCORE_QA.md` and existing evaluation tooling.

1. Freeze a licensed development/holdout corpus with auditable MIDI and human-reviewed audio references. Include solo piano, non-piano solo, rubato, pickups, tuplets, rapid repeats, sustain, noise, and ensembles. Record code SHA, model/version, configuration, hardware, and artifact hashes for every run.
2. Report pitch/onset/offset precision and recall, timing error distributions, meter/downbeat errors, missing/invented attacks, and full-mix versus fusion additions/suppressions separately. Predeclare regression thresholds from the baseline; do not tune on holdout or equate export success with audio accuracy.
3. Optimize one failure class at a time. Keep experimental quantization behind explicit comparison entry points. Use uncertain timing conservatively. For fusion, validate instrument-aware part assignment and provenance before replacing the explicit full-mix fallback with ensemble notation; never flatten instruments into one piano staff merely to pass export.
4. Improve engraving with measured examples: staff/voice allocation, chord grouping, ties and rests, tuplets, beaming, spelling, and page/system density. Produce before/after SVG or PDF examples for blind musician review. Preserve exact playback independently of simplified notation.
5. Run actual inference readiness checks for optional models, benchmark latency/memory and failure rate, then perform a staged rollout with rollback conditions. Enable components only when the relevant corpus and operational gates pass.

**Acceptance:** a reproducible baseline-versus-candidate report, zero new source-attack integrity failures, explicit per-category accuracy/latency deltas, holdout results, musician-reviewed before/after scores, and a tested rollback. New ensemble support must preserve instrument identity and show higher measured utility than the current fallback. No claim of universal accuracy or “perfect” notation follows from automated tests alone.

**Cursor prompt:** Execute Phase 3 using the existing evaluation framework. Commit the frozen baseline/configuration and report first. Choose the highest-impact measured failure, implement one focused improvement, and publish reproducible metric deltas plus visual score examples. Keep optional features gated until inference, accuracy, readability, and operational checks pass.

## Verification

Final verification results are recorded below after the test run. Live MT3/PM2S tests, deployed database/storage integration, and browser interaction are outside this local review. Core ML tests require execution outside the filesystem sandbox; the initial sandboxed run failed three inference tests for that environmental reason.

Final working-tree run on top of `8d75b37`:

```sh
cd audio2score-week4/backend
.venv/bin/python -m pytest -m 'not integration and not pm2s' -q
# 686 passed, 4 deselected, 20 warnings in 23.64s
```

The four deselected tests require live integration/PM2S validation. Warnings are dependency deprecations and small-audio FFT warnings. No frontend/browser or deployed multi-worker validation was performed. `git diff --check` passes. Test-generated benchmark report changes were restored to their pre-review contents; generated worker bytecode was moved outside the repository. The local fixes and this handoff are intentionally uncommitted and unpushed.
