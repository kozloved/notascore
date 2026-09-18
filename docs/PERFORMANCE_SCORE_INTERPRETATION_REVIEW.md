# Performance-to-score interpretation review

**Branch:** `cursor/performance-score-interpretation-95a8`  
**Base:** current `main` (`2b466fb` historical review baseline; not reset)  
**Date:** 2026-09-18  
**Design reference:** Logic Pro 11 score-interpretation workflow (independent implementation; not Apple integration)

This is a newly run review. It is not a restatement of
`docs/HANDS_RHYTHM_PHASE3_REVIEW_2026-09-13.md` or
`docs/TRANSCRIPTION_RELIABILITY_REVIEW.md`.

## What changed

The existing performance-to-score engine now has one execution contract,
explicit reversible notation settings, and meter-aware spelling inside
`exact_plan.py`. Raw MIDI bytes, checksums, source note IDs, and performed
timing are unchanged. Readable-v2 policies stay opt-in
(`algorithm_version=performance-score-2`).

## Phase summary

1. **Execution contract.** Production jobs always run `QuantizationMode.PERFORMANCE`.
   Experimental env values (`adaptive`, `strict_grid`, `off`, `pm2s`) parse, then
   fall back with an explicit reason in health, config, and debug. Unknown modes
   are rejected by `parse_quantization_mode` / `require_production_quantization_mode`.
2. **Notation settings.** Validated model: display grid, triplet policy,
   interpretation, syncopation, overlap, max dots, meter/pickup, measure-range
   overrides. Defaults reproduce `performance-score-1`. Contradictory overrides
   raise. Settings persist in `{job}.notation_settings.json` and participate in
   notation cache identity.
3. **Rhythm / duration.** Bounded search logs beat + millisecond displacement,
   local tempo, source IDs, and release reasons. Pedal CC64 is labeled `cc64`;
   inferred tails are `hypothesis`. Independent holds are not shortened merely
   because another note starts on the same staff.
4. **Meter-aware spelling.** `show_meter` splits at beat grouping (6/8 as two
   compound beats). Barline ties always apply. Structural filler rests are
   distinct from musical rests. Exact source coverage is retained.
5. **Correction workflow.** GET/POST `/jobs/{id}/notation-settings` regenerates
   MusicXML from `{job}.raw.mid` without transcription. Editor controls:
   Readable/Literal, display grid, meter/pickup, Reset interpretation.
   Listen preview labels original-performance vs score playback separately.
6. **Fixtures.** Nine MIDI cases in
   `audio2score-week4/backend/evaluation/notation_fixtures.py`.

## Newly run tests (this branch)

Command (from `audio2score-week4/backend`):

```
.venv/bin/pytest tests/test_quantization_contract.py tests/test_notation_settings.py \
  tests/test_notation_interpretation.py tests/test_performance_score.py \
  tests/test_simple_score.py tests/test_job_context.py tests/test_performance_cli.py \
  tests/test_export_integrity.py tests/test_notation_integrity.py \
  tests/test_quantizer_identity.py tests/test_score_interpretation.py \
  tests/test_notation_plan.py tests/test_notation_plan_production.py \
  tests/test_pipeline_config.py
```

Results:

- New tests: 33 passed, 1 skipped (httpx-gated API test ran in the 33).
- Existing gates above: 189 then 110+115 after fixing the 3-tuple release
  hypothesis assertion. Combined: all selected gates green after that one
  expected-tuple update.
- Default settings still match historical `quantize_notation` on a jittered
  quarter phrase. Reference expectations were not loosened.

Historical Phase 3 / reliability numbers remain in their original docs.

## Fixture comparisons

All nine fixtures keep the raw MIDI SHA-256 unchanged through `convert`.
Source note counts match the ingested performance. Timing error and notation
complexity are reported separately (`max_onset_error_beats` /
`max_onset_error_ms` vs voice count / written durations).

| Fixture | MIDI hash unchanged | Source notes | Notes |
|---|---|---|---|
| `humanized_quarters` | yes | 8 | Default readable writes quarters (mean written duration 1.0); ~45 ms max onset error |
| `short_rests_repeats` | yes | 7 | Distinct attacks; musical rest kept |
| `melody_over_bass` | yes | 10 | Two voices; bass hold not truncated |
| `syncopation` | yes | 5 | `show_meter` adds beat-aligned ties vs `preserve` |
| `meter_3_4` | yes | 6 | 3/4 measures |
| `meter_6_8` | yes | 4 | Compound beat spelling of exact 3/2 values; barline ties |
| `mixed_tuplets` | yes | 10 | Binary and triplet families both present |
| `rubato_pickup` | yes | 7 | Beat and ms error both logged; literal closer in ms |
| `unison_crossing` | yes | 9 | Three printed lanes; independent overlapping unisons kept |

On this default (`performance-score-1`) vocabulary, readable vs literal often
share the same written durations. Rubato is the clear exception (literal
0.625 vs readable 0.679 mean written duration; max error 50 ms vs 131 ms).
Do not treat identical symbol counts as visual improvement.

## OSMD visual inspection (production config)

Rendered with `evaluation/render_osmd.mjs` (same constructor/engraving
options as `SheetResult.jsx`) and headless Chrome.

- Humanized quarters: eight clean quarters, empty bass staff, no micro-rests.
  Current readable, literal, and opt-in v2 look the same on this fixture.
- Melody over bass: left-hand tied whole notes survive under the melody.
  Melody still shows dotted-eighth + 16th rest from performed 0.42 s releases.
- Short rests / repeats: attacks stay separate; an eighth rest appears after
  the first pair. Spelling is busy (dotted 16ths) because performed notes are
  0.10 s.
- Syncopation preserve: off-beat quarters after an eighth rest; barline tie
  on the long last note.
- Syncopation show_meter: same attacks split onto the beat with extra ties.
  Last bar rest spelling also changes. A stray triplet 3 appears on the long
  final value in both policies — remaining limitation, not claimed as a win.
- 6/8: two measures of dotted quarters (compound duple). Display tempo still
  prints as a float (`90.00009`).

## Remaining limitations

- `performance-score-2` stays opt-in. On these fixtures it did not produce a
  clearly better OSMD image than `performance-score-1`.
- First UI exposes score-wide Readable/Literal, display grid, meter, and
  pickup. Measure-range overrides are validated in the model but not edited
  in the panel.
- PrettyMIDI cannot represent two identical unison notes at the same
  pitch/time; overlapping unisons at distinct times are preserved.
- Display tempo may print as a float (seen on the 6/8 fixture).
- `show_meter` can over-split and still inherit tuplet brackets on long
  values. Visual review must stay opt-in for that policy.
- Multi-instrument collapse still warns via `score_profile`; the editor
  surfaces provenance rather than presenting a silent solo transcription.
