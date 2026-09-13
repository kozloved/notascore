# Hands and rhythm Phase 3 review (2026-09-13)

Phase 3 plan deliverables are complete: frozen metrics harness, synthetic corpus,
comparable Autumn Walks before/after (identical MIDI + audio beat map + 3/4), and
recorded deltas. This does **not** claim perfect hand separation from one song.

Gap closures required for an honest comparable review (landed with this Phase 3
completion commit):

1. **Per-hand silence decay** — each hand’s anchors/sticky costs use its own activity timestamps.
2. **Stamped layout authority** — quantization keeps `LayoutResult`; no label-only rebuild.
3. **Meter-aware release scoring** — barline fragments, ties, and tiny pieces use real meter.
4. **Line/release hypotheses** — pedal tails capped for voice search only; holds/repeats preserved.

## Harness

```bash
cd audio2score-week4/backend
.venv/bin/python -m evaluation.hands_rhythm_metrics --write-baseline
```

- Script: `evaluation/hands_rhythm_metrics.py` (`replay_autumn_walks_aligned`)
- Baseline: `evaluation/baselines/hands_rhythm_phase3.json`
- Private fixtures stay under `.tmp/autumn-walks-review/` (not committed)

## Synthetic corpus (git-safe)

| Case | Checks |
| --- | --- |
| `pedal_quarters` | One voice; written quarters; raw durations unchanged |
| `broken_chord_waltz` | Bass/mid under melody preserved |
| `near_boundary_releases` | 0.94→1, 1.17→1, 1.94→2, 2.21→2 |
| `independent_rh_voices` | Two overlapping RH lines stay distinct |

## Autumn Walks — comparable before/after

Controls: same `mt3-original.mid` (SHA matches alignment), `detected-beats.json`, forced `3/4`.

| Metric | `current-main.musicxml` | Aligned after | Δ |
| --- | ---: | ---: | ---: |
| Pitched symbols | 155 | 120 | −35 |
| Tie starts | 110 | 40 | −70 |
| Tiny (32nd+) | 37 | 5 | −32 |
| Time modifications | 20 | 2 | −18 |
| Max voices / measure·staff | 3 | 3 | 0 |
| Source attacks | 100 | 100 | 0 |
| Source identity preserved | — | true | — |

### Voice-count note

An earlier MIDI-only replay without the frozen beat map chose 6/8 and reported max
voices 4. Comparable 3/4 replay keeps max voices at **3**. Local after score:
`.tmp/autumn-walks-review/bp_hands_rhythm_aligned/hands_rhythm_aligned.musicxml`

## Regressions

- `test_one_hand_rest_decays_independently_while_other_continues`
- `test_stamped_layout_authority_survives_quantization`
- `test_release_scoring_uses_meter_barlines_not_unit_pulse`
- `test_overlapping_repeated_pitch_is_not_clipped_for_voice_search`
- `test_genuine_multi_attack_hold_is_not_clipped_for_voice_search`

Focused hands/performance/downbeat/metrics suite: **passed**.

## Remaining limitations (future work, not Phase 3 blockers)

- Held-key reach vs pedal resonance still unmodeled.
- Line/release search is bounded, not a full joint optimizer.
- Autumn Walks is one unlabeled development excerpt; pianist phrase review and
  annotated multi-song holdout gates are still desirable before broad claims.
- Plan-level `voices_max_per_staff` counts lanes over the piece, not simultaneous XML voices.
