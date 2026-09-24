# NotaScore engine roadmap

Canonical development plan for reliable, editable solo-instrument and piano
scores. Historical reviews stay in dated `docs/` files. New engine work is
scheduled here.

Reviewed baseline for this plan: `a05664c` / PR #77. No newer `origin/main`
commits were present when this file was written.

This is a plan, not a claim that musical quality is solved. Synthetic tests,
valid MusicXML, and successful PDF export are not proof of musical quality.

## Contracts

These are non-negotiable unless a later milestone explicitly revises them
with comparative evidence:

- Preserve original MIDI bytes, source-note identities, and performed timing.
- Keep performance, musical interpretation, notation, and user corrections distinct.
- Automatic and edited scores use the shared planner.
- Preserve exact tuplets, ties, articulation ownership, and accepted corrections.
- Keep readable-v2 (`performance-score-2`) opt-in until comparative evidence
  supports a rollout. Do not silently migrate existing jobs.
- Do not treat synthetic fixtures or export success as musician-reviewed quality.

Live product code is `audio2score-week4/`. Status values: **verified**,
**implemented but unverified**, **missing**, **blocked**.

## P0 — Trustworthy release checks and runtime identification

**User problem.** A save and a reset on the same revision can race. Diagnostics
that treat printed MusicXML lanes as musical voices report false grouping
changes. Operators cannot tell which provider, fallback, timing source, planner,
or notation version actually produced a score.

**Current implementation and evidence.**

- Edit publish is fenced by `database.cas_update_job` after writing an
  unpublished bundle (`main._write_revision_bundle`). Reset without stored
  notation settings publishes `edited_result_storage_key=None` through the
  same CAS. The save/reset test still waited on `_write_edited_sidecars`,
  which is no longer the save path.
- Quantization decisions already store `hand`, `musical_voice`,
  `printed_voice`, `voice_provenance`, and locks. The v1/v2 comparator
  grouped editor `voice` (printed lane). On development MIDI
  `138_с_chords_piano`, musical voice is `0` for every note on both
  versions; two notes change printed lane after v2 duration changes.
- Runtime identity already exists in pieces: `TranscriptionResult.diagnostic_payload()`,
  `PipelineDebug`, `{job}.notation_settings.json`, quantization summary
  (`engine`, `beat_origin_source`, `algorithm_version`). It is not assembled
  for diagnostics.

**Modules.** `main.py`, `database.py`, `publishing.py`, `tests/test_publish_fencing.py`,
`mir/performance_score.py` (`_stable_lanes`), `mir/notation_regen.py`,
`evaluation/readable_v2_rollout.py`, `mir/runtime_identity.py`,
`mir/models.py`, `mir/debug.py`.

**Dependencies.** None. This milestone must land before P2 metric work treats
138 as a musical-voice defect.

**Implementation tasks.**

1. Synchronize save/reset and concurrent-save tests at `cas_update_job`.
   Deterministic barriers; capture exceptions from both threads; assert the
   winning revision points at a complete bundle (or a clean reset).
2. Fix production only if the corrected test exposes a real publish defect.
3. Compare staff, musical-voice grouping, and printed lanes separately.
   Match notes by `source_note_id`.
4. Assemble existing runtime metadata for diagnostics. Do not add it to
   ordinary editor responses.

**Acceptance criteria.**

- Competing same-revision save/reset cannot both publish.
- Winning save bundle contains consistent JSON, MusicXML, and score MIDI.
- Winning reset clears the overlay and leaves original MusicXML bytes.
- 138 reports printed-lane adjustment, not a musical-line regrouping.
- A real musical-voice regrouping and a staff swap are still detected.
- User-locked staff/voice stay locked.
- Runtime identity reports provider, fallback reason, timing source, planner,
  and notation version from existing artifacts.
- Internal fields stay off ordinary user edit payloads.

