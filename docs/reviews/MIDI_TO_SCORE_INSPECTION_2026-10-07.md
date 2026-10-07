# MIDI-to-score inspection and balanced interpretation

Baseline inspected: `6763e0a` (PR #98). User-selected policy: **Balanced** — simplify performance noise while preserving pitches, intentional rhythm, repeated attacks, and independent voices. This branch combines the PR #99 musical-context fixes and the existing `codex/canonical-rest-engraving` work with additional fixes below. It does not merge or deploy them.

## Architecture and findings

| Stage | Existing implementation | Inspection result |
| --- | --- | --- |
| Source capture | `mir/midi_ingest.py`, `mir/performance.py` | Immutable snapshot, track-aware note pairing, tempo and source identity provide a sound foundation. Overlapping same-pitch FIFO pairing remains an interpretation policy, not proof of intent. |
| Musical time | `timing/tempo_map.py`, `mir/score_interpretation.py` | Tempo-scale and meter hypotheses exist; changing meter remains explicitly unsupported by the solo planner. Avoid choosing meter merely to reduce printed symbols. |
| Hands and voices | layout authority, hand/voice separators | Preserve supplied layout and user locks. Independent voice continuity needs reviewed real piano examples before broader heuristic retuning. |
| Rhythm interpretation | `mir/performance_score.py` | Reproduced unconditional simplification of exact short offbeats. Exact per-voice candidates are now retained; supported cross-line cleanup remains possible. Chords, repeats, and ornament ownership include the PR #99 safeguards. |
| Exact engraving | `notation_engine/exact_plan.py` | Reproduced ordinary binary duration 11/8 becoming 4/3 + 1/24, inventing tuplets. Binary spans now use binary spelling. Integrated meter-aware rests, visible empty bars, and tuplet-rest annotation. |
| Playback export | writer and MIDI conversion CLI | CLI bypassed unsplit-event playback and lost tempo changes after sparse-printing changes. It now uses the shared export path and persists the full tempo curve in interpretation context. Pickup export bounds now follow playback events rather than shorter rebased engraving. |
| Printed output | writer, PDF assembly | Sparse printed tempo is separate from playback. Secondary-renderer inspection completed for the targeted spelling/rest example; OSMD and production PDF remain unverified here. |
| Quality evidence | tests and musical-baseline package | Automated correctness is extensive; attributed musical acceptance is still a separate missing gate. Do not label the engine perfect or publisher-quality. |

## Verified improvements

- A 11/8-quarter-note binary sustain becomes a quarter tied to a dotted sixteenth, rather than a spurious triplet half plus tiny tuplet remainder.
- Ordinary silent spans expose the meter; empty primary bars show measure rests; secondary structural fillers stay hidden.
- Exact short offbeats survive per-voice search. A paired delayed melody/bass example still aligns when cross-line evidence supports it.
- CLI score playback retains sub-beat tempo changes even when printed tempo is off; source bytes, instrument, pitch, velocity, held-note continuity, and repeated attacks are tested.
- Pickup playback retains tempo events beyond the shorter rebased printed score boundary.
- The CLI protects its interpretation-context path from colliding with its source and records the playback curve for later regeneration.

## Rendered comparison

Construction-labeled example: C5 at beat 0 for 11/8 beats, D5 at beat 2 for half a beat, 4/4. Compare [before](midi_score_2026-10-07/before.svg) and [after](midi_score_2026-10-07/after.svg), with corresponding MusicXML. Inspection confirms removal of the invented triplet and restoration of the empty bass measure rest. Verovio's local tempo glyph rendering has a missing glyph, and it reports a tie-ID warning; this is not a production PDF visual acceptance result.

## Development sequence toward intentional, simple notation

1. **Finish this correctness increment:** run the complete available backend suite, retain regression pairs, review and merge the consolidated change.
2. **Grace-note contract:** distinguish accepted ornaments from candidates. Store source ID, target note, written grace type, and original performance duration independently. Do not zero source duration to get small noteheads. Require an editable choice and negative cases for short chord tones, repeated notes, and independent voices.
3. **Phrase-level alternatives:** score complete rhythmic interpretations against timing error, beat clarity, ties, rests, and voice continuity. Keep raw performance immutable; expose uncertainty and retain an alternative when evidence is close. Repetition should support consistent spelling, not override user locks or clear intentional variation.
4. **Tonal spelling:** audit key-hint propagation (the CLI currently does not forward the ingested key hint; ingest's hint also drops the minor-mode word), enharmonic spelling, and key changes with paired major/minor and chromatic examples before implementing tonal heuristics.
5. **Meter and pickup:** add changing-meter support as an explicit planner extension, then test 3/4 vs 6/8, 9/8, mixed meter, and pickups with tempo changes. Do not silently force unsupported files into 4/4.
6. **Independent piano voices:** use reference excerpts with held inner voices, crossings, repeated unisons, and pedal tails. Evaluate musical voice identity separately from printed lane count.
7. **Real visual acceptance:** render the same source through Literal and Balanced modes in OSMD/A4 PDF. Review readability, correct musical intent, and correction effort alongside decoded MIDI fidelity. Start with 3–5 user-selected excerpts plus the existing synthetic review corpus; keep evaluation material separate from heuristic tuning.

## Final validation

`python -m pytest -m 'not integration and not pm2s' -k 'not test_prepare_fixture_and_end_to_end_evaluation and not test_stage_capture_does_not_reinvoke_basic_pitch and not test_prepare_smoke_and_run_observational_eval' -q`

**1087 passed, 1 skipped, 7 deselected.** Four deselections are live integration/model markers; three are audio evaluation tests whose diagnostic artifacts explicitly report missing `basic_pitch`. The first broad run exposed the outdated dense-printed-tempo expectation; that test now checks the intended sparse page and still verifies decoded playback timing and automatic/edited agreement. The final run includes the previously dependency-blocked app/export checks.

Nine new binary-spelling cases include exhaustive combinations of binary offsets and durations under both syncopation policies and three dot limits. CLI additions decode tempo-changing playback and held/repeated notes. No failures remain in the available suite.

## Limits

This work improves deterministic MIDI interpretation and engraving. It cannot recover a composer's unique intention from arbitrary MIDI, establish audio transcription accuracy without audio references, or replace musician review. Experimental v2 remains opt-in. No production deployment or model inference was performed.
