# NotaScore engine roadmap

Canonical development plan for reliable, editable solo-instrument and piano
scores. Historical reviews stay in dated `docs/` files. New engine work is
scheduled here.

Reviewed remote baseline for this plan: `8ea76d4` / PR #80 (P1 review
safety: preserve, validate, bind, report-only).

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

**Status.** Verified locally in this increment for the P0 acceptance
criteria (concurrency, voice/layout metrics, identity regressions, readable-v2
suites, MIDI benchmark). Musician review of 138 remains missing; that is a
P1/P2 input, not a P0 gate.

## P1 — Reviewed musical baseline

**User problem.** We cannot say whether a score is musically good. Existing
gates prove preservation, structure, and export plumbing.

**Current implementation and evidence.**

- Inventory + candidate set + review package live under
  `evaluation/musical_baseline/` (`catalog.py`, `package.py`, `reviews.py`,
  CLI `python -m evaluation.musical_baseline`). Written inventory:
  `evaluation/musical_baseline/INVENTORY.md`. Generated package:
  `evaluation/musical_baseline/review_package/`.
- Reviewed remote baseline before this increment: `8ea76d4` / PR #80.
- Candidate set: **15** short synthetic examples (9 development /
  6 held-out). Compositions are disjoint; TUNING_SET members stay
  development-only. Required families covered.
- Review safety + live artifact verification (this increment):
  - Human-owned `review.json` / `REVIEW_FORM.md` are not overwritten on
    `--package` / `--render`. Malformed reviews are preserved.
  - Empty scaffolds may refresh `artifact_binding` to match
    `artifact_fingerprint.json`; human-touched files never do.
  - MusicXML hashes normalize volatile music21 part IDs so unchanged
    rebuilds keep binding current (timestamps alone never invalidate).
  - Validation **recomputes** SHA-256 from live `input.mid`,
    `v1/v2.musicxml`, and `v1/v2.score.mid`. Cached fingerprints inside
    `case_report.json` are never used as evidence. Missing, unreadable,
    malformed, or changed required artifacts prevent `review_complete`.
  - Playback hashes are required binding fields (`null` when a score-MIDI
    file is absent). Playback changes invalidate dependent reviews; older
    reviews that omit these fields remain on disk but need migration /
    re-review before counting as complete.
  - Report-only updates generated reports only; it never rewrites reviews,
    scores, source MIDI, or fingerprints to hide mismatches.
  - Validation/aggregation distinguishes `review_complete` vs
    `musically_accepted` (complete + interpretation `pass`). Stale,
    partial, invalid, mismatched, and `not_applicable` ratings do not
    count as complete.
  - Report-only: `python -m evaluation.musical_baseline --report-reviews`
    validates without rebuilding scores or modifying human files.
- Four dimensions stay separate. Package evidence: acoustic
  `not_applicable` on synthetics; interpretation/correction unreviewed;
  export mechanical. `musician_reviewed_complete=0`.
- NotaTestSamples still undocumented/unreviewed; paired/holdout/real_world
  /smoke audio still missing.

**Modules.** `evaluation/musical_baseline/*`, `evaluation/notation_fixtures.py`,
`evaluation/readable_v2_cases.py`, `evaluation/readable_v2_rollout.py`,
`benchmark/fixtures/catalog.py`, `docs/PRODUCTION_SCORE_QA.md`,
`docs/MUSICAL_INTERPRETATION.md`.

**Dependencies.** P0 metrics so voice scores are not printed-lane noise.

**Implementation tasks.**

1. Inventory available assets in-repo. **Done.**
2. Select 10–15 short examples covering required families. **Done
   (synthetic subset).**
3. Keep compositions disjoint between development and held-out. **Done.**
4. Score four tracks separately; keep unreviewed explicit. **Done.**
5. Safe review collection (preserve, validate, bind, report-only). **Done
   in code; human ratings still missing.**
6. Live artifact verification + playback binding (close the cached-
   fingerprint gap). **Done in code; human ratings still missing.**
7. Collect attributed musician reviews and suitable audio for acoustic
   accuracy. **Remaining — next milestone.**

**Acceptance criteria.**

- Written inventory with provenance and permitted use for every example.
- Missing material listed as missing.
- Development and held-out compositions do not overlap.
- Reviews, if present, are attributed. No invented quality scores.
- Rebuilds must not erase human reviews; completion criteria documented.
- Validation must verify live artifact bytes, not cached fingerprints.

**Status.** Implemented but unverified as a reviewed baseline.
Review-collection machinery is safe, bound to live artifacts, and
reportable (`musician_reviewed_complete=0`, `musically_accepted_count=0`).
**Do not mark P1 complete** without attributed current interpretation and
correction-effort reviews. Do not start P2 heuristics without reviewed
counterexamples. Synthetic coverage does not prove acoustic accuracy or
production readiness.

**Remaining gaps (exact).**

1. Attributed musician reviews for interpretation + correction effort on
   the 15 packaged cases (follow `REVIEW_INSTRUCTIONS.md`).
2. Documented permitted use / license for NotaTestSamples before any
   acoustic claim on those takes.
3. Held-out / real-world / paired-corpus / production-smoke audio still
   missing (self-performed recordings are enough).
4. Acoustic-accuracy labels: missing on every candidate.
5. Optional OSMD `--render` HTML/PNG not required for package completeness.

**Validation evidence (this increment).**

- Focused: `python -m pytest -q tests/test_musical_baseline.py`
  → **25 passed**.
- Supported backend suite:
  `python -m pytest -m 'not integration and not pm2s' -q`
  → **1001 passed, 4 deselected, 3 failed**. The three failures
  (`test_tracks_are_independent`,
  `test_midi_subbeat_tempo_changes_survive_pipeline_and_export`,
  `test_fallback_engine_uses_legacy_on_failure`) reproduce on clean
  `8ea76d4` and are unrelated to this artifact-verification change.
- Tested from branch `cursor/engine-p1-artifact-verify` (base `8ea76d4` /
  PR #80). Record the landing commit SHA when this increment merges.

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

Live artifact verification and playback binding are in place. **Next:**
collect attributed P1 musician reviews via
`evaluation/musical_baseline/review_package/REVIEW_INSTRUCTIONS.md`
(synthetic fixtures must not be used as musician evidence). Only after
real attributed reviews: **P2 musical interpretation improvements** using
reviewed counterexamples. Do not retune heuristics without them.
