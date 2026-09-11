# Production smoke fixtures

Local, untracked audio used by `deploy/run-production-smoke-matrix.sh`.

Do **not** commit copyrighted commercial recordings. Keep fixtures on the
VPS or a workstation; this directory is gitignored except README and
`.gitignore`.

## Expected filenames

| File | Smoke mode |
|---|---|
| `solo-piano.wav` | solo |
| `solo-violin.wav` | solo |
| `polyphonic-piano.wav` | polyphonic |
| `full-song.wav` | polyphonic |
| `rubato-piano.wav` | polyphonic |
| `short-rests.wav` | polyphonic |
| `barline-sustain.wav` | polyphonic |
| `repeated-notes.wav` | polyphonic |

Missing files are `SKIP`, not failure.

Place files here, or set `FIXTURE_DIR` when running the matrix.

```bash
cd audio2score-week4
BASE_URL=https://notascore.com/api \
./deploy/run-production-smoke-matrix.sh
```

A single case:

```bash
BASE_URL=https://notascore.com/api \
MODE=polyphonic \
CASE=full-song \
./deploy/smoke-nextgen-live.sh ./full-song.wav
```

The matrix proves infrastructure, routing, raw MIDI identity, and artifact
retrieval. It does **not** score notation quality. Use
[`docs/PRODUCTION_SCORE_QA.md`](../../../../docs/PRODUCTION_SCORE_QA.md)
for musician review and
[`docs/MUSICAL_INTERPRETATION.md`](../../../../docs/MUSICAL_INTERPRETATION.md)
for tempo/meter candidate diagnostics.

## Interpretation categories

`cases.json` lists local fixture names and optional annotations:

```text
01-simple-piano
02-rubato-piano
03-waltz-3-4
04-compound-6-8
05-triplets
06-syncopation
07-pickup
08-pedal-legato
09-two-voice-piano
10-repeated-notes
```

Missing files are `SKIP`. Never commit copyrighted audio. Place wav/midi
files here (gitignored) or set `--fixtures` when running:

```bash
cd audio2score-week4/backend
python -m evaluation.score_diagnostics --fixtures evaluation/production_smoke --out evaluation/results
```

Each processed MIDI case writes `evaluation/results/<case>/` with
`score_metrics.json` and copied artifacts. Audio cases still go through the
deployed backend (`./deploy/run-production-smoke-matrix.sh`); this CLI will
SKIP them rather than inventing a transcription.

Production OSMD options used by the frontend live in
`backend/evaluation/osmd_config.json`. Render a MusicXML file with:

```bash
node evaluation/render_osmd.mjs path/to/score.musicxml evaluation/results/preview
```

That writes `osmd_preview.html` always. SVG/PNG snapshots require Playwright.
