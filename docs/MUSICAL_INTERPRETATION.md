# Musical interpretation benchmarks

The transcription (provider MIDI / `raw.mid`) is immutable. This pass only
reinterprets **score time**: tempo scale, meter, written duration, voices,
hands, pickups. Source `note_id`, pitch, velocity, and performed seconds
never change.

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

Jobs write `{job}.candidate_scores.json`. Debug JSON repeats the table plus
`interpretation_choice`, `pickup`, `hand_decisions`, and
`notation_complexity_warning`. Warnings never delete notes.

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
