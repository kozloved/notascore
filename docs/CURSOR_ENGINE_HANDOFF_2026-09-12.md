# Engine review and Cursor handoff

> Historical review of `4536944`. The current review, fixes, and next three phases are in [CURSOR_NEXT_3_PHASES_2026-09-12.md](CURSOR_NEXT_3_PHASES_2026-09-12.md).

Reviewed remote main: `4536944` (2026-09-12), including Cursor PR #60.
Previous fidelity baseline: `b42d606`. Review checkout: `/tmp/notascore-review-4536944`.
This is a review and implementation plan, not a claim that the fixes below are implemented.

## Git and overwrite audit

- PR #60, "Shared job notes, production quantizer, and reviewable federation", merged at 2026-09-12 15:02:22 UTC: https://github.com/kozloved/notascore/pull/60
- Remote main contains `b42d606` as an ancestor. The merged tree equals `cursor/immutable-job-time-map-f48d` at `75139cd`.
- Main gained six commits, including the integration merge. Local main was clean at `b42d606`, six commits behind after fetch. This review did not pull, merge, push, or alter application code.
- `notation_engine/integrity.py`, `notation_engine/playback.py`, and `notation_engine/exact_plan.py` are byte-for-byte unchanged from `b42d606`. Their source-attack protections were not overwritten.
- PR #48 remains open: https://github.com/kozloved/notascore/pull/48 . Its branch has one commit absent from main (`5b89fa4`); `git cherry` does NOT establish patch equivalence. It is an old overlapping proposal, not a new dependency. Review its intended behavior against current tests before closing it; do not blindly merge or replace current files with that branch.
- Git ancestry rules out replacement of the reviewed baseline in current history, not every possible semantic regression or an unobserved earlier force-push. Runtime concurrency needs separate protection.

## Findings

Paths and line numbers below refer to backend files under `audio2score-week4/backend` at `4536944`, NOT the older local main checkout.

### P1: Editor revision checking does not prevent concurrent overwrites

`main.py:994-1018`, `main.py:240-258`, `database.py:233-255`.

Two requests read the same revision, both pass the check, then write the same JSON/XML/MIDI filenames before an unconditional database update. Both report the same next revision. Interleaved storage writes can produce a bundle whose JSON, score, and MIDI describe different edits. Reset also deletes the shared files without conditional revision ownership (`main.py:1024`).

Reproduced with two synchronized calls to the real `score_edits_put`, mocking DB/storage/build boundaries: both accepted revision 0; two writes; updates `[1, 1]`. This is a handler-level reproduction, not a deployed load test.

### P1: Duplicate job attempts can overwrite each other's artifacts and status

`tasks.py:17-26`, `tasks.py:48-108`.

Processing has no atomic claim or attempt fencing. It writes keys based only on job ID and updates completion/failure without checking ownership. Duplicate execution of the same job can overwrite the first attempt's results; a late failure can replace a newer successful status. Multi-file publication is not transactional.

This is a code-confirmed unsafe path; duplicate delivery in the deployed queue was not observed during this review. Different job IDs normally have separate paths. `transcription.py:368` constructs fresh engines, so there is no evidence here of a shared pipeline singleton contaminating unrelated jobs.

### P1: Initial editor loading loses the full performance tempo map

`main.py:275-279`, `score_edits.py:191-202`, `mir/pipeline.py:537-540`.

The pipeline deliberately separates full playback tempo from sparse printed tempo. Initial editor state is reconstructed only from MusicXML markings. The new `tempo_curve` field preserves a curve supplied to it, but does not load the original full playback curve. Saving even a pitch-only edit can therefore change rubato in the edited MIDI. Current tests supply a curve explicitly or use constant-tempo XML, which does not exercise this boundary.

### P2: Editor source IDs and voices do not survive XML round-trip

`score_edits.py:213-229`, `score_edits.py:318-323`.

Extraction invents `n-####` source IDs instead of restoring actual provenance. Rebuilding inserts notes directly into the staff and does not use their requested voice for engraving. An exported note with `source_note_id=original-a` and `voice=3` reimports as `source_note_id=n-0000`, `voice=0`. Existing saved JSON can retain the submitted fields, but the exported/reimported score cannot. This undermines comparison, voice-sensitive editing, and tracking genuine repeated notes across exports.

Do not simply restore whole-part Voice wrappers: PR #60 includes a fix for an attack-loss problem involving those wrappers. Use stable per-measure voice lanes and verify exported attacks.

### P2: The immutable job abstraction is not yet authoritative or immutable

`mir/job.py:16-37`, `mir/pipeline.py:640`, `mir/pipeline.py:934-966`.

`ImmutableNoteSet` freezes a tuple containing mutable `NoteEvent` objects. Direct assignment to `notes.notes[0].pitch` succeeds (reproduced: changed to 99). Its copy-in/copy-out methods do prevent ordinary external-list aliasing, which is useful but weaker than immutability.

`PipelineJob` is assembled after export by reading mutable `last_result` and other `last_*` fields. It is a post-hoc bundle, not the shared input contract its documentation describes. Reusing one engine concurrently would be unsafe; current factory-per-job behavior reduces that exposure. Do not advertise instance reentrancy or cache these engines without further work.

## Architecture judgment

Keep the core approach: original attacks in seconds, an explicit seconds-to-beats map, conservative performance quantization, separate engraving and playback, and tie-aware export validation. Replacing it wholesale would discard useful safeguards.

The avoidable complexity is duplicated authority: pipeline fields, stage `last_result` fields, and a job object populated after the fact. Converge these on explicit returned stage results, rather than adding another orchestration framework.

