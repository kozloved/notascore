# Cursor handoff: stable piano hands and simpler note endings

Reviewed main: `fdb15bef4000cea8d807eb002231968dd1d3d2b8` (2026-09-13).
Fetch and fast-forward pull completed; main was already current. This is the next implementation plan, not a claim that these recommendations are implemented.

## What to preserve

- `697e948` keeps measured downbeats through meter/tempo interpretation. Do not restore a cheaper notation meter that contradicts consistent measured bars.
- The current layout path preserves supplied hand/voice assignments through quantization. Keep this separation of responsibilities; improve the upstream layout rather than running another hand separator during export.
- `fdb15be` improves bass → mid-register broken chords under a melody with register anchors and contextual costs. Its new tests pass. Extend the evidence beyond that particular texture rather than adding more pitch thresholds for each song.
- Preserve original note IDs, pitch, multiplicity, velocity, and performed attack/release times. A simpler *written* ending must not rewrite the acoustic performance or original MIDI.

## Review findings

### Hand context does not expire

`backend/mir/hand_separator.py`, `HandReps`, `_transition`, `_update_reps`.

The new bass/melody anchors have no timestamp, phrase boundary, or inactivity decay. Transition costs use pitch jumps without elapsed time. A previous accompaniment pattern can therefore influence a new passage after a long rest just as strongly as the immediately following note. This is a code-confirmed limitation; the correct hand for an unlabelled passage still needs musical reference labels.

The state also does not represent already held notes. Span checks cover simultaneous attacks, not the combination of held keys and a new attack. Distinguish held keys from pedal resonance before using overlap to judge physical reach.

### Dense-chord search can contradict explicit locks internally

`backend/mir/hand_separator.py:164`, `_candidates`.

Above seven simultaneous notes, candidates are only contiguous pitch splits. If explicit hand locks require a crossing/interleaved assignment, filtering can remove every candidate and `return filtered or raw[:1]` selects a lock-violating fallback. `_apply`/`separate` restores locked labels later, but neighboring decisions, carried anchors, and confidence were computed on the wrong assignment.

Reproduced with eight ascending pitches and alternating locked RIGHT/LEFT labels: the sole returned candidate respects none of the required complete assignments. Fix candidate generation and state consistency; do not rely on relabeling after search.

### Layout authority and confidence need explicit meaning

`backend/mir/performance_score.py`, `hands_provided`, `voices_provided`, `assign_pipeline_layout`; `hand_separator.py`, `_viterbi`, `_note_factors`.

All LEFT/RIGHT/AMBIGUOUS labels currently count as a supplied hand layout, while an intentional single voice numbered zero cannot be distinguished from an unassigned voice. This is weaker than an explicit completed layout result. Keep provider hints, inferred layout, and manual locks distinct.

The hand search keeps one carried history for each current assignment even though future costs depend on history-dependent anchors and velocity. Treat it as an approximation, not an exact globally optimal Viterbi solution. Prefix/local competing costs are not calibrated confidence probabilities. The reported factors omit the new accompaniment/texture costs and do not exactly mirror the transition calculation.

### Endings are still fitted mainly to acoustic duration

`backend/mir/performance_score.py:120`, `_duration`, `_written_overlap`; `backend/notation_engine/exact_plan.py`, `_pieces`.

The duration search adds an arbitrary rounded fine-grid duration to its named candidates. Once a simpler value is outside its small tolerance, matching the raw release wins over a simpler written phrase. There is no cost for the *actual resulting* number of ties, tiny rests, or fragments after barline splitting. `_pieces` then faithfully engraves that decision; it is too late to infer a sensible release there.

Direct binary-duration probes at onset zero, with no next attack:

| Performed duration, quarter-note beats | Chosen written duration | Written pieces before bar splitting |
| --- | --- | --- |
| 0.94 | 1 | 1 |
| 1.17 | 19/16 | 1 + 3/16 |
| 2.21 | 35/16 | 2 + 3/16 |
| 3.14 | 25/8 | 3 + 1/8 |
| 5.28 | 21/4 | 4 + 1 + 1/4 |

