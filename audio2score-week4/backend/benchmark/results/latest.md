# NotaScore benchmark

- timestamp: `2026-08-25T07:50:21Z`
- git: `e581c4c`
- mode: **MIDI ingest** (`midi`)
- cases: 21 (pass 21, fail 0, skip 0)
- fallback count: 0
- regressions vs baseline: 0
- baseline git: `7bb1319`

## Results

Overall: **PASS**

| case | category | pass | hands | voices | meter | plan | fallback | F1 | flags |
|---|---|---|---|---|---|---|---|---|---|
| c_major_quarters | melody_simple | PASS | 1.00 | ok | 4/4 | yes | no | 1.00 |  |
| g_major_eighths | melody_simple | PASS | 1.00 | ok | 4/4 | yes | no | 1.00 |  |
| midi_3_4 | midi_ingest | PASS | 1.00 | ok | 3/4 | yes | no | 1.00 |  |
| midi_6_8 | midi_ingest | PASS | 1.00 | ok | 6/8 | yes | no | 1.00 |  |
| midi_chords_and_melody | midi_ingest | PASS | 0.62 | ok | 4/4 | yes | no | 1.00 |  |
| midi_rh_lh_tracks | midi_ingest | PASS | 1.00 | ok | 4/4 [METER_AMBIGUOUS] | yes | no | 1.00 |  |
| c_major_block_chords | piano_chords | PASS | 1.00 | ok | 4/4 | yes | no | 1.00 |  |
| octave_doubling | piano_chords | PASS | 0.67 | - | 4/4 [METER_AMBIGUOUS] | yes | no | 1.00 |  |
| melody_and_bass | piano_simple | PASS | 1.00 | ok | 4/4 | yes | no | 1.00 |  |
| hand_crossing | piano_two_hands | PASS | 1.00 | ok | 4/4 | yes | no | 1.00 |  |
| middle_register | piano_two_hands | PASS | 1.00 | ok | 4/4 | yes | no | 1.00 |  |
| polyphonic_rh | piano_two_hands | PASS | 0.83 | ok | 4/4 | yes | no | 1.00 |  |
| two_hand_scale | piano_two_hands | PASS | 1.00 | ok | 4/4 | yes | no | 1.00 |  |
| compound_6_8 | rhythm | PASS | 1.00 | ok | 6/8 | yes | no | 1.00 |  |
| dotted | rhythm | PASS | 1.00 | ok | 4/4 [METER_NOT_EVALUATED] | yes | no | 1.00 |  |
| eighths | rhythm | PASS | 1.00 | ok | 4/4 | yes | no | 1.00 |  |
| quarters | rhythm | PASS | 1.00 | ok | 4/4 | yes | no | 1.00 |  |
| sixteenths | rhythm | PASS | 1.00 | ok | 4/4 [METER_NOT_EVALUATED] | yes | no | 1.00 |  |
| syncopation | rhythm | PASS | 1.00 | ok | 4/4 [METER_AMBIGUOUS] | yes | no | 1.00 |  |
| triplets | rhythm | PASS | 1.00 | ok | 4/4 [METER_AMBIGUOUS] | yes | no | 1.00 |  |
| waltz_3_4 | rhythm | PASS | 1.00 | ok | 3/4 | yes | no | 1.00 |  |

## Regressions

None.


## Metrics

- NotationPlan fallbacks: 0
- false legitimate-note removals (sum): 0
