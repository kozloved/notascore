# readable-v2 rollout comparison

Production default remains `performance-score-1`. `performance-score-2` is opt-in.
Fewer rests or ties are not treated as better. Real-audio transcription is out of scope.

## Provenance

- Evidence kind: `synthetic_midi`
- Licensed performances available: `False`
- Local reference MIDI available: `True`
- Default algorithm: `performance-score-1`
- Opt-in algorithm: `performance-score-2`
- Tuning set (last-note pulse): `I_detached_triplet_groups`, `J_intentional_short_triplet_rests`, `K_repeated_triplet_pitches`, `L_held_voice_under_triplets`, `mixed_tuplets`

### Real-material gap

No documented licensed commercial recordings or paired-corpus performances are present. 3 local NotaTestSamples raw/quantized pairs are available and are labeled development reference MIDI, not licensed performances. benchmark/realworld/local has no extra audio/MIDI.

## Recommendation

**continued_opt_in**

Keep performance-score-2 opt-in. Remaining regressions or missing real-performance evidence are listed below. Do not migrate existing jobs or change the default because synthetic tests pass.

### Remaining issues

- `short_rests_repeats`: v2 rest count 10→5. Fewer rests are not automatically better; musician review needed.
- `irregular_triplet_intervals`: v2 filled leftover < sixteenth to the next attack (0.25→0.375), not a 1/3 tuplet. Ambiguous silence; not used to retune.
- `real_performances`: No documented licensed commercial recordings or paired-corpus performances are present. 3 local NotaTestSamples raw/quantized pairs are available and are labeled development reference MIDI, not licensed performances. benchmark/realworld/local has no extra audio/MIDI.
- `long_monophonic_phrase`: Production OSMD compact A4 rendered the 41-bar phrase as 1 page. Multi-page output did not occur. Reported only; renderer was not changed.

## Cases

| Case | Held-out | MIDI preserved | Written identical | Rests v1→v2 | Ties v1→v2 | Measures | Hands/voices |
|---|---|---|---|---|---|---|---|
| `A_detached_regular_line` | yes | yes | no | 10→2 | 0→0 | ok | ok |
| `B_short_notes_with_rests` | yes | yes | yes | 9→9 | 0→0 | ok | ok |
| `humanized_quarters` | yes | yes | yes | 2→2 | 0→0 | ok | ok |
| `short_rests_repeats` | yes | yes | no | 10→5 | 0→0 | ok | ok |
| `mixed_tuplets` | no | yes | no | 9→3 | 0→0 | ok | ok |
| `I_detached_triplet_groups` | no | yes | no | 9→3 | 0→0 | ok | ok |
| `J_intentional_short_triplet_rests` | no | yes | yes | 5→5 | 0→0 | ok | ok |
| `mixed_families_after_bar` | yes | yes | no | 10→4 | 0→0 | ok | ok |
| `irregular_triplet_intervals` | yes | yes | no | 4→2 | 0→0 | ok | ok |
| `final_short_then_silence` | yes | yes | yes | 5→5 | 0→0 | ok | ok |
| `rubato_pickup` | yes | yes | yes | 10→10 | 2→2 | ok | ok |
| `syncopation` | yes | yes | yes | 5→5 | 4→4 | ok | ok |
| `meter_6_8` | yes | yes | yes | 2→2 | 0→0 | ok | ok |
| `C_repeated_attacks_under_pedal` | yes | yes | yes | 1→1 | 0→0 | ok | ok |
| `E_repeated_attacks_no_pedal` | yes | yes | yes | 1→1 | 0→0 | ok | ok |
| `G_held_voice_same_staff` | yes | yes | no | 4→0 | 0→0 | ok | ok |
| `L_held_voice_under_triplets` | no | yes | no | 8→2 | 0→0 | ok | ok |
| `independent_voices_mixed_release` | yes | yes | yes | 6→6 | 0→0 | ok | ok |
| `mixed_release_chord` | yes | yes | yes | 2→2 | 0→0 | ok | ok |
| `unison_crossing` | yes | yes | yes | 4→4 | 0→0 | ok | ok |
| `near_barline_short_release` | yes | yes | yes | 4→4 | 0→0 | ok | ok |
| `long_monophonic_phrase` | yes | yes | yes | 41→41 | 0→0 | ok | ok |
| `160_f_melody_piano` | yes | yes | yes | 21→21 | 10→10 | ok | ok |
| `138_с_chords_piano` | yes | yes | no | 40→32 | 51→32 | ok | ok |
| `88_D_waltz_th_piano` | yes | yes | yes | 55→55 | 14→14 | ok | ok |
| `c_major_quarters` | yes | yes | yes | 2→2 | 0→0 | ok | ok |
| `melody_and_bass` | yes | yes | yes | 0→0 | 0→0 | ok | ok |
| `hand_crossing` | yes | yes | yes | 2→2 | 0→0 | ok | ok |
| `triplets` | yes | yes | yes | 1→1 | 0→0 | ok | ok |
| `syncopation` | yes | yes | yes | 1→1 | 0→0 | ok | ok |
| `compound_6_8` | yes | yes | yes | 0→0 | 0→0 | ok | ok |
| `midi_chords_and_melody` | yes | yes | yes | 0→0 | 0→0 | ok | ok |

## Duration changes (not an automatic improvement)

