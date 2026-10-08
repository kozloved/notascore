# Voice continuity and written-rhythm review

Reviewed main at `71b4c18` (PR #100, canonical rests + independent playback
tempo). This increment stays on the shared production path
(`assign_pipeline_layout` → `quantize_notation` → `build_exact_measures` →
writer/playback/regen). User-facing modes are Literal and Readable. New
scores default to Readable (`performance-score-2`). Saved jobs keep stored
`algorithm_version` until explicit regenerate.

Development MIDI is labeled as such. P1 musician reviews remain 0/15.

## 138_с_chords_piano (regenerated)

Input: `evaluation/development/NotaTestSamples/Case2/138_с_chords_piano_raw.mid`
(undocumented development MIDI, not musician-validated).

Current engine (this increment, user-facing Readable):

- Staff equal v1/v2; musical grouping equal; source MIDI bytes unchanged.
- Kind: printed-lane adjustment (or unchanged), **not** a musical-line regrouping.
- Texture: four successive compact mid-register chords (C–Eb–G, then Ab–C–Eb–F,
  etc.), all inferred right-hand. Musical voice is one chord stream.
- Printed-lane movement after duration/onset fill is occupancy of mixed
  written lengths, not a staff or identity change.

Old rollout `DIFF` on “staff or voice grouping” was the printed-lane metric.
It is not a genuine musical regression on current main.

## Implemented

### 1. Independent lines vs compact chords

`_score_voices` used `prefer_simple_chords=True`, so the first attack of two
contrary homorhythmic lines (octave-ish) was absorbed as a chord; later notes
then forked a second voice. Lookahead now splits when continuations move
independently. Compact repeating C–E–G and parallel octave doubling stay one
chord.

Pair: contrary C4/C5-register lines vs repeating C–E–G vs parallel octaves.

Same-hand locked events (production `_score_voices`) split contrary motion
into two musical voices. Unlabeled MIDI of the same pitches may staff-split
via HandSeparator instead; that is a hand/staff identity, not a chord. Parallel
tenths stay one chord on one staff. Do not compare those outcomes by numeric
voice labels alone.

### 2. Overlapping unisons keep attacks and identity

Same-pitch members of an onset cluster are no longer one chord. Independent
overlapping G4s get distinct musical voices and printed lanes. Monophonic
repeats stay one voice.

Pair: overlapping unisons vs repeated single-line pitches.

### 3. Inner hold under a treble melody stays on the treble staff

Hand-separator centroids averaged a long inner hold with the moving melody,
so the next melody attack looked like a jump and G4/E4 holds were parked
left. Mixed-duration frames now follow the moving notes. A real bass (C3)
under the same melody remains left. `G_held_voice_same_staff` is now
same-staff polyphony through MIDI ingest, not a staff split.

Pair: G4 hold + treble quarters vs C3 bass + treble quarters.

### 4. Humanized chord coincidence vs deliberate syncopation

Readable may align compact same-hand chord members inside an 0.08-beat window
and unify written durations when the spread is articulation, not mixed
release. Fast figures, isolated 32nd syncopation, locked timing, tuplets, and
cross-line Autumn Walks bounds are unchanged. Decisions expose
`readable_chord_coincidence` and `readable_chord_duration`.

Pair: staggered C–E–G vs off-beat 1.125 vs mixed-release inner hold vs rapid
RH against bass.

### 5. PR #100 rest and tempo contracts

Meter-aware rests, visible primary measure rests, hidden secondary fillers,
byte-identical source MIDI, and independent printed vs playback tempo are
untouched.

## Counterexamples retained

- Intentional short notes + rests (case B, short_rests_repeats)
- Detached quarters fill on current Readable; saved `performance-score-1` jobs keep the rest until regenerate
- Consecutive 16th run 60/64/67 at 0, 1/16, 1/8 is not a staggered chord
- Syncopation, mixed tuplets, pickups, user-locked hand/voice/timing
- Broken-chord left-hand waltz under melody
- Bass above middle C stays left; melody below middle C stays right

## Remaining grace-note work (not in this increment)

Readable already labels short anticipations (`ornament_style=acciaccatura`,
`editable=true`, `primary_note_id`, positive performed duration). MusicXML
grace engraving is still missing. A complete contract needs all of:

1. **Plan.** `PlannedNote` grace metadata (style, slash, steal-from-next)
   separate from performed `duration_q`. Grace must not consume measure
   time; the principal keeps the beat. Source `event_ids` stay on the grace
   note.
2. **Writer.** MusicXML `<grace slash="yes"/>` (acciaccatura) with the source
   XML id. Do not convert the source event to zero duration to get a small
   head.
3. **Playback.** Keep using performance events (`notation_engine/playback.py`),
   never the engraved grace duration. Attacks and coverage must remain.
4. **Editor / regen.** Persist accept/reject. Clearing `articulation` today
   does not stop `_readable_mark_ornaments` from re-tagging on regenerate.
   Need an explicit ornament decision lock, including user-locked timing.
5. **Pairs.** Short anticipation → grace; ordinary sixteenth; bass attack;
   tuplet member; re-ingested long written hold (already not ornamented).
6. **Visual.** OSMD/PDF of accepted vs rejected grace, including collisions
   with accidentals and tuplets.

Until that lands, ornaments stay decision + `articulation="ornament"` only.

## What this is not

- Not musician-validated quality. New scores default to Readable
  (`performance-score-2`); existing jobs are not auto-migrated.
- Reattack / pedal-tail writes to the next accepted attack. Independent
  overlapping unisons and long same-pitch holds stay `overlapping_repeat`.
- Literal vs Readable OSMD/PDF of the same MIDI is the visual evidence for
  this increment, not fewer symbols alone.
- 138 remains unlabeled development MIDI. Chord-coincidence spelling on that
  file is a printed-lane / duration change, not musician-validated quality.
- Filename-specific heuristics were not added.
- Parallel replacement pipelines were not added.
- Unlabeled MIDI contrary octaves may still become a two-staff layout; the
  VoiceSeparator fix is the same-hand path. OSMD stacks a treble whole-note
  inner hold under the first melody attack, so the PNG can look like a short
  chord even when MusicXML is a whole note plus moving eighths.
