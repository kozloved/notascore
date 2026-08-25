# Real-world evaluation (local audio)

Observational Fast-pipeline evaluation for recordings that must **not** be committed.

This is not a regression gate. Do not add per-song expected F1/meter targets and do not tune the production algorithm against individual files.

## Layout

```
benchmark/realworld/
  manifests/example.json   # template
  manifests/smoke.json     # 3-case framework smoke (paths only)
  local/                   # gitignored WAV / MIDI
```

Put recordings in `local/` (or any directory pointed to by `NOTASCORE_REALWORLD_DIR` / `--local-root`).

Each manifest case may include:

- `audio` (required to run; skipped if missing)
- `reference_performance_midi` (optional; note P/R/F1 + hands)
- `reference_score_midi` (optional; separate F1 vs a notated MIDI)
- `expected_meter` if known (shown for review, not a CI fail)
- `instrumentation` and `notes` for the musician sheet

## Run

From `audio2score-week4/backend`:

```bash
# Prove the harness with three synthetic clips (writes gitignored local files)
python -m benchmark.realworld.runner --prepare-smoke

# Your own corpus
python -m benchmark.realworld.runner \
  --manifest /path/to/manifest.json \
  --local-root ~/notascore-realworld
```

Reports:

- `benchmark/results/realworld/realworld.json`
- `benchmark/results/realworld/realworld.md`
- `benchmark/results/realworld/musician_review.md`