### `A_detached_regular_line`
- Expected release: Written as quarters; 80ms gaps are articulation, not rests.
- index 0 pitch 72: v1=0.75 v2=1.0
- index 1 pitch 72: v1=0.75 v2=1.0
- index 2 pitch 72: v1=0.75 v2=1.0
- index 3 pitch 72: v1=0.75 v2=1.0
- index 4 pitch 72: v1=0.75 v2=1.0
- index 5 pitch 72: v1=0.75 v2=1.0
- index 6 pitch 72: v1=0.75 v2=1.0
- index 7 pitch 72: v1=0.75 v2=1.0

### `short_rests_repeats`
- index 0 pitch 76: v1=0.1875 v2=0.25
- index 2 pitch 76: v1=0.1875 v2=0.25
- index 3 pitch 76: v1=0.1875 v2=0.25
- index 4 pitch 76: v1=0.1875 v2=0.25
- index 5 pitch 76: v1=0.1875 v2=0.25

### `mixed_tuplets`
- Expected release: v1: sixteenths at triplet onsets. v2: all six written 1/3, including the last.
- index 4 pitch 72: v1=0.25 v2=0.3333
- index 5 pitch 73: v1=0.25 v2=0.3333
- index 6 pitch 74: v1=0.25 v2=0.3333
- index 7 pitch 72: v1=0.25 v2=0.3333
- index 8 pitch 73: v1=0.25 v2=0.3333
- index 9 pitch 74: v1=0.25 v2=0.3333

### `I_detached_triplet_groups`
- Expected release: All six written as triplet eighths (1/3), including each group-ending note.
- index 0 pitch 72: v1=0.25 v2=0.3333
- index 1 pitch 72: v1=0.25 v2=0.3333
- index 2 pitch 72: v1=0.25 v2=0.3333
- index 3 pitch 72: v1=0.25 v2=0.3333
- index 4 pitch 72: v1=0.25 v2=0.3333
- index 5 pitch 72: v1=0.25 v2=0.3333

### `mixed_families_after_bar`
- Expected release: Keep both families. Last triplet must not steal the returning quarter.
- index 4 pitch 72: v1=0.25 v2=0.3333
- index 5 pitch 73: v1=0.25 v2=0.3333
- index 6 pitch 74: v1=0.25 v2=0.3333
- index 7 pitch 72: v1=0.25 v2=0.3333
- index 8 pitch 73: v1=0.25 v2=0.3333
- index 9 pitch 74: v1=0.25 v2=0.3333

### `irregular_triplet_intervals`
- Expected release: Keep performed spacing. Do not rewrite as regular triplet eighths.
- index 0 pitch 72: v1=0.25 v2=0.375
- index 1 pitch 74: v1=0.25 v2=0.375

### `G_held_voice_same_staff`
- Expected release: The hold lasts the bar; moving notes keep their releases.
- index 0 pitch 76: v1=0.75 v2=1.0
- index 2 pitch 77: v1=0.75 v2=1.0
- index 3 pitch 78: v1=0.75 v2=1.0
- index 4 pitch 79: v1=0.75 v2=1.0

### `L_held_voice_under_triplets`
- Expected release: Bass lasts its span; treble last note is a triplet eighth.
- index 0 pitch 72: v1=0.25 v2=0.3333
- index 2 pitch 73: v1=0.25 v2=0.3333
- index 3 pitch 74: v1=0.25 v2=0.3333
- index 4 pitch 72: v1=0.25 v2=0.3333
- index 5 pitch 73: v1=0.25 v2=0.3333
- index 6 pitch 74: v1=0.25 v2=0.3333

### `138_с_chords_piano`
- index 7 pitch 60: v1=3.9583 v2=4.0
- index 8 pitch 67: v1=3.4792 v2=3.5
- index 9 pitch 71: v1=3.6458 v2=4.0
- index 13 pitch 67: v1=7.5833 v2=7.5625

## Pagination

Production OSMD (`pageFormat: A4_P`, `drawingParameters: compact`) is the SheetResult path. The 41-bar held-out phrase rendered as one page and six systems. The production PDF page count matched OSMD. Multi-page output was requested and did not occur. This is a renderer layout result, not a v2 duration change.

## Rendered exports

- `B_short_notes_with_rests` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `B_short_notes_with_rests` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `mixed_tuplets` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `mixed_tuplets` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `final_short_then_silence` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `final_short_then_silence` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `meter_6_8` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `meter_6_8` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `independent_voices_mixed_release` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `independent_voices_mixed_release` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `mixed_release_chord` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
  - OSMD mixed-chord limitation: per-member marks are in MusicXML; the renderer may still show a unioned chord mark.
- `mixed_release_chord` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
  - OSMD mixed-chord limitation: per-member marks are in MusicXML; the renderer may still show a unioned chord mark.
- `unison_crossing` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `unison_crossing` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `near_barline_short_release` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `near_barline_short_release` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `long_monophonic_phrase` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `long_monophonic_phrase` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `160_f_melody_piano` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `160_f_melody_piano` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `138_с_chords_piano` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `138_с_chords_piano` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `88_D_waltz_th_piano` v1: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None
- `88_D_waltz_th_piano` v2: export_completed=True parsed=True page_count_verified=True pages_rendered=True visual_review_completed=False status=passed reason=None

## Commands

```bash
cd audio2score-week4/backend
python -m pytest -q tests/test_export_evidence_structure.py tests/test_readable_v2_rollout.py tests/test_readable_v2_cases.py
python -m evaluation.readable_v2_rollout evaluation/readable_v2_rollout/out
python -m evaluation.readable_v2_rollout evaluation/readable_v2_rollout/out --render
```

