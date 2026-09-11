# Next-gen live cutover checklist

Next-Gen **live** does not mean all experimental models are enabled.
The first cutover only promotes `PipelineOrchestrator` to the production
job owner. Stem separation, Transkun, Beat This!, RoFormer, fusion, and
ensemble rendering stay off until this path is proven.

The Python fallback remains `NEXTGEN_PIPELINE_MODE=legacy` if the env is
missing. Production becomes live through `.env.production`, not a hard-coded
default.

## First production configuration

```text
NEXTGEN_PIPELINE_MODE=live

NEXTGEN_SEPARATION_ENABLED=0
NEXTGEN_STEM_TRANSCRIPTION_ENABLED=0
NEXTGEN_FUSION_ENABLED=0
NEXTGEN_ENSEMBLE_RENDER=0

NEXTGEN_TRANSKUN=0
NEXTGEN_BEAT_THIS=0
NEXTGEN_WRITE_MANIFEST=1

NEXTGEN_SEPARATION_BACKEND=auto
SEPARATION_ENDPOINT=
```

Leave `SEPARATION_ENDPOINT` blank unless a real separator service exists.

What this runs:

```text
audio
 → current MT3 / Basic Pitch transcription
 → immutable raw transcription
 → Next-Gen PipelineOrchestrator
 → MusicalTimeMap
 → interpretation
 → NotationPlan
 → score MIDI
 → MusicXML
 → artifacts / provenance
```

`format=midi` remains full-mix **raw**. `format=midi_score` is notation MIDI.
`format=fused_midi` is derived and will usually be absent while fusion is off.

## VPS cutover

```bash
cd /root/notascore
git pull origin main

cd audio2score-week4

# Edit .env.production to the first production configuration above.

docker compose --env-file .env.production up -d --build api worker
```

Do not recreate redis/nginx/frontend/tunnel unless those images also changed.

## Verify after deploy

```bash
curl -fsS https://notascore.com/api/health
```

The JSON must include:

```json
"nextgen": {
  "pipeline_mode": "live",
  "orchestrator_active": true,
  "separation_enabled": false,
  "stem_transcription_enabled": false,
  "fusion_enabled": false,
  "ensemble_render_enabled": false
}
```

If health still says `legacy`, the deployment is not complete.

Scripted check:

```bash
BASE_URL=https://notascore.com/api ./deploy/smoke-nextgen-live.sh
# optional real job:
BASE_URL=https://notascore.com/api ./deploy/smoke-nextgen-live.sh ./path/to/clip.wav
```

Worker logs should print once:

```text
NotaScore pipeline configuration:
  nextgen_mode=live
  separation=off
  stem_transcription=off
  fusion=off
  ensemble_render=off
  MT3 configured = true
```

## Production smoke matrix

For each completed job verify `raw.mid`, `score.mid`, MusicXML, manifest,
provenance, and tempo JSON. With federation OFF it is valid that `fused.mid`,
stem WAVs, and per-stem MIDI do **not** exist.

1. Solo piano
2. Solo non-piano (must not become a piano grand staff)
3. Polyphonic piano
4. Full-song MT3 example
5. Rubato audio
6. Short rests
7. Sustained barline-crossing note
8. Repeated same-pitch attacks

Hard checks:

- SHA256 of the raw provider MIDI == SHA256 of `{job}.raw.mid`
- SHA256(`raw.mid`) is unchanged after score generation
- Polyphonic: MT3 = 1, warmup = 0, BeatTracker = 1, separator = 0, stem BP = 0
- `GET /jobs/{id}/artifacts` and downloads work on the active storage backend
  (do not assume local filesystem keys)

## Emergency rollback

One variable. No database rollback, no artifact deletion, no schema change.
Existing live-created jobs remain readable.

```text
NEXTGEN_PIPELINE_MODE=legacy
```

```bash
cd /root/notascore/audio2score-week4
docker compose --env-file .env.production up -d --force-recreate api worker
curl -fsS https://notascore.com/api/health
# nextgen.pipeline_mode must be "legacy"
```

## Stage 2 (do not enable yet)

Only after the core live smoke matrix passes:

```text
NEXTGEN_PIPELINE_MODE=live
NEXTGEN_SEPARATION_ENABLED=1
NEXTGEN_SEPARATION_BACKEND=http
SEPARATION_ENDPOINT=<real service>

NEXTGEN_STEM_TRANSCRIPTION_ENABLED=1
NEXTGEN_FUSION_ENABLED=1

NEXTGEN_ENSEMBLE_RENDER=0
```
