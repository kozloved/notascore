# Performance foundation: implementation and release gates

This increment extends the performance engine present in main at `3096320`.
It does not claim to complete the entire audio-to-score rebuild. It establishes
source preservation, an instrument-aware solo score path, and separate quality
gates before model replacement or ensemble development.

## What now flows through the engine

1. Retain the original MIDI bytes returned by MT3 or supplied by the customer.
2. Capture a frozen `PerformanceSnapshot`: stable note IDs, seconds, velocities,
   instrument streams/programs, controller events, pitch bends, tempo/meter
   changes, and SHA-256 of the original MIDI. Drum notes remain in this snapshot.
3. Create mutable `NoteEvent` / `MusicalEvent` copies for interpretation, carrying
   source note ID, instrument stream ID, and GM program. Do not lengthen short
   source notes at the ingest/CMR boundary.
4. Resolve a solo score profile. Piano uses hands and a grand staff. Other GM
   instruments use one staff and no piano hand assignment. Voice/rhythm search
   feeds the existing exact rational notation planner.
5. Export MusicXML and score MIDI separately. Preserve the original performance
   independently and write a versioned `.performance.json` analysis artifact.

The production MT3 `.raw.mid` is now the exact response bytes, rather than a
piano reconstruction of its notes. When validation leaves notes unchanged,
`.validated.mid` also retains those bytes. If a cleaner changes notes, its
derived MIDI keeps program/stream grouping, but does not yet restore every
controller or arbitrary source meta event. Original bytes remain available.
This change cannot recover information from older reconstructed raw downloads.

Snapshots are immutable through their factory/JSON load path; legacy
`RawPerformance` and event classes remain mutable compatibility interfaces.
The JSON is not a lossless MIDI encoding. Track IDs identify PrettyMIDI
instrument streams, not original SMF track chunks. IDs are scoped to one
performance; the source checksum identifies the file. Encoded GM programs are
evidence, not proof that MT3 identified the acoustic instrument correctly.
MIDI note confidence 1.0 means the encoded event was read, not acoustic certainty.

## Run without audio models

From `audio2score-week4/backend`:

```sh
python -m pip install -r requirements-score.txt
python -m mir.performance_cli input.mid output.musicxml --meter 4/4
python -m pytest -q tests/test_performance_foundation.py \
  tests/test_performance_score.py tests/test_performance_cli.py \
  tests/test_quantizer_identity.py tests/test_score_ab.py
```

Basic Pitch is imported only when actually transcribing audio. The existing
Basic Pitch dependency remains required for that audio route.

The CLI produces `output.musicxml`, `output.score.mid`,
`output.decisions.json`, and `output.performance.json`. It rejects output paths
that would overwrite the source through either the score or a sidecar.

## Separate measurable stages

```sh
# Score reference: independently specified quantized/written rhythms.
python -m evaluation.stage_gate score input.mid reference.mid --out /tmp/score-gate

# Audio reference: independently annotated performed note timings.
# mt3.raw.mid must be the unmodified output of the audio model being evaluated.
python -m evaluation.stage_gate transcription mt3.raw.mid performed-reference.mid \
  --out /tmp/transcription-gate
```

Both commands write `result.json` and exit nonzero on failure. They do not fit
tempo/offset to the answer or invoke an audio model. Initial configurable
engineering targets are onset/pitch F1 >= 0.98 and onset/pitch/offset F1 >= 0.95,
using the existing 50 ms onset / 100 ms offset tolerances. These are targets,
not claims of achieved product quality. Score checks also require note identity,
valid planned timelines, no fallback, exact exported note timing relative to
the selected interpretation, and unchanged source/reference bytes.

Transcription evaluates per-program metrics in addition to overall pitches;
correct notes attributed to the wrong instrument cannot pass. It currently
evaluates pitched notes and reports excluded drum counts. Program-separated
metrics do not establish voice identity or separate same-program instruments.

The lightweight CI job runs seven generated acceptance scenarios: flute with
short rests, cello sustain across bars, piano bass/melody polyphony, repeated
same-pitch overlap input, flute triplets, compound-meter piano, and violin chord
input. Additional tests cover snapshot round trips, sub-10 ms ingestion,
controllers/bends/drums, byte preservation, source/output collisions, solo
pipeline routing, and negative quality-gate cases. These are synthetic
engineering fixtures, not musician-reviewed recordings or engraving ratings.

## Measured status and next work

The pre-existing A/B corpus still reports 1.000 onset/pitch and offset F1 for
both engines on 21 synthetic pairs, and 1.000 export fidelity on all 24 pairs.
The three development pairs still produce:

| Case | Adaptive onset F1 | Performance onset F1 | Adaptive offset F1 | Performance offset F1 |
|---|---:|---:|---:|---:|
| Case1 | 1.000 | 0.857 | 0.571 | 0.857 |
| Case2 | 1.000 | 0.929 | 0.071 | 0.786 |
| Case3 | 1.000 | 1.000 | 1.000 | 1.000 |

The first two development cases do not meet the new quality targets. Their
provenance does not establish real MT3/musician ground truth. No thresholds
were relaxed and no rhythm weights were tuned to hide these failures.

| Requested stage | Status in this increment | Remaining gate |
|---|---|---|
| Shared notes and original transcription | Implemented at MIDI/MT3 boundaries and carried to score decisions | Extend confidence/evidence from future acoustic adapters |
| MIDI-only interpretation and score | Existing engine extended, tested, and given an independent gate | Competing meter/voice/hand hypotheses; fix development onset regressions |
| Reliable solo piano/instrument output | Synthetic acceptance cases pass | Independently annotated hands/voices, expressive real recordings, musician review, rendered score QA |
| Benchmark/improve audio separately | Offline raw-transcription gate implemented; original MT3 output retained | Run real audio/reference corpus, compare candidate models and measured latency/cost |
| Expand to ensembles after quality | Explicitly deferred; mixed programs fail clearly in performance mode | Passing solo gates, per-part/instrument/voice truth, same-instrument mixtures and cross-part engraving |

Performance mode rejects mixed GM programs and multiple non-piano streams
instead of silently collapsing them to piano. Piano streams are combined for
RH/LH compatibility; multiple same-program pianos remain ambiguous. Unknown
events without programs retain the historical piano assumption and report it.
Changing meter is rejected by the MIDI CLI/upload path; the snapshot retains
all changes for future support. Meter changes, pickups, ornaments, arbitrary
tuplets, pedal-aware duration inference, concert/written-pitch conventions,
and joint hand/voice/rhythm inference remain future work.

No production deployment or GPU inference is part of these offline checks.
Do not merge this change as evidence that ensembles or general recording
quality are solved. Review the deliberate mixed-program behavior change.
