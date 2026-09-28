# First musician review session (development only)

Engine default remains `performance-score-1` (v1). `performance-score-2`
(v2) is opt-in for side-by-side comparison. Do **not** invent ratings
or reviewer names. Automated OSMD images are not musician sign-off.
These synthetic cases can assess **notation / interpretation /
correction effort**; they cannot prove acoustic transcription accuracy.

Open `REVIEW_INDEX.html` for thumbnails and file links.

## Cases (4)

### `dev-intentional-rests` — Short notes with intentional rests

- Families: intentional_rests, solo_line
- Meter / tempo: 4/4 @ 120.0
- Folder: `development/dev-intentional-rests/`
- Focus: Listen for intentional silence between short attacks. Check whether rests look deliberate (not fragmented junk) on both staves.

**Steps**

1. Open v1 and v2 renders (`v1_osmd/osmd.png`, `v2_osmd/osmd.png`) or HTML previews.
2. Play `v1.score.mid` then `v2.score.mid` (source: `input.mid`).
3. Use `note_index.json` / `phrases/` and cite `source_note_id` for concrete notes.
4. Edit `review.json` (authoritative):
   - `attribution.reviewer`, `attribution.reviewed_at` (ISO date)
   - copy current hashes from `artifact_fingerprint.json` into `artifact_binding` (include playback SHA fields)
   - `dimensions.musical_interpretation_accuracy.status` (`pass`/`fail`/`needs_work`) and optional `versions.v1` / `versions.v2`
   - `dimensions.human_correction_effort.status` plus notes (minutes / top edits by `source_note_id`)
   - leave `acoustic_accuracy` as `not_applicable` unless real audio+labels exist
5. Optionally mirror notes in `REVIEW_FORM.md`.

### `dev-independent-voices` — Held voice under moving notes (same staff)

- Families: independent_voices
- Meter / tempo: 4/4 @ 120.0
- Folder: `development/dev-independent-voices/`
- Focus: Check whether a sustained voice stays readable under moving notes on the same staff. Compare staff vs musical-voice vs printed lane.

**Steps**

1. Open v1 and v2 renders (`v1_osmd/osmd.png`, `v2_osmd/osmd.png`) or HTML previews.
2. Play `v1.score.mid` then `v2.score.mid` (source: `input.mid`).
3. Use `note_index.json` / `phrases/` and cite `source_note_id` for concrete notes.
4. Edit `review.json` (authoritative):
   - `attribution.reviewer`, `attribution.reviewed_at` (ISO date)
   - copy current hashes from `artifact_fingerprint.json` into `artifact_binding` (include playback SHA fields)
   - `dimensions.musical_interpretation_accuracy.status` (`pass`/`fail`/`needs_work`) and optional `versions.v1` / `versions.v2`
   - `dimensions.human_correction_effort.status` plus notes (minutes / top edits by `source_note_id`)
   - leave `acoustic_accuracy` as `not_applicable` unless real audio+labels exist
5. Optionally mirror notes in `REVIEW_FORM.md`.

### `dev-detached-triplets` — Detached triplet groups (last-note-tune development)

- Families: triplets, detached_articulation
- Meter / tempo: 4/4 @ 120.0
- Folder: `development/dev-detached-triplets/`
- Focus: Confirm triplet grouping is readable and detached attacks stay separate. Compare v1 vs v2 spelling if they differ.

**Steps**

1. Open v1 and v2 renders (`v1_osmd/osmd.png`, `v2_osmd/osmd.png`) or HTML previews.
2. Play `v1.score.mid` then `v2.score.mid` (source: `input.mid`).
3. Use `note_index.json` / `phrases/` and cite `source_note_id` for concrete notes.
4. Edit `review.json` (authoritative):
   - `attribution.reviewer`, `attribution.reviewed_at` (ISO date)
   - copy current hashes from `artifact_fingerprint.json` into `artifact_binding` (include playback SHA fields)
   - `dimensions.musical_interpretation_accuracy.status` (`pass`/`fail`/`needs_work`) and optional `versions.v1` / `versions.v2`
   - `dimensions.human_correction_effort.status` plus notes (minutes / top edits by `source_note_id`)
   - leave `acoustic_accuracy` as `not_applicable` unless real audio+labels exist
5. Optionally mirror notes in `REVIEW_FORM.md`.

### `dev-pickup` — Pickup eighth with rubato tempo map

- Families: pickup
- Meter / tempo: 4/4 @ 120.0
- Folder: `development/dev-pickup/`
- Focus: Confirm the pickup/rubato opening is playable: downbeat location, tempo marks for listening, and whether the first written beat feels right.

**Steps**

1. Open v1 and v2 renders (`v1_osmd/osmd.png`, `v2_osmd/osmd.png`) or HTML previews.
2. Play `v1.score.mid` then `v2.score.mid` (source: `input.mid`).
3. Use `note_index.json` / `phrases/` and cite `source_note_id` for concrete notes.
4. Edit `review.json` (authoritative):
   - `attribution.reviewer`, `attribution.reviewed_at` (ISO date)
   - copy current hashes from `artifact_fingerprint.json` into `artifact_binding` (include playback SHA fields)
   - `dimensions.musical_interpretation_accuracy.status` (`pass`/`fail`/`needs_work`) and optional `versions.v1` / `versions.v2`
   - `dimensions.human_correction_effort.status` plus notes (minutes / top edits by `source_note_id`)
   - leave `acoustic_accuracy` as `not_applicable` unless real audio+labels exist
5. Optionally mirror notes in `REVIEW_FORM.md`.

## After the session

Ask an engineer to run report-only (does not rebuild scores):

```bash
cd audio2score-week4/backend
python -m evaluation.musical_baseline --report-reviews evaluation/musical_baseline/review_package
```

Confirm your cases appear under review_complete / musically_accepted
in `package_report.md` only when bindings match **live** artifacts.

Held-out cases are **out of scope** for this first session.
