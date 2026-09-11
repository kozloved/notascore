# Musical-time integration

Checkpoint after PR #49. Timing abstractions already exist; they were unused by
`UnderstandingPipeline`. This document is the map for making them authoritative.

## PR #48

`kozloved/notascore#48` (`cursor/respect-pipeline-layout-2317`) is **redundant**.
The same layout-respect change landed on `main` as `cafa6cd` inside PR #49.
Do not merge or re-apply #48; it now conflicts with `main`.

## Current timing path (before this checkpoint)

```text
audio → AudioNormalizer
     → BeatTracker.track_stable()     # madmom/librosa, THEN stabilize_tempo_map
     → mir.types.TempoMap             # collapsed BPM regions
     → cmr_builder.notes_to_events
           start_beat = TempoMap.seconds_to_beats(t)
           ≈ piecewise (dt * bpm / 60) on stabilized regions
     → meter / hands / voices / performance_score
```

Prefetch in `_prefetch_cpu` already runs the tracker once; `_build_tempo_map`
reuses `_prefetched_tempo`. Good.

What was wrong: `stabilize_tempo_map` is a **printed-tempo** smoother. Using it
as the seconds→beats map turns rubato into a near-constant BPM, so performed
quarters become messy written values.

`timing.MusicalTimeMap` existed but production never passed it to
`notes_to_events`. The orchestrator MIDI path built one and did not feed the
quantizer.

## Authoritative path (this checkpoint)

```text
RawPerformance / PerformanceSnapshot     # seconds immutable
        │
        ▼
BeatTracker.track() once (prefetch)
        │
        ├── last_beat_times / madmom beat_times   → MusicalTimeMap   (performance)
        └── stabilize_tempo_map(TempoMap)         → display / printed / score MIDI
        │
        ▼
notes_to_events(..., time_map)
        start = time_map.seconds_to_beats(start_sec)
        end   = time_map.seconds_to_beats(end_sec)
        duration_beats = end - start          # NOT duration_sec * bpm / 60
        │
        ▼
meter arbitrator (beat grouping + downbeats + onsets)
        │
        ▼
performance_score / NotationPlan
```

`MusicalTimeMap` is **not** a quantizer. `18.351 s → 23.47 beats` is valid.
Rounding to a written grid happens only in the notation engine.

## Files

| File | Change |
|---|---|
| `timing/tempo_map.py` | Sanitize beat times; NaN/inf guards; `from_beat_times` |
| `timing/metrics.py` | Timing quality summary |
| `timing/service.py` | Single resolver used by the pipeline |
| `timing/existing_tracker.py` | `analyze_from_tracker` (no second tracker run) |
| `audio_engine/beat_tracker.py` | Keep librosa `last_beat_times` |
| `mir/cmr_builder.py` | Duck-type any `seconds_to_beats` mapper |
| `mir/pipeline.py` | Audio + MIDI consume `TimingResolution` |
| `docs/MODEL_LICENSES.md` | Beat This! still disabled |

Live jobs remain `tasks.process_job` → `transcription.get_engine()` →
`UnderstandingPipeline`. No orchestrator cutover.

## Fallback

```text
valid MusicalTimeMap from ≥2 increasing beat timestamps
    ↓
sample MusicalTimeMap.from_tempo_map (existing TempoMap, including MIDI file tempi)
    ↓
constant_bpm 120 last resort
```

Always record `timing_fallback_used`, `timing_backend_requested`,
`timing_backend_used`, `failure_reason`. Transcription does not fail.

## Quality gates

- Round-trip `t ≈ beats_to_seconds(seconds_to_beats(t))` within `1e-4` s
- Rubato / rit / accel / triplet / local-delay fixtures
- One production-path fixture where constant BPM mis-notates and the beat map
  recovers quarters
- Existing MIDI CI 21/21, structure suite, score A/B, raw MIDI SHA unchanged
