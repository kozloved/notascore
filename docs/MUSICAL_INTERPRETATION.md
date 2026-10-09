# Musical interpretation benchmarks

The transcription (provider MIDI / `raw.mid`) is immutable. This pass only
reinterprets **score time**: tempo scale, meter, written duration, voices,
hands, pickups, and style-aware rhythmic feel. Source `note_id`, pitch,
velocity, and performed seconds never change.

## Interpretation vs simplification vs arrangement

1. **Interpretation** recovers intended notation from a performance (this
   milestone). Example: swung eighths become ordinary eighths plus a Swing
   indication.
2. **Simplification** is an explicit `output_mode=simplified` reduction for
   readability. It may prefer coarser spelling. It does not delete notes.
3. **Arrangement** would change harmony, texture, or instrumentation into a
   **separate** derived score. It is not implemented. The extension point is
   `mir/arrangement.py`. Do not expose a target-style control until it works.

Style and feel are priors for scoring, not hard quantization rules and not
acoustic note detection. Changing them regenerates notation from `{job}.raw.mid`
without GPU transcription.

## What is scored

`mir.score_interpretation.evaluate_candidates` compares tempo scales
`0.5× / 1.0× / 2.0×` against meters `2/4 3/4 4/4 6/8 9/8 12/8`. Audio is
not time-stretched. Each candidate writes a transparent cost:

```text
total =
    timing_cost
  + rhythm_complexity
  + rest_fragmentation
  + tie_complexity
  + voice_complexity
  + measure_complexity
  + grouping_cost
  + small scale prior
```

Jobs write `{job}.candidate_scores.json` as
`{ interpretation_choice, candidates }`. Debug JSON and provenance
repeat `interpretation_choice` with both `performance_bpm` and
`score_bpm`. `{job}.tempo.json` keeps the existing score-facing keys
and adds `performance` / `score` views plus `tempo_scale`.

## Local fixtures

`audio2score-week4/backend/evaluation/production_smoke/cases.json` lists
categories `01-simple-piano` … `10-repeated-notes`. Missing audio is SKIP.
Do not commit copyrighted recordings.

```bash
cd audio2score-week4/backend
python -m evaluation.score_diagnostics
```

MIDI fixtures in that folder are transcribed locally. Real wavs still go
through the deployed API.

## Production OSMD

Frontend options are copied to `backend/evaluation/osmd_config.json`
(from `SheetResult.jsx`). Preview a MusicXML file with:

```bash
node evaluation/render_osmd.mjs score.musicxml evaluation/results/preview
```

Verovio remains available for the older `docs/simple-score-review/`
comparison. OSMD is what customers see.

## Hard regressions

`tests/test_score_interpretation.py` covers:

- jittered quarters stay simple
- genuine sixteenths
- triplets
- syncopation
- 3/4 vs 6/8 grouping costs
- half/double tempo candidates
- pickup only with downbeat evidence
- pedal-like releases write quarters
- two independent voices
- hand crossing allowed
- barline sustains keep ties
- source identity on every candidate evaluation

Federation (RoFormer, Transkun, Beat This!, stem AMT, Gemini MIDI edits)
stays off. Interpretation must work on a single good MIDI first.

## Style-aware feel (production slice)

Inserted in `quantize_notation` after layout, before onset search:

```
MusicalEvent (performed beats)
  → infer_interpretation_spans (beat-space windows)
  → apply_written_timing (reversible r:1 map)
  → candidate search / NotationPlan / MusicXML
```

Profile fields (`interpretation_profile`, version 1): `source_style`,
`rhythmic_feel`, `timing`, `output_mode`, optional `swing_ratio`.
Defaults (`auto` / `faithful`) keep existing jobs compatible. The user does
not choose Swing or Straight before generating a score. Feel is inferred
from the performance; Jazz is not required. Style and feel remain optional
advanced corrections after generation and reuse the same transcription.

The engine infers pulse/meter/tempo, then subdivision feel (straight, swung,
or uncertain), then written placement including syncopation, then local
exceptions (tuplets, dotted figures, straight passages). Swing and
syncopation are independent and can coexist. A syncopated attack is never
moved onto a strong beat to simplify the page.

Swing mapping: for ratio `r:1` the performed offbeat is at `r/(r+1)` of the
subdivision pair; the written position is `1/2`. Seconds are unchanged. Long
sustains are not pulled onto swing slots. Compound meters are never classified
as swing. Genuine triplets inside a swing span stay triplet exceptions.
Uncertain or sparse evidence stays straight, with no confident Swing mark.

Readable writes conventional swing as even eighths plus a Swing word
(or Swing 16ths). Literal still detects feel for the editor but does not
rewrite performed onsets. `output_mode` is an internal spelling nudge
(compatibility only); Readable/Literal remains the user-facing
interpretation axis.

Export puts visible words in `direction-type/words` and playback metadata in
`direction/sound/swing` (`notation_engine/swing_export.py`), using inherited
divisions for offsets. Score MIDI and browser score playback apply the
written→sounded inverse once. Original-performance MIDI is unchanged. OSMD
may ignore `<swing>` and still show the word mark.

Fixtures: `evaluation/swing_fixtures.py`, `tests/test_style_interpretation.py`,
and `tests/test_swing_playback.py`.
