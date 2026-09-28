# P1 asset inventory

- Package-eligible candidates: **15**
- Musician-reviewed: **0**
- Splits disjoint: `True`
- P1 complete: `False`
- Reason: Candidate inventory and review package infrastructure exist, but musician_reviewed=0. P1 acceptance requires attributed reviews; do not mark complete without them.

## Candidates

| Example | Split | Composition | Families | License | Reviewed | Acoustic labels |
|---|---|---|---|---|---|---|
| `dev-solo-detached` | `development` | `p1-comp-detached-line` | solo_line, detached_articulation | `synthetic_repo_fixture` | `False` | `False` |
| `dev-intentional-rests` | `development` | `p1-comp-short-rests` | intentional_rests, solo_line | `synthetic_repo_fixture` | `False` | `False` |
| `dev-melody-bass` | `development` | `p1-comp-melody-over-bass` | piano_accompaniment, pedal_repeated_notes | `synthetic_repo_fixture` | `False` | `False` |
| `dev-pedal-repeats` | `development` | `p1-comp-pedal-repeats` | pedal_repeated_notes | `synthetic_repo_fixture` | `False` | `False` |
| `dev-independent-voices` | `development` | `p1-comp-held-voice-same-staff` | independent_voices | `synthetic_repo_fixture` | `False` | `False` |
| `dev-detached-triplets` | `development` | `p1-comp-detached-triplets` | triplets, detached_articulation | `synthetic_repo_fixture` | `False` | `False` |
| `dev-syncopation` | `development` | `p1-comp-syncopation` | syncopation | `synthetic_repo_fixture` | `False` | `False` |
| `dev-pickup` | `development` | `p1-comp-rubato-pickup` | pickup | `synthetic_repo_fixture` | `False` | `False` |
| `dev-meter-3-4` | `development` | `p1-comp-meter-3-4` | meter_3_4, solo_line | `synthetic_repo_fixture` | `False` | `False` |
| `hold-repeats-no-pedal` | `held_out` | `p1-comp-repeats-no-pedal` | pedal_repeated_notes | `synthetic_repo_fixture` | `False` | `False` |
| `hold-independent-mixed` | `held_out` | `p1-comp-independent-mixed-release` | independent_voices, intentional_rests | `synthetic_repo_fixture` | `False` | `False` |
| `hold-meter-6-8` | `held_out` | `p1-comp-meter-6-8` | meter_6_8 | `synthetic_repo_fixture` | `False` | `False` |
| `hold-final-short` | `held_out` | `p1-comp-final-short-silence` | intentional_rests, solo_line | `synthetic_repo_fixture` | `False` | `False` |
| `hold-catalog-triplets` | `held_out` | `p1-comp-catalog-triplets` | triplets | `synthetic_repo_fixture` | `False` | `False` |
| `hold-catalog-melody-bass` | `held_out` | `p1-comp-catalog-melody-bass` | piano_accompaniment | `synthetic_repo_fixture` | `False` | `False` |

## Gaps

- `paired_corpus_recordings` @ `evaluation/paired_corpus` — **missing**: Slot templates exist; complete_slots=0; no audio/MIDI/score.
- `evaluation_holdout_cases` @ `evaluation/holdout` — **missing**: Directory present; no case assets committed.
- `evaluation_real_world_cases` @ `evaluation/real_world` — **missing**: Directory present; no case assets committed.
- `benchmark_realworld_local` @ `benchmark/realworld/local` — **missing**: Ad-hoc local audio slot; empty or gitignored.
- `human_reviewed_ratings` @ `evaluation/human_reviewed` — **missing**: Generators and rubric exist; no attributed musician ratings.
- `production_smoke_audio` @ `evaluation/production_smoke` — **missing**: cases.json names expected WAVs; audio not committed.
- `nota_test_sample_licenses` @ `evaluation/development/NotaTestSamples` — **undocumented**: 3 local raw/quantized/audio pairs present; license and composition identity not documented; not musician-reviewed.
- `acoustic_accuracy_labels` @ `n/a` — **missing**: No reviewed acoustic-accuracy labels on any asset.
- `correction_effort_labels` @ `n/a` — **missing**: No human correction-effort ratings on any asset.

## NotaTestSamples (present, not package-claimed as licensed)

- `160_f_melody_piano` audio=`evaluation/development/NotaTestSamples/Case1/160_f_melody_piano_audio.wav` license=`undocumented_in_repo` reviewed=`False`
- `138_с_chords_piano` audio=`evaluation/development/NotaTestSamples/Case2/138_с_chords_piano_audio.wav` license=`undocumented_in_repo` reviewed=`False`
- `88_D_waltz_th_piano` audio=`evaluation/development/NotaTestSamples/Case3/88_D_waltz_th_piano_audio.wav` license=`undocumented_in_repo` reviewed=`False`
