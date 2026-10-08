# NotaScore engine roadmap

Canonical development plan for reliable, editable solo-instrument and piano
scores. Historical reviews stay in dated `docs/` files. New engine work is
scheduled here.

Reviewed remote baseline for this plan: `8b381cb` / PR #88 (same-pitch
continuity duration-compatible bonus). P1 remains **0/15 attributed
reviews** — `musician_reviewed_complete=0`, `p1_complete=false`. Prepared
for review does not mean P1 is complete.

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
- Reviewed remote baseline before this increment: `4ba0659` / PR #81.
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
   accuracy. **Remaining — next milestone.** Package regenerated and
   prepared for review on `2ad36b7`; human ratings still absent.

**Acceptance criteria.**

- Written inventory with provenance and permitted use for every example.
- Missing material listed as missing.
- Development and held-out compositions do not overlap.
- Reviews, if present, are attributed. No invented quality scores.
- Rebuilds must not erase human reviews; completion criteria documented.
- Validation must verify live artifact bytes, not cached fingerprints.

**Status.** Package prepared for musician review — **not P1 complete.**
Fifteen development+held-out cases regenerated against engine `2ad36b7`
with source MIDI, v1/v2 MusicXML, playback MIDI, note indexes, live
fingerprints, OSMD renders, `REVIEW_INDEX.html`, and
`FIRST_SESSION.md`. Report-only validation still shows
`musician_reviewed_complete=0`, `musically_accepted_count=0`,
`stale_count=0`, `p1_complete=false`. Prepared for review ≠ reviewed.
Automated visual inspection is not musician sign-off. Synthetic examples
can assess notation quality but cannot establish acoustic transcription
accuracy. Deterministic P2a correctness fixes may use construction-labeled
pairs while reviews remain 0/15; **do not claim musician-validated
interpretation improvement** and **do not start P2b voice heuristics**
without independent P2a validation plus reviewed or construction-labeled
counterexamples.

**Remaining gaps (exact).**

1. Attributed musician reviews for interpretation + correction effort on
   the 15 packaged cases (start with `FIRST_SESSION.md`; schema in
   `REVIEW_INSTRUCTIONS.md`). Entry point: `REVIEW_INDEX.html`.
2. Documented permitted use / license for NotaTestSamples before any
   acoustic claim on those takes.
3. Held-out / real-world / paired-corpus / production-smoke audio still
   missing (self-performed recordings are enough).
4. Acoustic-accuracy labels: missing on every candidate.
5. Optional OSMD `--render` HTML/PNG not required for package completeness.

**Validation evidence (this increment).**

- Focused: `python -m pytest -q tests/test_musical_baseline.py`
  → **25 passed**.
