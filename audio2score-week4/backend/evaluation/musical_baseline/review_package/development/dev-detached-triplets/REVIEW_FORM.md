# Review form — `dev-detached-triplets`

- Title: Detached triplet groups (last-note-tune development)
- Composition ID: `p1-comp-detached-triplets`
- Performance ID: `p1-perf-detached-triplets-synth`
- Split: `development`
- Source: `readable_v2` / `I_detached_triplet_groups`
- Instrument: piano
- Meter / tempo: 4/4 @ 120.0
- Families: triplets, detached_articulation
- Permitted use: `synthetic_repo_fixture`
- Copyrighted: `False`

Identify notes by **source_note_id** in `note_index.json` (not printed lane numbers alone).

Default engine is `performance-score-1`. Opt-in `performance-score-2` artifacts are for comparison only. Export success is not musical quality.

## Attribution

- Reviewer name: _______________________________
- Reviewer role / credentials: _________________
- Review date (ISO): ___________________________
- Contact (optional): __________________________

## Dimensions (score each separately; leave blank if not reviewing)

### acoustic_accuracy

- Status in package: `not_applicable`
- Reason: No suitable audio/reference labels for acoustic accuracy
- Prompt: Only if suitable audio + reference labels exist. Do pitches and performed timings match the recording?
- Rating (pass / fail / needs_work / not_reviewed): ________
- Score (optional 1–5; leave blank if unreviewed): ________
- Notes:

  > 

### musical_interpretation_accuracy

- Status in package: `unreviewed`
- Reason: Musician interpretation rating required; export success is not a substitute
- Prompt: Is the printed interpretation usable (meter, pickup, voices, rests, articulation, duration spelling)?
- Rating (pass / fail / needs_work / not_reviewed): ________
- Score (optional 1–5; leave blank if unreviewed): ________
- Notes:

  > 

### export_integrity

- Status in package: `passed`
- Reason: mechanical MusicXML/MIDI integrity on the shared planner (not acoustic quality; not musician readability)
- Prompt: Mechanical: MusicXML/MIDI readable, identities preserved, no silent fallback. Automated checks may pre-fill this.
- Rating (pass / fail / needs_work / not_reviewed): ________
- Score (optional 1–5; leave blank if unreviewed): ________
- Notes:

  > 

### human_correction_effort

- Status in package: `unreviewed`
- Reason: Musician correction-effort estimate required
- Prompt: About how many minutes / edits to make this teachable or publishable? List the top 1–3 corrections keyed by source_note_id.
- Rating (pass / fail / needs_work / not_reviewed): ________
- Score (optional 1–5; leave blank if unreviewed): ________
- Notes:

  > 

## Staff vs musical voice vs printed lanes

Compare these separately. A printed-lane change after duration fill (e.g. development MIDI 138) is not automatically a musical-voice defect.

- Staff grouping ok? ________
- Musical-voice grouping ok? ________
- Printed lanes ok / expected adjustment? ________

## Contracts reminder

- Preserve original MIDI bytes and source-note identities.
- Preserve performed timing, exact tuplets/ties, accepted corrections, locks.
- Do not retune the engine solely because printed lanes move.
