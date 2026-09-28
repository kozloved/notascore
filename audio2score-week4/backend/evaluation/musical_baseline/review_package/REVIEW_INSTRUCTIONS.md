# P1 musical baseline — review instructions

## Purpose

Assess short examples on **four independent dimensions**. Do not collapse them
into one pass/fail. Export success is not musical quality. Synthetic fixtures
do not prove acoustic accuracy or production readiness.

## Dimensions (keep separate)

1. **Acoustic accuracy** — only when suitable audio and reference labels exist.
   Most synthetic package cases are `not_applicable` and never count toward
   P1 completion.
2. **Musical interpretation accuracy** — meter, pickup, voices, rests,
   articulation, duration spelling. Required for review completion.
3. **Export integrity** — mechanical MusicXML/MIDI identity (package fills
   automated checks). Optional human overlay.
4. **Human correction effort** — minutes/edits to make the score usable.
   Required for review completion.

Valid statuses: `pass` | `fail` | `needs_work` | `not_reviewed` | `not_applicable`.
Optional per-version ratings: `dimensions.<name>.versions.v1` / `.v2`.

## Completion vs acceptance

Documented in code as `COMPLETION_CRITERIA` (`evaluation/musical_baseline/reviews.py`):

- **review_complete** requires: valid `review.json`, matching case identity,
  attribution (`reviewer` + ISO `reviewed_at`), **current** `artifact_binding`
  matching `artifact_fingerprint.json`, and both interpretation + correction
  effort rated `pass`/`fail`/`needs_work`.
- `not_reviewed` / `not_applicable` / missing ratings do **not** count.
- Stale bindings (artifact hashes changed) retain feedback on disk but are
  **excluded** from completion counts until re-reviewed against new hashes.
- **musically_accepted** = review_complete AND interpretation `pass`.
  A complete review may still fail musically.

## Exact musician workflow (first real review)

1. Ensure the package exists (engineer may run `--package` once):
   `python -m evaluation.musical_baseline --package evaluation/musical_baseline/review_package`
2. Open one case, e.g. `development/dev-solo-detached/`.
3. Play `v1.score.mid` / `v2.score.mid`; open `v1.musicxml` / `v2.musicxml`.
4. Use `note_index.json` and `phrases/`; cite `source_note_id`.
5. Copy binding hashes from `artifact_fingerprint.json` into `review.json`
   → `artifact_binding` (template already includes them when first created;
   if you started from an older file, refresh these fields from the fingerprint).
6. Fill `review.json` (authoritative):
   - `attribution.reviewer`, `attribution.reviewed_at` (ISO date)
   - `dimensions.musical_interpretation_accuracy.status`
   - `dimensions.human_correction_effort.status`
   - optional acoustic / export / notes / per-version ratings
7. Optionally annotate `REVIEW_FORM.md` (human-owned; rebuilds preserve it).
8. Ask an engineer (or yourself) to run **report-only** (does not rebuild scores
   or touch your review files):
   `python -m evaluation.musical_baseline --report-reviews evaluation/musical_baseline/review_package`
9. Confirm your case appears under `review_complete` / `musically_accepted` in
   `package_report.md` as appropriate.

## Rebuild safety

- `python -m evaluation.musical_baseline --package …` and `--render` regenerate
  scores and `artifact_fingerprint.json` but **never overwrite** existing
  `review.json` or filled `REVIEW_FORM.md` (including malformed files).
- Fresh blank templates are written only when those files are absent.
- `REVIEW_FORM.template.md` is always refreshed as a generated reference.

## Contracts

- Default remains `performance-score-1`; `performance-score-2` is opt-in.
- Preserve original MIDI bytes, source identities, performed timing, tuplets,
  ties, accepted corrections, and user locks.
- Compare staff, musical-voice grouping, and printed lanes separately.
- Do not retune the engine merely because case 138 printed lanes move.
