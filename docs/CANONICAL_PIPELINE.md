# Canonical pipeline — checkpoint 2

This is the implementation map after `docs/CORE_ENGINE_AUDIT.md`. Legacy `BasicPitchEngine` is kept as fallback and benchmark baseline. New musical logic goes only through the canonical path.

## Target flow

```
Audio
 → normalize / analyze
 → transcribe                    → TranscriptionResult
 → RawPerformance
 → confidence-aware cleanup
 → tempo + beat analysis
 → MusicalStructure              (meter, key, hands, voices, roles, phrases)
 → NotationPlan                  (measures, staves, voices, durations, rests, ties)
 → MusicXML                      (music21 export, not inference)
```

## Public types (evolve CMR, do not break callers)

| Type | Module | Role |
|---|---|---|
| `NoteEvent` | `mir/types.py` | Raw note in seconds (extended with id + original times) |
| `MusicalEvent` | `mir/types.py` | Beat-space event (extended with provenance, confidences, role) |
| `TranscriptionResult` | `mir/models.py` | Adapter output |
| `RawPerformance` | `mir/models.py` | Acoustic performance |
| `MusicalStructure` | `mir/models.py` | Explicit musical decisions |
| `NotationPlan` | `mir/models.py` | Readable score plan |
| `PipelineDebug` | `mir/debug.py` | Per-job inspectable trace |

## Files to change

### New

- `audio2score-week4/backend/mir/models.py`
- `audio2score-week4/backend/mir/debug.py`
- `audio2score-week4/backend/mir/meter.py`
- `audio2score-week4/backend/mir/quantizer.py`
- `audio2score-week4/backend/notation_engine/plan.py`
- `audio2score-week4/backend/tests/test_hand_separator.py`
- `audio2score-week4/backend/tests/test_voice_separator.py`
- `audio2score-week4/backend/tests/test_voice_preservation.py`
- `audio2score-week4/backend/tests/test_notation_plan.py`
- `audio2score-week4/backend/tests/test_midi_cleaner_confidence.py`
- `audio2score-week4/backend/tests/test_meter_quantizer.py`
- `audio2score-week4/backend/tests/test_canonical_models.py`
- `audio2score-week4/backend/benchmark/suite.py`
- `audio2score-week4/backend/benchmark/cases.py`
- `audio2score-week4/backend/benchmark/run_suite.py`
- `backend/benchmark/README.md` (pointer + runner into the live package)

### Rewrite in place (keep class names)

- `mir/hand_separator.py` — Viterbi; middle C is a weak prior only
- `mir/voice_separator.py` — continuity; chords stay one voice
- `mir/midi_cleaner.py` — KEEP/SUPPRESS/UNCERTAIN + reasons; `clean()` API kept
- `notation_engine/writer.py` — write from NotationPlan; Staff → Voice → events
- `mir/pipeline.py` — canonical stages + debug JSON; still named `UnderstandingPipeline`
- `adapters/basic_pitch_backend.py` — keep amplitude as confidence
- `mir/cmr_builder.py` — role as hint, not hand; preserve ids/times
- `mir/dynamics.py`, `articulation.py`, `phrase_detector.py` — `dataclasses.replace` so new fields survive
- `transcription.py` — Fast/Quality both feed understanding; health default fix
- `main.py` — health pipeline default matches `get_engine`

### Do not delete (baseline / stubs)

- `transcription.BasicPitchEngine` (fallback + benchmark)
- `adapters/mt3_backend.py`, `adapters/classical_dsp_backend.py`
- root `backend/engines/*`, `backend/workers/*`

## Solo vs Polyphonic

Both call the same `UnderstandingPipeline`.

- Solo: `TRANSCRIPTION_BACKEND=basic_pitch`
- Polyphonic: `MT3Backend` via `MT3_ENDPOINT` (YourMT3 / mt3-infer 0.2.0)

## Checkpoint order

1. Audit (this + `CORE_ENGINE_AUDIT.md`) — done as docs
2. Architecture map — this file
3. Hand separation + tests
4. Voice preservation through the writer
5. Meter-aware quantization
6. Notation planning
7. Benchmark suite