These are reproductions of the current choice, not instructions to round all such notes to a fixed value. Use surrounding rhythm, articulation, pedal evidence, and the next attack in the same musical line.

### Acoustic tails create extra voices before release simplification

`backend/mir/voice_separator.py`, `_separate_hand`; `backend/mir/performance_score.py`, `_score_voices`, `_stable_lanes`.

Voice allocation uses performed note endings. Pedal/room tails can make notes look independent and overlapping. Once they occupy different voices, `_duration` cannot see the next attack of their intended line. The nominal voice cap is not a strict cap when all existing voices overlap. Do not solve this by force-merging overlapping notes or dropping attacks; infer a separate written line/release hypothesis.

## Evidence from the user's Autumn Walks clip

The real NotaScore polyphonic job `d261e44d-9ba7-46a4-b0e2-329ca643846e` completed successfully through MT3. It produced 100 notes; provider and saved raw-MIDI hashes agreed. The raw SHA-256 is `aae968993fe7aa03dd21d3ba77e2aa8cc143cd585b6d6b0e257f6d2156cf7cca`.

The current-main replay uses that exact provider MIDI and the original 16.9-second audio for local beat detection and notation. It preserves 100 attacks and aligns the detected downbeats to 3/4 bar starts. A short MT3 note before the first detected downbeat is retained as a pickup.

The serialized current score has **155 pitched symbols for 100 attacks**, including **86 symbols participating in ties**, **29 32nd-note symbols**, **one 64th**, **seven 128th**, and **20 symbols with time modifications**. These counts overlap. Some ties and tuplets may be legitimate; inspect their source IDs and phrase context before simplifying. The counts establish a concrete baseline for this user's complaint, not a universal complexity threshold or ground-truth hand annotation.

Keep private audio and MIDI fixtures outside Git. Local review artifacts are under `audio2score-week4/backend/.tmp/autumn-walks-review/`. For a cloud Cursor session, supply the authorized fixture separately or use the synthetic regressions first.

## Phase 1 — Make hand assignment stable across phrases

**Files:** `mir/hand_separator.py`, `mir/voice_separator.py`, layout result/model types, `mir/performance_score.py`, focused tests.

1. Replace implicit “labels exist” detection with an explicit layout result/authority field. Preserve manual locks, provider hints, and completed inferred assignments separately. A valid single voice zero is still a completed layout. Export consumes the result without re-inferring it.
2. Add elapsed-time/beat and inactivity information to each hand's state. Decay anchors across silence and reset them at justified phrase boundaries. Retain bass–harmony–melody continuity within a phrase, allow genuine hand crossing, descending melody below middle C, and wide arpeggios.
3. Generate candidates that always satisfy locks, including dense crossed chords. Keep a small beam of distinct carried contexts or document and measure a simpler approximation. Never repair a contradictory search path only after decoding.
4. Make diagnostics explain the costs actually used, including texture, accompaniment continuity, reach, and anchor age. Report ambiguity as an uncalibrated decision margin until confidence is validated.

**Acceptance:** zero violations of explicit locks; no dropped/reordered source attacks; existing broken-chord tests remain green; test the same phrase at multiple tempi and transpositions, after long silence, with crossed hands, low RH melody, high LH accompaniment, octave melody, dense locked chords, and changes of texture. Use annotated excerpts to measure hand accuracy, inappropriate switches per phrase, and sustained-note reach errors. Do not label the entire corpus by pitch threshold.

## Phase 2 — Infer simple written releases before final voice allocation

**Files:** `mir/performance_score.py`, `mir/voice_separator.py`, notation planning/exact lowering, playback/export tests.

