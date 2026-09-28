# P1 reviewed musical baseline

Inventory, candidate set, and review-package builder for the engine roadmap
milestone **P1 — Reviewed musical baseline**.

This package does **not** invent licenses, musician reviews, or quality scores.
Synthetic fixtures are eligible for packaging; acoustic accuracy stays
`not_applicable` without suitable audio/labels. P1 is not complete until
attributed reviews exist.

## Commands

```bash
cd audio2score-week4/backend
python -m evaluation.musical_baseline --inventory
python -m evaluation.musical_baseline --inventory-md evaluation/musical_baseline/INVENTORY.md
python -m evaluation.musical_baseline --package evaluation/musical_baseline/review_package
python -m evaluation.musical_baseline --package evaluation/musical_baseline/review_package --render
python -m evaluation.musical_baseline --report-reviews evaluation/musical_baseline/review_package
python -m pytest -q tests/test_musical_baseline.py
```

`--package` / `--render` regenerate scores and fingerprints but never erase
human-owned `review.json` / filled `REVIEW_FORM.md`. `--report-reviews`
validates and summarizes without rebuilding scores or touching human files.

## Layout

| Path | Role |
|---|---|
| `catalog.py` | Candidate set, splits, family coverage, asset inventory |
| `reviews.py` | Schema, validation, artifact binding, completion criteria |
| `package.py` | Matched v1/v2 MusicXML, score MIDI, phrase extracts, reports |
| `review_package/` | Generated artifacts (MIDI under `.gitignore`) |
| `INVENTORY.md` | Written inventory snapshot |

## Contracts preserved

- `performance-score-1` default; `performance-score-2` opt-in
- Original MIDI bytes and `source_note_id` identities
- Staff, musical-voice grouping, and printed lanes compared separately
- Export integrity reported apart from musical quality
- `review_complete` ≠ `musically_accepted` ≠ production readiness
