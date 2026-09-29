# Real-sample evaluation session (baseline `39c18ef` / PR #93)

**Status.** No suitable real-job bundle was registered. `real_samples/` remains
empty. P1 stays **0/15** attributed synthetic reviews and **0** real-sample
reviews. v1 default / v2 opt-in unchanged. No ratings invented.

**Report-only** (`--report-reviews` on this package):

| Field | Value |
|---|---|
| Synthetic musician_reviewed_complete | 0 |
| Synthetic stale_count | 15 (pre-existing package drift; not real jobs) |
| `real_samples.count` | 0 |
| `real_samples.stale_count` | 0 |
| `p1_complete` | false |

## Inventory (facts only)

### Documented repo locations

| Location | Audio | Score MusicXML | Corrected | Job ID | Engine | Permitted use |
|---|---|---|---|---|---|---|
| `evaluation/musical_baseline/review_package/` (synthetic 15) | no | v1/v2 fixtures | n/a (algo compare) | n/a | package commit | `synthetic_repo_fixture` |
| `evaluation/development/NotaTestSamples/` Case1–3 | wav present | **missing** | missing | missing | missing | **undocumented** — not treated as real jobs |
| `evaluation/paired_corpus/` | missing | missing | missing | missing | missing | slots empty |
| `evaluation/real_world/`, `benchmark/realworld/local/` | empty / gitignored | missing | missing | missing | missing | n/a |
| `review_package/real_samples/` | — | — | — | — | — | **none registered** |

### Local Downloads / `.tmp` (not imported)

Near-miss candidate labeled **Autumn Walks** (YouTube-style filename in Downloads):

| Artifact | Present? | Notes |
|---|---|---|
| Job-linked MusicXML `audio2score-bd53a401c6eb.musicxml` | yes | job_id `bd53a401c6eb`; **1 note** placeholder titled "Audio2Score Placeholder" — not usable as unedited score |
| Downloads `…Autumn Walks….musicxml` | yes | Music21 export; 290 notes / 9 measures; **no job_id**; role (original vs corrected vs external) **unknown** |
| `…Autumn Walks….mid` (1643 B) | yes | role unknown |
| `…Autumn Walks… (1).mid` (786 B) | yes | **byte-identical** to `.tmp/autumn-walks-review/mt3-original.mid` |
| Audio `.mp3` | **missing** | only Ableton `.mp3.asd` sidecar found |
| PDF exports | yes | not a review binding |
| `.tmp/autumn-walks-review/production-before.musicxml` | yes | algorithm/history compare; **not** documented human correction |
| `.tmp/autumn-walks-review/current-main.musicxml` | yes | algorithm/history compare |
| `corrections.json` / `note_index.json` / editor corrected export | **missing** | |
| Engine commit / provider / algorithm_version | **unknown** | |
| Permitted-use statement | **unknown** | do not infer from filename |

Local `uploads/` / `results/` under the main worktree contain assorted wav/mp3/musicxml
from prior local runs. They are **not** packaged as original-vs-corrected job
bundles with permitted-use documentation and were not imported.

## Selection

**0 of 3 preferred slots filled.** Prefer pickup/tempo/rhythm, independent
voices / sustains, and a user-corrected score — but every candidate lacked
enough evidence for an honest original-vs-corrected claim (audio and/or
unedited job MusicXML and/or corrected export and/or permitted use).

Synthetic fixtures and undocumented NotaTestSamples were **not** selected as
real jobs. Algorithm before/after MusicXML is **not** original-vs-corrected.

## Import

Not run against production. No `--import-real-job` performed (would invent a
false original/corrected pairing).

When a complete bundle exists:

```bash
cd audio2score-week4/backend
python -m evaluation.musical_baseline \
  --import-real-job /path/to/downloaded_job_bundle \
  --job-id <JOB_ID> \
  --package evaluation/musical_baseline/review_package \
  --engine-commit <sha-or-omit> \
  --algorithm-version performance-score-1 \
  --permitted-use "<documented permitted use>"
# Identical re-import: idempotent. Changed evidence: rejected unless
# --force-import → new revision example_id-rN (prior case preserved).
python -m evaluation.musical_baseline \
  --report-reviews evaluation/musical_baseline/review_package
```

## Review sheets (blanks — attribution unfilled)

### Sheet A — Autumn Walks (candidate only; not registered)

| Field | Value |
|---|---|
| Job / sample identity | Possible job_id `bd53a401c6eb` (placeholder export only) |
| Engine evidence | **unknown / missing** |
| Original audio | **missing** (need `.mp3`/`.wav`) |
| Unedited score / playback | Placeholder MusicXML unusable; full MusicXML role **unknown** |
| Corrected output | **missing** (need editor export + optional score MIDI) |
| Timestamp / measure refs | (user fills after listening) |
| Expected result | _(user)_ |
| Observed problem | _(user)_ |
| Edits made | _(user)_ |
| Correction time | actual ___ min / estimated ___ min / unknown |
| Reviewer / reviewed_at | _(leave blank until user supplies)_ |

**Mechanically verified:** placeholder job MusicXML has 1 note; Downloads
MusicXML has 290 notes; one MIDI matches local `mt3-original.mid`.

**Musical judgments:** none recorded.

### Sheet B / C — reserved

No second or third sample met the evidence bar.

## Missing files to provide (only)

For **each** sample (up to three), please supply a folder ready for
`--import-real-job`:

1. `original.musicxml` — unedited job export (required)
2. `original.score.mid` — recommended
3. `corrected.musicxml` (+ `corrected.score.mid`) — if you already corrected it
4. Source audio (`audio.wav` / `.mp3`) — for acoustic comparison
5. Optional: `input.mid` / raw MIDI, `corrections.json`, `note_index.json`, `engine.json`
6. Written **permitted-use** note (and job ID)
7. Optional: brief expected vs observed notes + actual/estimated minutes

Do **not** mark P1/P2 complete until attributed `review.json` entries exist.

## Next fix

**Blocked on evidence.** No attributed real feedback + complete original/corrected
pair → no diverging-stage regression and no heuristic change. Smallest next
step: import one complete downloaded bundle, then fill a review sheet.
