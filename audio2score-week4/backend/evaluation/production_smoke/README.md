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
for musician review.