- Supported backend suite (branch `cursor/engine-p0-timing-fallback`,
  base `4ba0659` / PR #81):
  `python -m pytest -m 'not integration and not pm2s' -q`
  → **1009 passed, 4 deselected, 0 failed**.
- Prior three reproducible failures on clean `4ba0659` are resolved:
  1. **Sub-beat tempo fidelity** — root cause: `MusicalTimeMap.interval_bpms()`
     sampled only integer beat grid, so `playback_tempo` averaged mid-beat
     changes (onset 0.125s exported as 0.150s). Fix: prefer exact tempo
     knots for playback curves; keep printed tempo sparse. Tolerances derived
     from MIDI tick resolution at the slowest tempo.
  2. **Human-review readability** — root cause: `meter_changes` correctly
     has no notation plan (changing meter unsupported), but
     `not_evaluated` omitted `human_rating_required`. Fix: readability
     always requires human rating; never treat missing plan as pass.
  3. **FallbackEngine** — root cause: obsolete test expected legacy
     MusicXML when AMT returns no notes under production performance mode.
     Production correctly refuses silent legacy fallback. Tests now assert
     performance refusal and adaptive-mode fallback separately.
- Remaining limitation: changing meter still rejected by the solo planner
  (`meter_changes` export fails by design). Printed tempo stays sparse;
  playback carries the full curve. Real attributed P1 musician reviews
  remain outstanding.

## P2 — Musical interpretation improvements

**User problem.** Wrong tempo scale, shifted downbeats/pickups, and broken
voice continuity make a score unusable even when export is valid.

**Current implementation and evidence.**

- Performance engine: `mir/performance_score.py`, shared planner
  `notation_engine/plan.py`. Readable-v2 is opt-in
  (`performance-score-2`). Last-note triplet pulse and relative leftover
  fill are tested. Independent holds are not clipped on synthetic cases.
- Editor **Notation version** control (Standard = `performance-score-1`,
  Experimental = `performance-score-2`) regenerates from existing
  performance MIDI via `/jobs/{id}/notation-settings` — no retranscription
  and no extra transcription credit. v2 remains opt-in; the control does
  not make v2 the default.
- 138: musical voice unchanged; printed lanes move after duration fill.
  Not a P2 musical-line bug. Residual duration spelling on that
  development file is unverified musically.
- Tempo-scale search exists (`mir/score_interpretation.py`) but is not a
  reviewed quality claim.

**Modules.** `mir/performance_score.py`, `mir/score_interpretation.py`,
`mir/voice_separator.py`, `mir/meter.py`, `evaluation/readable_v2_cases.py`.

**Dependencies.** P1 examples for anything claimed as musical benefit. P0
metrics before treating 138 as voice work. Deterministic correctness fixes
may proceed with construction-labeled pairs while P1 reviews are still 0/15;
do not claim musician-validated improvement.

**Implementation tasks.**

1. Prioritize tempo scale, downbeat/pickup alignment, and voice continuity.
2. Use paired counterexamples for every heuristic change.
3. Preserve deliberate rests, independent holds, and user-locked decisions.
4. Do not retune readable-v2 from 138 printed-lane movement.
5. Continue P2b only from reproduced musical-identity defects (not lane-only).

**Acceptance criteria.**

- Each change has a labeled pair: intended improvement and a case that
  must not regress.
- User-locked timing, staff, and voice survive.
- No claim of quality without P1 reviews.

**Status.** Partially implemented as deterministic correctness work —
**not P2 complete**, **not musician-validated**. P1 still 0/15 attributed
reviews. Default remains `performance-score-1`; v2 stays opt-in.

**P2a increment (PR #84 @ `e9dca18`).**

- False double-time of already-correct half notes blocked when scale-1
  onsets are on-beat; paired ×1 / ×2 cases retained.

**P2a increment (PR #85 @ `cbaf099`).**

- Tempo-guard unique-pulse ≥85% + min-3; pickup length + `first_downbeat_beat`
  semantics (opening-measure length, not bar-phase) for inferred anacruses.

**P2a increment (this branch, base `cbaf099`).**

1. **Pickup inference false positive (initial rest).**
   - **Defect.** After PR #85, `infer_pickup(0.5, 4.0, downbeat_beats=[0,4,8])`
     ignored the preceding downbeat at 0 and returned
     `pickup_inferred=True, pickup_beats=3.5, first_downbeat_beat=4.0`.
     Construction label: normal bar beginning at beat 0 with an initial
     eighth rest — must not infer a pickup.
   - **Fix.** Require that the first attack precedes every measured
     downbeat (`min(downs) > first_beat + 0.1`). Following-downbeat length
     math retained for the genuine pair attack@3 / downs=[4,8] → length=1,
     first_downbeat=4. Unordered downs, missing evidence, syncopation, and
     mid-bar entry after a barline stay non-inferred. User settings/locks
     remain authoritative.
   - **Paired table (helper).**

     | Case | first | downs | before (PR #85) | after |
     |---|---|---|---|---|
     | Initial eighth rest | 0.5 | 0,4,8 | pickup 3.5 @4 | no pickup |
     | Genuine one-beat pickup | 3.0 | 4,8 | pickup 1 @4 | pickup 1 @4 |

2. **Incomplete-measure engraving (concrete defect).**
   - **Defect.** Length-form genuine pickup exported measure 1 as full 4/4
     padded with leading rests; music21 `makeNotation` and metronome
     inserts using `barDuration` further widened incomplete bars.
   - **Fix.** `build_exact_measures` detects pickup span, rebases MusicXML
     to anacrusis at beat 0 with duration = pickup length; performance
     event beats stay absolute (`pickup_origin_shift` for integrity only).
     Performance MusicXML writes with `makeNotation=False`; metronome
     placement uses written measure duration; planned lengths re-asserted
     after tempo marks.
   - **Assertions.** Genuine length+fdb → first measure ql=1.0; initial
     rest (no pickup) → ql=4.0 with opening rest preserved; legacy
     `pickup_beats=1.0` alone → ql=1.0. Source MIDI bytes unchanged.
   - Sub-beat tempo pickup playback regression remains in the suite.

- **Not claimed.** Musician-validated quality. No v2 promotion.
  Construction-labeled tests ≠ human review. P2b not complete.

**P2a boundary (this branch, base `97a8785` / PR #86).**

1. **Pickup rebase vs printed tempo coordinates.**
   - **Defect.** Notes rebases with `pickup_origin_shift` (perf beat 3 →
     written 0) while `_apply_tempo_map` used `score_beat_offset` alone, so
     mid-pickup / first-downbeat metronomes stayed at absolute 3.5 / 4.0 on
     the written score (wrong measure).
   - **Fix.** Subtract `pickup_origin_shift` when applying tempos to the
     engraved score; apply the same offset to `printed_tempo` beats.
     Playback MIDI still uses absolute quantized events (attack/release
     times unchanged). Auto and velocity-edited regen agree on written
     mark positions. Ties/accidentals on the `makeNotation=False` pickup
     path showed no reproduced defect.
   - **Assertions.** Written marks 90@0.5 and 100@1.0; m1 ql=1.0; MIDI
     seconds match source within tick tolerance.

**P2b increment (PR #87 @ `5351786`).**

1. **Same-pitch continuation after an interrupting same-pitch voice.**
   - Same-pitch leap-0 bonus favoring longer prior duration; monophonic
     repeats counterexample retained.

**P2b increment (PR #88 @ `8b381cb`).**

1. **Short repeating line must not lose notes to a sustained hold.**
   - Duration-compatible same-pitch bonus; paired unit coverage.

**P2b increment (PR #89 @ `e0051f1`).**

1. **E2E fixture evidence repair (no production heuristic change).**
   - **Defect (test evidence).** `_write_same_pitch_midi` wrote overlapping
     same-pitch notes on one MIDI channel. pretty_midi round-trip truncated
     the intended hold `0.0–1.0` to `0.0–0.5`. Regen tests therefore did not
     exercise the documented construction; auto-vs-edited grouping could
     pass while both were wrong.
   - **Fix.** Multi-channel MIDI writers for overlapping unisons; decode
     assertions (count, pitch, attack/release, distinct IDs) before the
     engine; expected musical partitions by `source_note_id` for
     sustained-resume and short-line-continues E2E; staff/hand split
     documented separately for register-separated piano lines.
   - **Decoded fixture (sustained-resume).**

     | note | intended | single-channel decode | multi-channel decode |
     |---|---|---|---|
     | hold | 0.0–1.0 | **0.0–0.5** | 0.0–1.0 |
     | t0 | 0.25–0.5 | 0.25–0.5 | 0.25–0.5 |
     | t1 | 0.75–1.0 | 0.75–1.0 | 0.75–1.0 |
     | s1 | 1.0–1.5 | 1.0–1.5 | 1.0–1.5 |

   - **Claim correction.** Prior roadmap text said two-voice MIDI regen
     preserves ≥2 musical voices; the old test only checked note count and
     unchanged grouping, and register-split piano lines legitimately show
     `musical_voice=0` per hand after staff assignment. ≥2 musical voices
     is now asserted on same-staff multi-channel same-pitch E2E only.
   - **Production.** No VoiceSeparator change — corrected fixtures
     reproduce the intended partitions without a new defect.

**P2b increment (this branch, base `e0051f1`).**

1. **Export artifact verification for corrected voice pairs.**
   - Sustained-resume and short-line E2E now independently decode
     MusicXML (`score_attacks`) and score MIDI (pretty_midi) **before and
     after** a velocity-only edit, comparing both runs to fixture
     expectations (not only auto-vs-edited equality).
   - Asserts: note multiplicity/pitches; attack/release within MIDI tick
     tolerance; hold not shortened by interrupters; distinct repeated
     attacks; MusicXML ties only within a single intended attack span;
     editor partitions; velocity edit touches only the target
     `source_note_id`.
   - **Boundary.** Canonical multi-channel MIDI → planner → MusicXML/MIDI
     serialization → independent decode. No production defect reproduced;
     no VoiceSeparator / exporter change in this increment.
   - **Exported comparison (sustained-resume, seconds @ 120 bpm).**

     | note | fixture | score MIDI auto | score MIDI after vel→105 on hold |
     |---|---|---|---|
     | hold | 0.0–1.0 @80 | 0.0–1.0 @80 | 0.0–1.0 @105 |
     | t0 | 0.25–0.5 @70 | 0.25–0.5 @70 | unchanged |
     | t1 | 0.75–1.0 @70 | 0.75–1.0 @70 | unchanged |
     | s1 | 1.0–1.5 @80 | 1.0–1.5 @80 | unchanged |

     MusicXML attack spans (beats): hold 0–2, t0 0.5–1, t1 1.5–2, s1 2–3;
     no cross-voice ties.

2. **Review handoff refresh (versioned; old archives preserved).**
   - New portable bundle under
     `evaluation/musical_baseline/handoff/p1-review-handoff-e0051f1261ad-*.tar.gz`
     (prior `2ad36b7` archive kept).
   - Regenerated 15-candidate package at tested commit; human
     `review.json` / filled forms preserved (not rebound).
   - `supplemental_p2b/` adds synthetic sustained-resume + short-line
     pairs with matched v1/v2 MusicXML, score MIDI, and OSMD HTML
     previews — **not** part of the P1 candidate set; held-out unchanged.
   - `REAL_SAMPLE_REVIEW_CHECKLIST.md` for live jobs (job ID, engine
     evidence, audio, unedited/corrected outputs, timestamp/measure,
     edits, correction time).
   - OSMD HTML renders present; PNG/SVG not produced in this environment
     (documented limitation — playback MIDI + MusicXML remain).

**P2 increment (this branch, base `71b4c18` / PR #100).**

1. **138 staff/voice DIFF regenerated.** Printed-lane adjustment after
   duration/onset fill; musical grouping and staff unchanged. Not a
   musical-line regression. Development MIDI, not musician-reviewed.
2. **Independent lines vs compact chords.** Production `prefer_simple_chords`
   no longer swallows the first attack of contrary homorhythmic lines.
   Repeating triads and parallel octaves stay one chord.
3. **Overlapping unisons.** Same-pitch cluster members are independent
   voices; attacks preserved. Monophonic repeats stay one voice.
4. **Inner hold under treble melody.** Mixed-duration hand centroids follow
   the moving line, so G4/E4 holds stay on the treble staff. C3 bass under
   the same melody stays left. `G_held_voice_same_staff` is same-staff
   polyphony on the MIDI path.
5. **Humanized chord coincidence.** Readable may align compact same-hand
   members inside 0.08 beats and unify articulation-scale durations.
   Syncopation, fast figures, mixed-release holds, and Autumn Walks bounds
   retained. v2 stays opt-in.
6. **Grace notes.** Interpretation remains editable only. MusicXML grace
   engraving, playback ownership, and reject-on-regen are documented in
   `docs/reviews/VOICE_RHYTHM_REVIEW_2026-10-08.md` — not claimed done.

**Remaining P2 work.**

1. Rubato + sub-beat tempo knots under further scale transforms — keep
   playback fidelity green; no new heuristic without a pair.
2. Musician review of any interpretation claim — blocked on P1 ratings.
3. Auto-infer path still needs measured downs without a preceding barline;
   do not invent pickups from incomplete openings alone.
4. Collect real-sample reviews via checklist + existing `review.json`
   schema; do not invent ratings.
5. Grace-note MusicXML + editor reject contract (see review).

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

Real-job review registration is in this branch (base `678d35b`). Use
`--import-real-job` + `--report-reviews` for already-downloaded bundles;
results stay under `real_samples/` and do **not** change the synthetic
15-case P1 completion count. **P1 is still 0/15 attributed reviews** —
do not mark P1 or P2 complete. Do not invent real jobs or human ratings.
Keep v1 default / v2 opt-in. Pause speculative interpretation/voice
heuristics until real attributed reviews arrive.

**P1 increment (this branch, base `678d35b`).**

1. **Immutable registered real-job originals.**
   - `import_real_job_bundle` stages the full evidence set, then publishes
     only after validation. Identical re-imports are idempotent.
   - Changed originals/artifacts are rejected (`RealImportConflict`);
     human `review.json` never bypasses overwrite protection.
   - `--force-import` publishes a new revision (`example_id-rN`) and
     leaves the prior case + bindings intact (no in-place erase).
   - Omitted optionals on a revision do not leave mixed leftover files;
     failed imports restore the prior package manifest.
   - Evidence model remains **original vs corrected** (not algorithm
     v1/v2). Missing engine/audio/source-note IDs stay `unknown`/`missing`.
   - Demonstrated with clearly labeled temporary test data only — no
     production access, no invented review.

**Validation (this increment, feature `386a247`, merge `249e79e` / PR #92).**

- Focused:
  `pytest tests/test_real_sample_reviews.py tests/test_musical_baseline.py tests/test_voice_continuity_paired.py tests/test_export_evidence_structure.py -q`
  → **68 passed**.
- Supported backend suite:
  `pytest -m 'not integration and not pm2s' -q`
  → **1043 passed, 4 deselected, 0 failed**.

**Exact commands (real sample, local downloaded bundle).**

```bash
cd audio2score-week4/backend
python -m evaluation.musical_baseline \
  --import-real-job /path/to/downloaded_job_bundle \
  --job-id JOB123 \
  --package evaluation/musical_baseline/review_package \
  --engine-commit <sha-or-omit> \
  --algorithm-version performance-score-1
python -m evaluation.musical_baseline \
  --report-reviews evaluation/musical_baseline/review_package
```

**Remaining human inputs.** Minimum to start: **one** unedited NotaScore
MusicXML + job ID/link (or “unavailable”). Corrected/audio optional by
claim. Session: `review_package/REAL_SAMPLE_EVAL_SESSION.md` (baseline
`1cd1d3f`). Synthetic checkout stale cause: gitignored `*.mid` (use handoff
tarball or a separately versioned package — never silent rebind). No
musician-validated quality claim. Real-sample count remains 0 until an
original is imported.

