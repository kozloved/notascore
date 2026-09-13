# Hands and rhythm review update (after 44fffac)

Consolidates printed lane reuse with explicit musical-line identity in events and
diagnostics. No duration-heuristic changes in this pass.

**Visual review is partial** — matched OSMD PNGs regenerated with the production
render script (`evaluation/render_osmd.mjs` + `osmd_config.json`) after fixing
Playwright browser discovery via `PLAYWRIGHT_BROWSERS_PATH`.

## Code

1. **`musical_voice` / `voice_provenance`** on `MusicalEvent`, `ScoreNote`, and
   quantization decisions (`printed_voice`, `voice_assigned`). Line identity is
   preserved when `voice` becomes the printed lane.
2. **`_stable_lanes`** unchanged in packing policy from `44fffac`; now stamps
   identity fields on returned events.
3. **Regressions** — borrow-then-return melody; simultaneous returning lines;
   export round-trip attack inventory; release/downbeat unchanged under reuse.

## Measured results (not visual)

Supported suite: **761 passed**, 4 deselected.

Autumn Walks (MT3 semantics, forced 3/4):

| Metric | Before | After | Δ |
| --- | ---: | ---: | ---: |
| Pitched symbols | 155 | 120 | −35 |
| Tie starts | 55 | 20 | −35 |
| Tiny | 37 | 5 | −32 |
| Time modifications | 20 | 2 | −18 |
| MusicXML max voice IDs / measure·staff | 3 | 3 | 0 |
| Peak voice concurrency (events) | — | 3 | — |
| Peak note concurrency (events) | — | 4 | — |
| Attacks | 100 | 100 | 0 |

Matched phrases (same extract settings, `fifths=-5`):

| Phrase | pitched | ties | tiny | voice IDs |
| --- | ---: | ---: | ---: | ---: |
| mm1–4 | 25→23 | 7→5 | 2→2 | 2→2 |
| mm5–8 | 46→32 | 18→4 | 15→1 | 3→3 |
| mm13–16 | 41→32 | 15→6 | 9→0 | 3→3 |

## Visual judgments (OSMD PNG inspection)

Judgments are qualitative and separate from the table above.

- **mm1–4 after:** Grand-staff stems separate melody (up) from holds (down);
  bass ledger sustains readable; rests present in inactive lanes; mild triplet
  crowding in m3 treble.
- **mm5–8:** After is less fragmented than before (fewer tinies/ties in metrics).
  Still dense polyphony; ledger extremes and tie proximity remain; stems generally
  oppose for outer lines.
- **mm13–16:** After clearer than before (no tinies). Long upper ties and deep
  ledger chords still crowd; rests mark inactive middle lanes; stem opposition
  keeps returning lower motion distinct in m16.

## Playwright

Browsers installed under
`node_modules/playwright-core/.local-browsers`. Render with:

```bash
export PLAYWRIGHT_BROWSERS_PATH="$PWD/node_modules/playwright-core/.local-browsers"
node evaluation/render_osmd.mjs <musicxml> <out_dir>
```

## Remaining limitations

- Peak notes can exceed peak voices when chords share a lane.
- Extreme ledger + multi-tie crowding is an engraving readability issue, not fixed
  by lane reuse alone.
- Pianist sign-off still outstanding.

## Reproduce

```bash
cd audio2score-week4/backend
.venv/bin/python -m evaluation.hands_rhythm_metrics --write-baseline
.venv/bin/python -m pytest -m 'not integration and not pm2s' -q
```
