# Real-sample review checklist

Use this for **already-downloaded live job** evidence. Reuses the existing
evaluation package / `review.json` structures — no new review app.

Real cases live under `real_samples/` and are tracked **separately** from
the fixed 15-case synthetic P1 completion count. Corrected exports are
**not** algorithm v2; comparison is original vs corrected.

Keep synthetic package cases labeled `synthetic_repo_fixture`. Do not bind
older human reviews to rebuilt artifact hashes without re-review. Do not
access production accounts from this workflow.

## Per sample

| Field | Value |
|---|---|
| Job ID | |
| Engine commit / provider / algorithm evidence | known / unknown / missing |
| Original audio + permitted use | present / missing / unknown |
| Unedited MusicXML + score MIDI | required originals |
| Corrected MusicXML + score MIDI | optional |
| Source-note IDs | present / missing |
| Timestamp / measure citations | |
| Edits (`corrections.json`) | |
| Correction time (minutes) + kind | actual / estimated / unknown |
| Reviewer + `reviewed_at` (ISO) | |

## Import a downloaded job bundle

Place files in a folder (aliases accepted):

- `original.musicxml` (required; also `unedited.musicxml`)
- `original.score.mid` (optional but recommended)
- `corrected.musicxml` / `corrected.score.mid` (optional)
- `input.mid` / `raw.mid` (optional)
- `audio.wav` (optional)
- `corrections.json`, `note_index.json`, `engine.json` (optional)

```bash
cd audio2score-week4/backend
python -m evaluation.musical_baseline   --import-real-job /path/to/downloaded_job_bundle   --job-id JOB123   --package evaluation/musical_baseline/review_package   --engine-commit <sha-or-omit>   --algorithm-version performance-score-1   --permitted-use "document-permitted-use-or-omit"
```

This registers `real_samples/<example_id>/`, hashes supplied artifacts, and
writes an empty `review.json` scaffold (human-owned files are preserved).

## Record a review

1. Open `real_samples/<example_id>/`.
2. Play/compare `original.*` vs `corrected.*` (not v1 vs v2 algorithms).
3. Copy hashes from `artifact_fingerprint.json` into `review.json` →
   `artifact_binding`.
4. Fill attribution, interpretation, correction effort; set
   `correction_time.kind` to `actual`, `estimated`, or `unknown`.
5. Cite measures/timestamps in `citations`.
6. Acoustic accuracy only when audio **and** reference labels exist;
   otherwise `not_applicable`.

## Validate (report-only)

```bash
python -m evaluation.musical_baseline   --report-reviews evaluation/musical_baseline/review_package
```

Report-only discovers registered real cases, verifies live file hashes,
marks stale reviews when artifacts change, and lists real-sample results
under `real_samples` in `package_report.json` / `.md` — **without** changing
the synthetic P1 completion count.

## Limits

- Synthetic fixtures do not prove acoustic accuracy or P1 completion.
- Successful export or a corrected score alone is insufficient.
- P1 remains incomplete until attributed reviews exist.
- Default remains v1; v2 stays opt-in.
