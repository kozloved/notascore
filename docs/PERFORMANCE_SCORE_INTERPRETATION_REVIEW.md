# Performance-to-score interpretation review

**Branch:** `cursor/performance-score-interpretation-95a8`  
**Base:** current `main` (`2b466fb` historical review baseline; not reset)  
**Date:** 2026-09-18  
**Design reference:** Logic Pro 11 score-interpretation workflow (independent implementation; not Apple integration)

This document is a newly run review. It is not a restatement of
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
   raise. Settings and algorithm version persist in `{job}.notation_settings.json`
   and participate in notation cache identity.
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
6. **Fixtures.** Nine MIDI cases cover the eight requested musical situations
   (3/4 and 6/8 are separate). See `audio2score-week4/backend/evaluation/notation_fixtures.py`.

## Fixture comparisons

Comparisons are produced by `tests/test_notation_interpretation.py` through the
production CLI (`mir.performance_cli.convert`) and `quantize_notation`.

| Fixture | Intent | Expected vs current default |
|---|---|---|
| `humanized_quarters` | Late attacks, tiny release gaps | Default readable still closes to simple quarters; literal keeps performed releases closer |
| `short_rests_repeats` | Intentional rests + repeated 16ths | Attacks stay distinct; musical rest remains |
| `melody_over_bass` | Melody over sustained bass + CC64 | Bass hold is not truncated to melody attacks |
| `syncopation` | Off-beats crossing beats/barlines | `preserve` keeps writable syncopation; `show_meter` splits |
| `meter_3_4` | Simple triple | 3/4 measures, barline ties valid |
| `meter_6_8` | Compound duple | Dotted-quarter beats; barline split with ties |
| `mixed_tuplets` | Binary then triplet eighths | Both families survive; no collapsed attacks |
| `rubato_pickup` | Tempo map + pickup | Beat and ms error both reported; pickup offsets score time only |
| `unison_crossing` | Unisons, independent holds, staff crossing | Source IDs preserved; voice timelines valid |

Default settings are required to match historical `quantize_notation` output
on a jittered quarter phrase. Do not update that expectation to hide a
regression.

## Test results (newly run)

Filled in after pytest on this branch. Historical reports stay in their
original files.

## Remaining limitations

- `performance-score-2` passage-level family unification is opt-in until
  musical and visual review of OSMD renders passes.
- Measure-range overrides are validated and applied in spelling/search, but
  the first UI only exposes score-wide Readable/Literal, grid, meter, and pickup.
- PrettyMIDI may merge byte-identical unison notes; independent overlapping
  unisons at distinct times are preserved.
- OSMD collision/stem/beam judgment is visual, not a symbol-count metric.
- Changing meter/pickup reinterprets score coordinates; it does not rewrite
  performed seconds.
- Multi-instrument collapse still warns via `score_profile`; the UI surfaces
  provenance text rather than silently presenting a solo transcription.

## Invariants checked

- Original MIDI hash unchanged through convert, regen, and the notation-settings API.
- Source attack/pitch inventory preserved (no deleted attacks to simplify).
- Performed vs written duration both stored on each decision.
- Hand, musical voice, and printed voice remain separate fields.
- Transcription is not invoked when regenerating notation.