**Status.** Implemented in this increment; verification is the focused test
run recorded in the PR.

## P1 — Reviewed musical baseline

**User problem.** We cannot say whether a score is musically good. Existing
gates prove preservation, structure, and export plumbing.

**Current implementation and evidence.**

- Evaluation already exists: `evaluation/notation_fixtures.py`,
  `evaluation/readable_v2_cases.py`, `evaluation/readable_v2_rollout.py`,
  `benchmark/fixtures/catalog.py`, stage gates in
  `docs/PERFORMANCE_FOUNDATION.md`.
- Inventory on `a05664c`: synthetic fixtures and catalog MIDI; three local
  NotaTestSamples raw/quantized/audio pairs
  (`evaluation/development/NotaTestSamples`) with undocumented license,
  not musician-reviewed. `benchmark/realworld/local` empty.
  `evaluation/paired_corpus` empty. No licensed commercial recordings.
- Families already covered synthetically: solo detached line, short rests,
  independent voices, pedal/repeats, triplets, syncopation, pickup
  (`rubato_pickup`), 3/4, 6/8, mixed release, crossing hands.
- Missing: musician review labels, held-out vs development composition
  split for a 10–15 example reviewed set, acoustic-accuracy labels.

**Modules.** `evaluation/*`, `benchmark/*`, `docs/PRODUCTION_SCORE_QA.md`,
`docs/MUSICAL_INTERPRETATION.md`.

**Dependencies.** P0 metrics so voice scores are not printed-lane noise.

**Implementation tasks.**

1. Inventory available assets in-repo. Mark missing audio, labels, reviews,
   and licenses explicitly. Never fabricate them.
2. Select 10–15 short examples covering solo lines, piano accompaniment,
   independent voices, pedal/repeats, intentional rests, detached
   articulation, triplets, syncopation, pickups, 3/4, 6/8.
3. Keep compositions disjoint between development and held-out splits.
4. Score four tracks separately: acoustic accuracy, interpretation
   accuracy, export integrity, correction effort.
5. User-recorded performances are valid. Commercial recordings are not
   required.

**Acceptance criteria.**

- Written inventory with provenance and permitted use for every example.
- Missing material listed as missing.
- Development and held-out compositions do not overlap.
- Reviews, if present, are attributed. No invented quality scores.

**Status.** Missing. Infrastructure is present; the reviewed set is not.

## P2 — Musical interpretation improvements

**User problem.** Wrong tempo scale, shifted downbeats/pickups, and broken
voice continuity make a score unusable even when export is valid.

**Current implementation and evidence.**

- Performance engine: `mir/performance_score.py`, shared planner
  `notation_engine/plan.py`. Readable-v2 is opt-in
  (`performance-score-2`). Last-note triplet pulse and relative leftover
  fill are tested. Independent holds are not clipped on synthetic cases.
- 138: musical voice unchanged; printed lanes move after duration fill.
  Not a P2 musical-line bug. Residual duration spelling on that
  development file is unverified musically.
- Tempo-scale search exists (`mir/score_interpretation.py`) but is not a
  reviewed quality claim.

**Modules.** `mir/performance_score.py`, `mir/score_interpretation.py`,
`mir/voice_separator.py`, `mir/meter.py`, `evaluation/readable_v2_cases.py`.

**Dependencies.** P1 examples for anything claimed as musical benefit. P0
metrics before treating 138 as voice work.

**Implementation tasks.**

1. Prioritize tempo scale, downbeat/pickup alignment, and voice continuity.
2. Use paired counterexamples for every heuristic change.
3. Preserve deliberate rests, independent holds, and user-locked decisions.
4. Do not retune readable-v2 from 138 printed-lane movement.

**Acceptance criteria.**

- Each change has a labeled pair: intended improvement and a case that
  must not regress.
- User-locked timing, staff, and voice survive.
- No claim of quality without P1 reviews.

