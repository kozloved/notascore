# Hands and rhythm review update (release decision → duration)

Built on `a40f1e4`. Fixes the end-to-end gap where `_release_hypothesis` kept an
independent hold (`no_line`) but `_written_overlap` / `_duration` still truncated
it via the acoustic ratio heuristic when both MT3 events already had RIGHT/voice-0
assignments (`voice_assigned=True`).

**Visual review is not marked complete** — matched phrase OSMD PNGs were generated
and inspected; pianist sign-off and annotated holdouts remain outstanding.

## Code fixes

1. **Carry release decision into duration** — `_written_overlap(..., release_reason=)`
   and `_duration` honor accepted reasons:
   - `no_line` / `independent_hold` / `overlapping_repeat` / `multi_attack_hold` →
     keep written overlap (do **not** silently shorten)
   - `pedal_tail` → still cap for written quarters / voice search
   - otherwise fall back to the ratio heuristic
2. **`_release_decisions`** maps `note_id → (release_at, reason)` before quantization;
   decisions report includes `release_reason` / `release_at`.
3. **Regression through quantize + MusicXML** —
   `test_held_c_with_inner_e_survives_quantize_and_musicxml` (written C=2, E=1,
   distinct voices, export succeeds; performed times unchanged).
4. **Matched phrase renders** — `write_matched_phrase_renders` extracts mm1–4 /
   mm5–8 / mm13–16 with forced before-key fifths, same measure windows, and
   after-phrase `source_ids` from quantized events. Output under
   `.tmp/autumn-walks-review/phrase_renders_matched/` (local only).

## Tests

- Focused: `test_performance_score` / `test_score_interpretation` /
  `test_hands_rhythm_metrics` / `test_hand_separator` → **80 passed**
- Supported backend suite: `pytest -m 'not integration and not pm2s'` →
  **739 passed, 4 deselected**

## Comparable Autumn Walks metrics (MT3 semantics)

Controls: same `mt3-original.mid` SHA, `detected-beats.json`, forced `3/4`,
`source_backend="mt3"` (preserve duration path off), performance quantization.

| Metric | `current-main.musicxml` | Aligned after | Δ |
| --- | ---: | ---: | ---: |
| Pitched symbols | 155 | 120 | −35 |
| Tie starts (once each) | 55 | 20 | −35 |
| Tiny (32nd+) | 37 | 5 | −32 |
| Time modifications | 20 | 2 | −18 |
| Max voices / measure·staff | 3 | 4 | +1 |
| Source attacks | 100 | 100 | 0 |
| Source identity preserved | — | true | — |
| `duration_preserve_enabled` | — | false | — |
| Event backends | — | `["mt3"]` | — |

Voice increase note: max simultaneous written voices rose vs frozen before
(hotspot measure 4 / staff 0 with voices 0–3). Consistent with keeping independent
holds instead of truncating them; not meter drift. Pedal-tail quarters still
simplify on the synthetic fixture.

Matched phrase MusicXML complexity (tiny totals): mm1–4 2→2; mm5–8 15→1;
mm13–16 9→0. All windows force `fifths=-5` in XML.

## Phrase renders (local only)

Under `.tmp/autumn-walks-review/phrase_renders_matched/` (HTML + SVG + PNG after
`npx playwright install chromium`):

| Phrase | Inspected | Observation |
| --- | --- | --- |
| mm1–4 before/after | yes | Same key fifths in XML (−5); after keeps multi-voice holds without clipping the independent upper line; not glyph-identical to before |
| mm5–8 before/after | yes | Before denser (tuplets / tiny tails); after cleaner polyphony; OSMD layout still crowded |
| mm13–16 before/after | yes | Before: dense multi-voice + extreme ledger artifacts; after: simpler held lines under chords, still some extreme ledger placement |

## Remaining visual-review limitations

- Matched extracts share key/meter/measure numbers in MusicXML, but OSMD may still
  show staff/clef layout differences (e.g. mid-piece excerpts without a full
  grand-staff attributes block) and tempo marking differences from source files.
- Extreme ledger lines and stem/tie crowding remain hard to read in OSMD; PNG
  inspection is not a substitute for a pianist reading a printed page.
- Phrase matching is by measure window + after `source_ids`, not by guaranteeing
  identical engraved glyphs to frozen before.
- Held-key reach vs pedal still unmodeled beyond release hypotheses.
- Pianist phrase review and annotated holdouts still outstanding.
- Do not claim perfect hands from Autumn Walks alone.

## Reproduce

```bash
cd audio2score-week4/backend
.venv/bin/python -m evaluation.hands_rhythm_metrics --write-baseline
.venv/bin/python -m pytest tests/test_performance_score.py tests/test_score_interpretation.py \
  tests/test_hands_rhythm_metrics.py tests/test_hand_separator.py -q
.venv/bin/python -m pytest -m 'not integration and not pm2s' -q
# matched phrase OSMD (requires Playwright Chromium):
# node evaluation/render_osmd.mjs .tmp/autumn-walks-review/phrase_renders_matched/after_mm5-8.musicxml \
#   .tmp/autumn-walks-review/phrase_renders_matched/after_mm5-8
```
