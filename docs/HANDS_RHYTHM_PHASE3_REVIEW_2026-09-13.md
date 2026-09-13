# Hands and rhythm Phase 3 review (2026-09-13)

Phases 1–2 landed as separate commits on main (`e270d7c`, `0c75c61`). This Phase 3 commit freezes
metrics and records the local Autumn Walks replay without claiming perfect hands from one song.

## Harness

```bash
cd audio2score-week4/backend
.venv/bin/python -m evaluation.hands_rhythm_metrics --write-baseline
```

- Script: `evaluation/hands_rhythm_metrics.py`
- Frozen baseline: `evaluation/baselines/hands_rhythm_phase3.json` (synthetic corpus always)
- Latest run (gitignored under `evaluation/results/`): `hands_rhythm/latest.json`
- Private Autumn Walks audio/MIDI stay under `.tmp/autumn-walks-review/` and are not committed

## Synthetic corpus (git-safe)

| Case | Attacks | Notes |
| --- | --- | --- |
| `pedal_quarters` | 4 | Pedal tails write as quarters; raw durations unchanged; one voice |
| `broken_chord_waltz` | 16 | Bass/mid under melody; Phase 1 anchors preserved |
| `near_boundary_releases` | 4 | 0.94→1, 1.17→1, 1.94→2, 2.21→2 |
| `independent_rh_voices` | 8 | Two overlapping RH lines stay distinct voices |

All synthetic cases report `source_identity_preserved: true` and unchanged performed onsets/releases.

## Autumn Walks (local optional)

Source identity from the handoff: 100 MT3 attacks, raw SHA-256
`aae968993fe7aa03dd21d3ba77e2aa8cc143cd585b6d6b0e257f6d2156cf7cca`.

| Metric | `current-main.musicxml` (before) | MIDI-only after Phase 1–2 | Δ |
| --- | ---: | ---: | ---: |
| Pitched symbols | 155 | 143 | −12 |
| Tie starts | 110 | 86 | −24 |
| Tiny (32nd+) | 37 | 18 | −19 |
| Time modifications | 20 | 11 | −9 |
| Max voices / measure·staff | 3 | 4 | +1 |

Caveats:

- After metrics are a **MIDI-only** `UnderstandingPipeline` replay. Without the original audio
  beat map the meter can differ (this run chose 6/8 vs the handoff’s audio-aligned 3/4).
- Treat deltas as a development signal, not a production QA gate.
- Do not claim perfect hand separation from this single excerpt.

## Remaining uncertain cases

- Held-key reach vs pedal resonance still undocumented in Phase 1 state.
- MIDI-only Autumn Walks meter/phase drift vs audio-aligned scores.
- Occasional increase in simultaneous written voices when tails simplify onto more independent lines.
- Annotated multi-song hand accuracy and holdout pianist review are still outstanding.

## Release posture

Focused Phase 1/2 tests remain green. No middle-C gate, no hand re-inference at export, no
dropped source attacks, and no stripping of necessary barline ties.