**Status.** Missing as a reviewed interpretation program. Several synthetic
heuristics are implemented but unverified musically.

## P3 — Controlled readable-v2 rollout

**User problem.** Readable-v2 can write more conventional durations, but
turning it on by default would silently change existing jobs and may erase
intentional rests.

**Current implementation and evidence.**

- Default `performance-score-1`. Opt-in `performance-score-2`.
- Broader comparison and corrected metrics published in PR #76 / #77.
- Promotion must require no preservation regressions and documented
  musical benefit. That benefit is not yet musician-reviewed.

**Modules.** `mir/notation_settings.py`, `evaluation/readable_v2_rollout.py`,
job settings persistence.

**Dependencies.** P1 reviewed examples and P2 if interpretation still
diverges on those examples.

**Implementation tasks.**

1. Write promotion criteria before the next evaluation, including
   correction effort.
2. Compare v1/v2 on the reviewed set.
3. Prepare a reversible new-job-only setting. Do not enable it in this
   milestone.

**Acceptance criteria.**

- Criteria exist before scores are judged.
- Default remains v1. Existing jobs stay on their stored version.
- Rollout machinery is reversible and unactivated.

**Status.** Comparison implemented but unverified as a rollout decision.
Enablement is out of scope.

## P4 — Correction workflow and engraving

**User problem.** Common timing, meter, staff, and voice mistakes should be
repairable without retranscribing. Automatic, edited, and exported scores
must agree.

**Current implementation and evidence.**

- Corrections keyed by `source_note_id` (`mir/notation_regen.py`).
- Unrelated velocity edits keep engraving structure
  (`tests/test_export_evidence_structure.py`).
- Mixed-chord articulation ownership is in MusicXML; OSMD may still show
  a unioned mark. Documented, not discarded.
- Grand-staff 56-bar score produces two real PDF pages (PR #77). Visual
  review is not claimed from screenshots.

**Modules.** `main.py` score-edit routes, `score_edits.py`,
`mir/notation_regen.py`, frontend editor, OSMD export.

**Dependencies.** P0 publish fencing so concurrent save/reset cannot corrupt
a correction.

**Implementation tasks.**

1. Assess existing controls before adding UI.
2. Verify automatic, edited, and exported scores agree after common edits.
3. Re-validate dense and multi-page output after any layout change.
4. Keep the mixed-chord renderer limitation documented.

**Acceptance criteria.**

- Timing, meter, staff, and voice repairs do not resubmit transcription.
- Source MIDI bytes unchanged.
- Export integrity remains separate from visual review.

**Status.** Partial: correction plumbing implemented but unverified as a
complete workflow. Renderer limitation documented.

## P5 — Later scope expansion

**User problem.** Changing meters, richer marks, and ensembles are requested
but are outside the reliable MVP.

**Current implementation and evidence.**

- Snapshots retain tempo/meter changes. Changing meter on the MIDI CLI
  path is rejected.
- Mixed GM programs fail closed in performance mode.
- Ensembles are explicitly deferred in `docs/PERFORMANCE_FOUNDATION.md`.

**Modules.** Future work on `mir/performance.py`, planner, editor.

**Dependencies.** Independently validated P1–P4.

**Implementation tasks.** Changing meter, richer expressive notation,
ensembles. Each needs its own validation, not an MVP claim.

**Acceptance criteria.** Not in the current reliable-MVP claim until
independently validated.

**Status.** Missing. Intentionally out of scope.

## Evidence rules

| Kind | Allowed claim |
|---|---|
| Code inspection | What the source does |
| Local tests / commands | What ran in this workspace |
| Committed evaluation reports | What those reports record, with provenance |
| Musician review | Only when a named review exists |
| Missing audio, labels, licenses | Mark missing. Do not invent |

## Suggested next milestone

After P0 is verified: **P1 reviewed musical baseline**. Inventory is honest
enough to start selection; reviews and held-out labels are the gap.