1. Keep performed onset/release and written onset/release as distinct fields. Raw MIDI and canonical playback retain the performed seconds. Written score MIDI may follow the simplified notation; label the two products explicitly.
2. For each candidate musical line, propose release boundaries at the next same-line attack, strong/weak metrical boundaries, plausible articulation gaps, phrase ends, and justified sustained-note boundaries. Allow necessary dotted values and established tuplets. Do not use the next note in the other hand as a cutoff.
3. Score the *whole written ending*: timing fit plus symbol count, unnecessary tie fragments, tiny rests, rhythm-family switches, and consistency with repeated figures. Evaluate the spelling after barline splitting. Penalize isolated 32nd/64th/128th tails without recurring rhythmic evidence; retain genuine fast notes and tuplets.
4. Couple written releases with voice assignment in a bounded pass. Pedal tails alone should not create additional printed voices. Keep genuine independently held notes and overlapping repeated pitches separate. Never impose a hard voice cap by deleting or conflating notes.
5. Make exact lowering deterministic from the accepted written plan. Do not simplify by stripping XML ties, rounding every release, hiding unexplained fragments, or weakening source-attack validation.

**Acceptance:** 0.94/1.94/2.94-beat near-boundary releases stay simple; repeated accompaniment with uneven decay produces stable note values; no tail-only tuplets on synthetic binary phrases; no extra end-of-phrase bar caused only by a tiny release overrun. Preserve intentional staccato, syncopation, dotted rhythm, triplets, rapid repeats, independent unisons, and genuine multi-bar holds. Prove unchanged raw/performance MIDI, one attack per source ID in XML, continuous required ties, and correct bar sums. Validate written durations against the accepted written plan, not against acoustic decay.

## Phase 3 — Review readable scores against a fixed corpus

1. Freeze current baseline hashes and metrics before tuning. Use Autumn Walks as a development example alongside independently annotated piano excerpts; keep a separate holdout set. Include easier and harder textures than waltz accompaniment.
2. Count complexity by cause and source ID: fragments per attack, ties required by bar crossing versus release fitting, tiny terminal fragments/rests, isolated versus patterned tuplets, maximum simultaneous written voices, and hand switches within a labelled phrase.
3. Render before/after MusicXML with the same renderer and layout. Review complete phrases, especially melody sustains, accompaniment endings, crossings, and the final bar. Ask a pianist to judge playability and reading effort without seeing which version is new.
4. Merge the three phases separately. Record code/model/configuration versions, fixture identity, failures, and metric deltas. Predeclare thresholds after baseline collection. A smaller symbol count must not win by losing notes or necessary rhythmic structure.

**Release gate:** all supported tests pass; no regression in downbeat alignment, source identity, raw timing, explicit hands, or valid tuplets; measurable improvement in annotated hand assignment and unneeded tail fragments; reviewed visual examples; no broad claim of perfect hand separation from one song.

## Ready-to-paste Cursor instruction

Start from freshly fetched main containing `fdb15be` and `697e948`; inspect newer commits before editing. Read `docs/CURSOR_HANDS_AND_RHYTHM_2026-09-13.md`. Implement Phase 1 first: explicit layout authority, lock-safe dense-chord candidates, phrase-aware hand context, and honest diagnostics. Preserve the current broken-chord behavior and downbeat alignment. Then implement Phase 2 as a separate change: infer simpler written note endings and voices from musical context while retaining the original performance times and all source attacks. Penalize actual engraved tail fragments and tiny rests rather than globally snapping note-offs. Finally execute Phase 3 with fixed metrics and rendered before/after phrases, including Autumn Walks and a holdout corpus. Do not add another middle-C rule, rerun hand inference during engraving, drop notes to reduce voices, remove necessary ties, or weaken integrity checks. Return commit IDs, regression results, metric deltas, score examples, and remaining uncertain cases.

## Verification

Focused review run on `fdb15be`: **151 passed** across hand separation, performance score/foundation, downbeat alignment, score interpretation, and export/integrity tests. Dense locked-candidate and release-spelling probes reproduced the findings above. The current-main song replay preserved 100 source attacks. Full backend suite: **722 passed, 4 deselected, 20 dependency/audio warnings in 24.98 seconds**, using `python -m pytest -m 'not integration and not pm2s' -q`. The four deselected tests require live integration/PM2S setup; the separate real MT3 song job above did complete. Test-generated benchmark changes were restored to their pre-run contents. `git diff --check` passes. No new heuristic changes are made by this handoff.
