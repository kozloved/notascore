# NotaScore benchmark suite

The live Python package is `audio2score-week4/backend/benchmark/`.

This directory exists so the product architecture (`backend/benchmark/`) has a
stable entry point. Cases currently include synthetic MIDI-like events with
reference hand / voice / meter labels.

Real recordings must not be committed. Use the manifest-driven local evaluator
in `audio2score-week4/backend/benchmark/realworld/README.md`:

```
cd audio2score-week4/backend
./.venv/bin/python -m benchmark.realworld.runner --prepare-smoke
```

Run from the week-4 backend:

```bash
cd audio2score-week4/backend
./.venv/bin/python -m benchmark.run_suite
./.venv/bin/python -m benchmark.run_pipeline_benchmark
```

Metrics:

- transcription: pitch/onset P/R (existing `metrics.py`)
- musical structure: hand accuracy, voice count, meter
- notation: measure sums, voice preservation
