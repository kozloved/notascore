# Next-gen live cutover checklist

Manual production smoke **after** this reliability pass. Default remains
`NEXTGEN_PIPELINE_MODE=legacy`. Do not flip the default until these checks
pass on a staging worker.

## Environment

```text
NEXTGEN_PIPELINE_MODE=live
NEXTGEN_SEPARATION_ENABLED=1
NEXTGEN_SEPARATION_BACKEND=http
SEPARATION_ENDPOINT=...
NEXTGEN_STEM_TRANSCRIPTION_ENABLED=1
NEXTGEN_FUSION_ENABLED=1
NEXTGEN_ENSEMBLE_RENDER=0
```

Keep `NEXTGEN_ENSEMBLE_RENDER=0`. Do not enable Transkun, Beat This!, or
in-process RoFormer for this cutover.

## Smoke tests

For each case below, inspect MusicXML, `raw.mid`, `score.mid`, `fused.mid`,
provenance, manifest, tempo JSON, and stems / per-stem MIDI when enabled.

Hard check: **SHA256(`raw.mid`) must be unchanged** from the original full-mix
transcription bytes. `format=midi` is that raw file. `format=midi_score` is
notation MIDI. `format=fused_midi` is derived.

1. Solo piano
2. Solo non-piano
3. Full song with piano + bass + drums
4. Separator unavailable
5. One stem transcription failure
6. Rubato recording
7. Repeated same-pitch notes
8. Sustained note across a barline

## Request counts (polyphonic / FULL_SONG)

| Mode | MT3 | warmup | BeatTracker | separator |
|---|---|---|---|---|
| live | 1 | 0 | 1 | ≤ 1 |
| shadow | 1 | 0 | 1 | 0 |
| legacy | 1 | 0 | 1 | 0 |

Polyphonic MT3 failure must fail the job (never silently become Basic Pitch
on the mix). Separation or a single stem failure must not destroy a valid
MT3 result.

## Artifact API

- `GET /jobs/{id}/artifacts` lists from `{job}.manifest.json` via storage
  (local or Supabase). Older jobs without a manifest still probe known keys.
- `GET /jobs/{id}/artifacts/{filename}` only serves files in this job's
  namespace (manifest membership or `{job}.` prefix). Path traversal must 404.
- Do not assume result keys exist on the API server filesystem.

## Go / no-go

Live is safe for a **manual** smoke test when: MIDI CI, structure suite, and
score A/B are green; the HTTP separator contract test executes; remote
artifact list/download works; raw SHA identity holds; default mode is still
`legacy`.
