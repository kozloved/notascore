# P1 musical baseline review package

- Generated: `2026-09-28T14:25:08.433537+00:00`
- Mode: `package`
- Cases packaged: **15** (development 9, held-out 6)
- Default algorithm: `performance-score-1`
- Opt-in algorithm: `performance-score-2`
- Splits disjoint: `True`
- Review complete: **0**
- Musically accepted: **0**
- Reviewed but not accepted: **0**
- Stale reviews: **0**
- P1 complete: **False**
- Reason: 0/15 cases meet review_complete criteria; 0/15 musically accepted (interpretation pass). Do not mark P1 complete without attributed current reviews. Completion is not production readiness.

## Family coverage

- `solo_line`: ok (`dev-solo-detached`, `dev-intentional-rests`, `dev-meter-3-4`, `hold-final-short`)
- `piano_accompaniment`: ok (`dev-melody-bass`, `hold-catalog-melody-bass`)
- `independent_voices`: ok (`dev-independent-voices`, `hold-independent-mixed`)
- `pedal_repeated_notes`: ok (`dev-melody-bass`, `dev-pedal-repeats`, `hold-repeats-no-pedal`)
- `intentional_rests`: ok (`dev-intentional-rests`, `hold-independent-mixed`, `hold-final-short`)
- `detached_articulation`: ok (`dev-solo-detached`, `dev-detached-triplets`)
- `triplets`: ok (`dev-detached-triplets`, `hold-catalog-triplets`)
- `syncopation`: ok (`dev-syncopation`)
- `pickup`: ok (`dev-pickup`)
- `meter_3_4`: ok (`dev-meter-3-4`)
- `meter_6_8`: ok (`hold-meter-6-8`)

## Cases

| Example | Split | Complete | Accepted | Stale | Interp | Export | Correction | Acoustic |
|---|---|---|---|---|---|---|---|---|
| `dev-solo-detached` | `development` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `dev-intentional-rests` | `development` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `dev-melody-bass` | `development` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `dev-pedal-repeats` | `development` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `dev-independent-voices` | `development` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `dev-detached-triplets` | `development` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `dev-syncopation` | `development` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `dev-pickup` | `development` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `dev-meter-3-4` | `development` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `hold-repeats-no-pedal` | `held_out` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `hold-independent-mixed` | `held_out` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `hold-meter-6-8` | `held_out` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `hold-final-short` | `held_out` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `hold-catalog-triplets` | `held_out` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |
| `hold-catalog-melody-bass` | `held_out` | `False` | `False` | `False` | `not_reviewed` | `passed` | `not_reviewed` | `not_applicable` |

## Gaps

- `paired_corpus_recordings` (missing): Slot templates exist; complete_slots=0; no audio/MIDI/score.
- `evaluation_holdout_cases` (missing): Directory present; no case assets committed.
- `evaluation_real_world_cases` (missing): Directory present; no case assets committed.
- `benchmark_realworld_local` (missing): Ad-hoc local audio slot; empty or gitignored.
- `human_reviewed_ratings` (missing): Generators and rubric exist; no attributed musician ratings.
- `production_smoke_audio` (missing): cases.json names expected WAVs; audio not committed.
- `nota_test_sample_licenses` (undocumented): 3 local raw/quantized/audio pairs present; license and composition identity not documented; not musician-reviewed.
- `acoustic_accuracy_labels` (missing): No reviewed acoustic-accuracy labels on any asset.
- `correction_effort_labels` (missing): No human correction-effort ratings on any asset.

## Commands

```bash
cd audio2score-week4/backend
python -m evaluation.musical_baseline --inventory
python -m evaluation.musical_baseline --package evaluation/musical_baseline/review_package
python -m evaluation.musical_baseline --package evaluation/musical_baseline/review_package --render
python -m evaluation.musical_baseline --report-reviews evaluation/musical_baseline/review_package
python -m pytest -q tests/test_musical_baseline.py
```
