# Hands and rhythm review update (after 80077f6)

Built on `80077f6`. Improves **printed lane reuse** without changing release
hypotheses, downbeat alignment, or performed timings.

**Visual review is not marked complete** — matched phrase MusicXML refreshed;
OSMD PNGs need local Playwright Chromium.

## Code changes

1. **`_stable_lanes`** — musical `voice` is line identity (home-lane preference,
   chord grouping). Printed lanes reuse any inactive lane. Independent unisons
   stay separate; holds are not shortened to reduce lane count.
2. **Voice metrics** — distinct voice IDs per measure·staff vs peak **voice**
   concurrency (sustains from earlier measures included) vs peak **note**
   concurrency (chord members counted separately).
3. **Synthetic regressions** — overlapping lines, pitch crossings, chord ties
   across bars, repeated-pitch overlaps, metrics separation.

## Autumn Walks hotspot (measure 4 / RIGHT)

Before lane reuse: voices `[0,1,2,3]` with peak concurrency 2.  
After: printed voices `0/1` only (`18→0`, `19→1`, `20→0`, `24→1`, `28→0`).

Whole-score MusicXML `max_voices_in_measure_staff`: **4 → 3** (Δ vs frozen
before: **0**). Event metrics: distinct IDs 3, peak voices 3, peak notes 4
(left-hand chord under long sustains — real polyphony, not ID inflation).

## Tests

Supported suite: `pytest -m 'not integration and not pm2s'` → **757 passed**,
4 deselected (reconfirm after peak-note metric tweak in the same change set).

## Comparable metrics (MT3 semantics)

| Metric | Before | After | Δ |
| --- | ---: | ---: | ---: |
| Pitched symbols | 155 | 120 | −35 |
| Tie starts | 55 | 20 | −35 |
| Tiny (32nd+) | 37 | 5 | −32 |
| Time modifications | 20 | 2 | −18 |
| Max voices / measure·staff (MusicXML IDs) | 3 | 3 | 0 |
| Peak voice concurrency (events) | — | 3 | — |
| Peak note concurrency (events) | — | 4 | — |
| Attacks | 100 | 100 | 0 |

Matched phrases (`.tmp/.../phrase_renders_matched/`, `fifths=-5`): readability
improves via fewer idle voice IDs; attack inventory and performed times unchanged
by design.

## Remaining limitations

- Peak note concurrency can exceed peak voices when chords share a lane (expected).
- Dense left-hand sustains still need 3 written voices; not forced down to 2.
- OSMD PNG refresh blocked without Playwright browsers.
- Pianist sign-off still outstanding.

## Reproduce

```bash
cd audio2score-week4/backend
.venv/bin/python -m evaluation.hands_rhythm_metrics --write-baseline
.venv/bin/python -m pytest -m 'not integration and not pm2s' -q
```
