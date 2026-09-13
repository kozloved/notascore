# Hands and rhythm review update (after ec1324a)

Built on `ec1324a` (accepted pedal releases authoritative over same-voice
neighbors). This follow-up strengthens **export validation** and refreshes Autumn
Walks metrics/renders. Release-target / duration behavior from `ec1324a` is
unchanged.

**Visual review is not marked complete** — matched phrase MusicXML was refreshed;
OSMD PNGs depend on local Playwright Chromium.

## A. Validation fixes (not engine changes)

1. **`score_attacks` / `_musicxml_attack_spans`** — tie chains keyed by
   `(part, staff, voice, pitch)`; chord members tracked individually; independent
   unisons retained; timing continuity required; orphan continue/stop, gaps, and
   unfinished starts raise.
2. **`_assert_exported_attacks`** — exact attack multiplicity + total written
   duration (no silent summing of untied same-pitch fragments).
3. **Fixtures** — tied C with interleaved E; simultaneous tied voices; chord ties;
   repeated same-pitch reattacks + unison; orphan / unfinished / non-contiguous
   chains.

## B. Engine observations (not “fixed” by truncating holds)

**Four-voice hotspot (aligned Autumn Walks, measure 4 / staff 0 / RIGHT):**

| note_id | pitch | start | dur | voice |
| --- | ---: | ---: | ---: | ---: |
| track:0:note:18 | 80 | 12.00 | 0.375 | 0 |
| track:0:note:19 | 82 | 12.25 | 0.25 | 1 |
| track:0:note:20 | 80 | 12.50 | 0.75 | 2 |
| track:0:note:24 | 77 | 13.08 | 1.0 | 3 |
| track:0:note:28 | 75 | 14.125 | 0.75 | 2 |

Overlaps are pairwise (18∩19, 20∩24); peak concurrency is **2**, but the measure
uses **four distinct voice IDs**. That inflates `max_voices_in_measure_staff`
versus simultaneous sounding voices. Do **not** reduce this by shortening
legitimate overlapping holds — lane compaction / voice reuse is a separate
layout concern.

Hotspot rows in metrics now include `source_notes` context for inspection.

## Tests

- Supported backend suite: `pytest -m 'not integration and not pm2s'` →
  **752 passed, 4 deselected**

## Comparable Autumn Walks metrics (MT3 semantics)

| Metric | `current-main.musicxml` | Aligned after | Δ |
| --- | ---: | ---: | ---: |
| Pitched symbols | 155 | 120 | −35 |
| Tie starts (once each) | 55 | 20 | −35 |
| Tiny (32nd+) | 37 | 5 | −32 |
| Time modifications | 20 | 2 | −18 |
| Max voices / measure·staff | 3 | 4 | +1 |
| Source attacks | 100 | 100 | 0 |

Matched phrases: `.tmp/autumn-walks-review/phrase_renders_matched/` with
`force_fifths=-5`, source-ID manifests (mm1–4 / mm5–8 / mm13–16).

## Remaining limitations

- Voice-ID compaction inside a measure (hotspot above) still open.
- OSMD PNG refresh requires Playwright browsers on the machine.
- Pianist phrase review still outstanding.
- Do not claim perfect hands from Autumn Walks alone.

## Reproduce

```bash
cd audio2score-week4/backend
.venv/bin/python -m evaluation.hands_rhythm_metrics --write-baseline
.venv/bin/python -m pytest -m 'not integration and not pm2s' -q
```
