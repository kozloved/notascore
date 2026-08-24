# NotaScore benchmark suite

The live Python package is `audio2score-week4/backend/benchmark/`.

This directory exists so the product architecture (`backend/benchmark/`) has a
stable entry point. Cases currently include synthetic MIDI-like events with
reference hand / voice / meter labels. Real audio + reference MIDI/MusicXML
corpora should be added here as files:

```
cases/<name>/
  audio.wav
  reference.mid
  reference.musicxml   # optional
  metadata.json
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
