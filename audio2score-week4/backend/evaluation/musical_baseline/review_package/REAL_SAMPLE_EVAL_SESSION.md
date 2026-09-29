# Real-sample evaluation session (baseline `1cd1d3f` / PR #94)

**Ready for review.** One unedited NotaScore MusicXML is enough to start a
score/notation review. Corrected exports and correction records are
**optional**. Audio/reference labels are required only for acoustic claims.
Unknown engine metadata stays **unknown** — do not invent provenance or join
unrelated files into one job.

**Not ready.** No confirmed unedited job MusicXML has been imported into
`real_samples/` yet. Ambiguous Downloads / `.tmp` files were **not** assumed
to be the same job. P1 remains 0 attributed reviews. v1 default / v2 opt-in.

## Prerequisites (corrected)

| Evidence | Required to start? | Supports |
|---|---|---|
| Unedited `original.musicxml` | **Yes** | Notation / interpretation review of the automatic score |
| Job ID or link (or honest “unavailable”) | Strongly preferred | Provenance; leave unknown if unavailable |
| `original.score.mid` | Optional | Playback of unedited score |
| Corrected MusicXML / MIDI / `corrections.json` | Optional | Original-vs-corrected effort comparison |
| Source audio | Optional | Audio-versus-score / acoustic claims only |
| Reference labels | Optional | Acoustic accuracy ratings only |
| Engine commit / provider / algorithm | Optional | Record known; else **unknown** |

## Stale synthetic package diagnosis (isolated copy)

Report-only previously showed **stale_count = 15** on the checked-out
`review_package/`. Cause (verified in `/tmp` copies; package not mutated):

| Finding | Detail |
|---|---|
| Root cause | `evaluation/musical_baseline/.gitignore` ignores `*.mid` |
| On-disk MIDI in git checkout | **0** files (`input.mid`, `v1.score.mid`, `v2.score.mid` all absent) |
| Fingerprints / review bindings | Still record non-null MIDI SHA-256 from package build |
| Per-case probe (all 15) | `missing_files`: `input.mid`; `changed_files`: `input.mid`, `v1.score.mid`, `v2.score.mid` |
| MusicXML | Present; **not** listed as changed |
| Human reviews | None attributed — templates only |
| Handoff tarball control | Extract `handoff/p1-review-handoff-e0051f1261ad-20260929T113906Z.tar.gz` → **51** `.mid` files → **0** stale |

This is **missing gitignored MIDI**, not rewritten MusicXML and not silent
rebind of human reviews. Do **not** overwrite the existing package in place
to “fix” hashes. For MIDI-complete review use the handoff archive, or build a
**separately versioned** package from the current engine and leave the old
package + any future human reviews untouched.

## Minimum user handoff (one sample)

Please provide **one** of the following (folder or loose files):

1. **Required:** unedited NotaScore MusicXML export (`original.musicxml` /
   `unedited.musicxml` / job export named with the job id).
2. **Job identity:** job ID and/or link, **or** state that it is unavailable.
3. **Only if you want audio-vs-score:** the source audio file.
4. **Only if already available:** corrected MusicXML (and optional score MIDI /
   `corrections.json`).

**Not required to start:** a completed correction, three samples, or engine
metadata.

### Ambiguous existing files — please identify (do not guess)

| File | Ask |
|---|---|
| Downloads `…Autumn Walks….musicxml` (290 notes, Music21, no job_id) | Is this the **unedited job export**, a **corrected** score, or **something else**? |
| `audio2score-bd53a401c6eb.musicxml` (1-note placeholder) | Ignore for review unless a real unedited export exists for that job |
| Downloads `…Autumn Walks….mid` / `(1).mid` | Which is raw performance MIDI vs score MIDI, if either? |
| `.tmp/autumn-walks-review/production-before.musicxml` vs `current-main.musicxml` | Algorithm/history artifacts — confirm they are **not** human corrections before any compare claim |

## Import (when you supply a usable original)

```bash
cd audio2score-week4/backend
python -m evaluation.musical_baseline \
  --import-real-job /path/to/folder_with_original_musicxml \
  --job-id <JOB_ID_or_UNKNOWN> \
  --package evaluation/musical_baseline/review_package
python -m evaluation.musical_baseline \
  --report-reviews evaluation/musical_baseline/review_package
```

Identical re-import is idempotent; changed evidence needs `--force-import`
(new `example_id-rN`). After import: fill timestamp/measure, expected vs
observed, correction effort; leave attribution/ratings blank until the user
supplies them.

## Claims supported by current evidence

| Claim | Supported? |
|---|---|
| Review an imported unedited real score | **No** — nothing registered yet |
| Original-vs-corrected for Autumn Walks | **No** — roles unconfirmed |
| Audio-vs-score for Autumn Walks | **No** — audio missing |
| Synthetic P1 complete | **No** — 0 attributed; checkout stale without handoff MIDI |
| Musician-validated quality | **No** |
