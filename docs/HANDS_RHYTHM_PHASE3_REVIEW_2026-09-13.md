# Hands and rhythm review update (after d122849)

Fixes remaining release-inference / validation gaps on top of `d122849`. **Visual
review is not marked complete** — OSMD phrase PNGs were inspected where available;
`before_mm5-8` failed to snapshot, and frozen-before vs MT3-after excerpts are not
measure-identical (key/pickup differences), so pianist sign-off is still required.

## Code fixes

1. **Independent hold vs pedal** — `_pulsed_line_evidence` required before different-pitch
   shortening. Regression: two-beat held C + inner E at beat 1 must not clip (`no_line`).
   Same-pitch pulsed pedal tails still cap for voice search only.
2. **Autumn Walks MT3 semantics** — replay stamps `source_backend="mt3"` on frozen MIDI
   payload notes/events so `preserve=` duration path stays off (matches production MT3).
3. **Tie metrics** — `musicxml_complexity` counts each note’s musical tie start once
   (`<tie>` and `<tied>` no longer double-count).

## Tests

- Focused hands/performance/metrics/downbeat/interpretation: passed
- Supported backend suite: `pytest -m 'not integration and not pm2s'` → **738 passed, 4 deselected**

## Comparable Autumn Walks metrics (recounted ties)

Controls: same `mt3-original.mid` SHA, `detected-beats.json`, forced `3/4`, **MT3**
source semantics, performance quantization.

| Metric | `current-main.musicxml` | Aligned after | Δ |
| --- | ---: | ---: | ---: |
| Pitched symbols | 155 | 120 | −35 |
| Tie starts (once each) | 55 | 20 | −35 |
| Tiny (32nd+) | 37 | 5 | −32 |
| Time modifications | 20 | 2 | −18 |
| Max voices / measure·staff | 3 | 3 | 0 |
| Source attacks | 100 | 100 | 0 |
| Source identity preserved | — | true | — |
| `duration_preserve_enabled` | — | false | — |
| Event backends | — | `["mt3"]` | — |

## Phrase renders (local only)

Under `.tmp/autumn-walks-review/phrase_renders/`:

| Phrase | Inspected | Observation |
| --- | --- | --- |
| mm1–4 before/after | yes (OSMD PNG) | Sustained upper-line ties remain; after is cleaner but not glyph-identical to before |
| mm5–8 after | yes | Long bass holds without 128th tails; fewer fragments than music21 before analysis |
| mm5–8 before | **PNG missing** (OSMD wait timeout) | Not visually compared |
| mm13–16 before/after | yes | Before: dense multi-voice bass + tiny tails; after: sustained melody ties + simpler held bass under chords |

Music21 phrase stats (supporting the renders): mm13–16 tinies 7→0; mm5–8 tinies 14→2;
tied element counts drop in each window.

## Remaining limitations

- Held-key reach vs pedal still unmodeled beyond release hypotheses.
- Line evidence for pedal is pulsed-context only; richer voice+release joint search open.
- Visual review incomplete (`before_mm5-8` snapshot failed; before/after key/pickup differ).
- Pianist phrase review and annotated holdouts still outstanding.
- Do not claim perfect hands from Autumn Walks alone.

## Reproduce

```bash
cd audio2score-week4/backend
.venv/bin/python -m evaluation.hands_rhythm_metrics --write-baseline
.venv/bin/python -m pytest -m 'not integration and not pm2s' -q
# optional phrase OSMD:
# node evaluation/render_osmd.mjs .tmp/autumn-walks-review/phrase_renders/after_mm13-16.musicxml \
#   .tmp/autumn-walks-review/phrase_renders/after_mm13-16
```