The performance mode is the default, but is not an unconditional production boundary: `notation_engine/plan.py:149` calls `quantize_result`, whose dispatch at `mir/quantizer.py:200` selects experimental modes from configuration. Make the product boundary explicit before claiming experiments are comparison-only.

Source-count integrity proves that notation did not invent attacks relative to its input. It does not prove that audio transcription or federation produced the right attacks. Keep full-mix baseline provenance and report additions separately; never treat score export success as transcription accuracy.

## Next phases

### Phase 0: Establish a safe integration baseline

Owner: one integration agent. Start from a freshly fetched main, verify it still contains `4536944`, and inspect any newer commits before applying this plan. In a clean checkout, fast-forward only. Use separate worktrees and `codex/` or Cursor branches for independent agents; never have two agents edit one working directory. No force-push, reset, or automatic merge of stale PR #48.

Preserve the current integrity/playback/exact-plan tests. Record commit SHA with all test results. Merge phases serially or assign the overlapping API files to one owner.

### Phase 1: Make publishing safe across instances

Scope: `database.py`, `tasks.py`, `storage.py`, editor save/reset handlers in `main.py`, queue/retry integration, focused API/worker tests.

Implement atomic job claiming with attempt IDs and fencing on every final update. Write results to immutable attempt-specific paths and publish one manifest/pointer only after all artifacts validate. An expired attempt must not publish, change status, or delete a newer attempt's files.

For edits, stage a unique complete artifact bundle first, then atomically compare-and-swap the database pointer using the expected revision. A losing writer returns 409 and cannot overwrite the winner's files. Make reset a conditional pointer update; garbage collection must only remove unreachable bundles.

Acceptance: synchronized competing saves produce exactly one success and one 409; winning JSON/XML/MIDI are coherent; save-versus-reset is deterministic; duplicate worker attempts cannot publish twice; late failure cannot replace success; unrelated job IDs remain isolated; interrupted upload leaves the old committed bundle readable. Test against the real DB update implementation as well as mocks.

### Phase 2: Make pitch-only edits musically lossless

Scope: canonical editable performance sidecar/schema, initial editor loading in `main.py`, `score_edits.py`, frontend editor model/playback, round-trip tests. Coordinate `main.py` ownership with Phase 1.

Initialize editor data from the canonical performance notes and full time map, not printed XML. Preserve source IDs, multiplicity, voice/staff, velocity, exact beat positions, and tempo map. Keep presentation tempo marks separate. Define migration for old jobs without sidecars, with explicit degraded provenance rather than fabricated source identity. Consider tempo curves longer than the current 512-point limit.

Acceptance: a pitch-only edit changes only that pitch; all attack/release times in seconds remain within documented MIDI tick tolerance through import, API save, download and reimport. Include rubato with sparse printed marks, changes inside beats, pickups/offbeats, fast repeated pitches, ties across bars, overlapping same-pitch voices, triplets, long curves, and voices that end early. Assert original source identity and voice, not merely nonempty IDs or unchanged input dictionaries.

### Phase 3: Finish stage ownership and reduce complexity

Scope: `mir/job.py`, `mir/pipeline.py`, quantizer/planner/writer interfaces and their orchestration callers.

Use genuinely immutable input records, create job context before processing, and return explicit stage results. Keep `last_*` only as read-only compatibility diagnostics derived from the returned result, never read them to coordinate stages. Keep factories per job unless reentrancy is intentionally implemented and tested. Route public production calls explicitly to the performance quantizer; make experimental comparison an explicit separate entry point.

Acceptance: mutations of stored notes/time-map data cannot change another stage's inputs; mutation of returned diagnostics cannot change exports; interleaved independent jobs have distinct provenance/results; experimental environment settings cannot silently change the production path; no added or missing attacks across the corpus.

### Release gate after each phase

Run focused tests first, then the full supported suite. Use an auditable MIDI corpus and licensed, human-reviewed audio fixtures; report source attacks versus inferred additions separately. Check optional component readiness with actual model inference before enabling a component in production. Do not enable all optional processors merely because they import. Review score readability visually as well as attack/timing equality; retain rubato when confidence in a grid is low.

## Verification performed

Using the existing local backend virtualenv against the isolated remote-main checkout:

```sh
python -m pytest tests/test_job_context.py tests/test_tempo_map.py tests/test_export_integrity.py tests/test_notation_integrity.py tests/test_score_edits.py tests/test_quantizer_identity.py -q
# 97 passed
python -m pytest tests/test_performance_foundation.py tests/test_performance_score.py tests/test_midi_ingest.py tests/test_human_review.py tests/test_engine_orchestrator.py tests/test_transcription_reconcile.py -q
# 62 passed
```

Total: 159 passing tests. Module path was verified to resolve to the review worktree. Additional mutation, identity/voice, and concurrent-save probes reproduced the findings above. No full-suite, deployed multi-worker, frontend/browser, or live model validation was performed in this review. No blanket guarantee of zero invented transcription notes follows from these tests.

## Ready-to-paste Cursor prompt

Review `docs/CURSOR_ENGINE_HANDOFF_2026-09-12.md` against freshly fetched main. The reviewed baseline is `4536944`, which contains `b42d606`. Preserve the existing source-attack integrity guards and exact playback export. Implement Phase 1 first in an isolated branch/worktree, with race reproductions that fail before the fix and pass afterward. Use immutable artifact bundles plus database compare-and-swap/attempt fencing, not process-local locks. Do not modify quantization or merge old PR #48 in this phase. Report the commit reviewed, files changed, acceptance-test results, and remaining risks. Then proceed to Phase 2 and Phase 3 as separate reviewable changes, coordinating ownership of shared files.
