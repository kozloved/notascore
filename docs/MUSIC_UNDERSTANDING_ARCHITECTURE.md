# Music Understanding Engine — Architecture Report

See the approved migration plan for module order, metrics, and safety constraints.

## Current pipeline (legacy)

```
Audio upload → Basic Pitch → librosa tempo + refine → pretty_midi → music21 quantize → MusicXML
```

Live code: `audio2score-week4/backend/transcription.py`

## Target pipeline

```
Audio → Audio Intelligence → Transcription Backends → MIDICleaner → CMR → MIDI Intelligence → Notation → MusicXML
MIDI file ────────────────────────────────────────────────┘
```

## Package layout

```
audio2score-week4/backend/
  audio_engine/       # Audio Intelligence Layer
  mir/                # Common Musical Representation + MIDI Intelligence
  notation_engine/    # MusicXML from MusicalEvent[]
  adapters/           # Basic Pitch, MT3 (Quality), classical DSP
  transcription.py    # Facade: legacy | understanding pipeline
  benchmark/          # Metrics, fixtures, before/after harness
```

## Convergence contract

All backends emit `MusicalEvent[]` + `TempoMap` + `ScoreMeta`. Notation never imports Basic Pitch or MT3.

## Feature flags

| Variable | Values | Default |
|----------|--------|---------|
| `TRANSCRIPTION_PIPELINE` | `legacy` \| `understanding` | `understanding` |
| `TRANSCRIPTION_PIPELINE_FALLBACK` | `0` \| `1` | `1` |
| `TRANSCRIPTION_BACKEND` | `basic_pitch` \| `classical_dsp` \| `mt3` | `basic_pitch` (Fast default) |
| `MT3_ENDPOINT` | URL | empty — Quality HTTP worker (`POST` audio → MIDI) |
| `MT3_API_KEY` | string | empty — optional Bearer / X-API-Key |
| `MT3_TRANSCRIBE_COMMAND` | command with `{input}` `{output}` | empty — Quality CLI that writes MIDI |
| `MT3_TIMEOUT_SECONDS` | int | `300` |
| `TRANSCRIPTION_USE_CLEANER` | `0` \| `1` | `0` |
| `TRANSCRIPTION_SHADOW_CLEANER` | `0` \| `1` | `0` |
| `TRANSCRIPTION_USE_NORMALIZER` | `0` \| `1` | `1` |
| `TRANSCRIPTION_USE_BEAT_TRACKER` | `0` \| `1` | `1` |
| `TRANSCRIPTION_USE_PIANO_ANALYZER` | `0` \| `1` | `1` |
| `TRANSCRIPTION_USE_MIR_LAYERS` | `0` \| `1` | `1` |

## Phase 2 — Enhanced legacy path (implemented)

Production stays on `TRANSCRIPTION_PIPELINE=legacy` while audio intelligence modules
run **before and after** Basic Pitch:

```
Audio → Normalizer → Basic Pitch → MIDICleaner → PianoAnalyzer (if piano)
     → BeatTracker seed + onset refine → quantize → MusicXML
```

**Why this order:** normalization stabilizes Basic Pitch input; cleaner removes
micro-notes; beat tracker improves tempo seed for quantization; piano analyzer
refines dynamics from onset strength.

**Rollout:** flags default to `1`. Disable individually for A/B (`TRANSCRIPTION_USE_*=0`).

**Next (Phase 3):** promote `TRANSCRIPTION_PIPELINE=understanding` when benchmark
F1 ≥ 0.85 vs enhanced legacy and OSMD readability passes.

## Phase 3 — Understanding pipeline (implemented)

Default pipeline is now **`understanding`** with **`TRANSCRIPTION_PIPELINE_FALLBACK=1`**
so production jobs fall back to enhanced legacy if the full MIR path fails.

```
Audio → Normalizer → Classifier → Basic Pitch → MIDICleaner → PianoAnalyzer
     → BeatTracker TempoMap → CMR → Hand/Voice/Dynamics/Articulation/Phrases
     → Notation → MusicXML + DAW MIDI (tempo track) + score MIDI
```

**Validate before/after deploy:**

```bash
cd audio2score-week4/backend
./.venv/bin/python -m benchmark.run_pipeline_benchmark
./.venv/bin/python -m pytest tests/test_understanding_pipeline.py -q
```

**Rollback:** set `TRANSCRIPTION_PIPELINE=legacy` and restart worker.

## Phase 4 — Tempo map (implemented)

Understanding jobs no longer collapse BeatTracker to a single BPM. The pipeline:

1. Tracks beats, then **stabilizes** per-beat jitter into regions (≈8% change held ≥2s).
2. Scales the whole map so time 0 matches onset-refined global tempo.
3. Converts notes → CMR beats with `TempoMap.seconds_to_beats`.
4. Writes DAW MIDI in **original seconds** plus a tempo track.
5. Inserts extra metronome marks on the score when tempo actually changes.

## Phase 5 — Score writing (implemented)

Notation builds a **piano grand staff** from CMR events instead of a MIDI round-trip:

- RH treble + LH bass, braced together, barlines aligned
- Same-attack notes become chords; held overlaps become extra voices
- Events snap to a 16th / triplet grid; rests fill empty beats and measures
- Time signature defaults to 4/4 unless another meter is clearly better
- Quantized score MIDI is written from that score (DAW MIDI is unchanged)

## Phase 6 — Piano / guitar classifier (implemented)

Instrument classification no longer treats a plain sine as voice or guitar.

- Simple stable tones → `unknown` (piano analysis still runs)
- Polyphonic decaying chords with bass energy → piano
- Bright, fast-decaying plucked clips → guitar, only with a clear margin
- Vibrato + monophonic harmonic tone → voice; noise bursts → drums
- Close piano vs guitar scores keep piano (Fast mode default)

## Phase 7 — MIDI-file ingest (implemented)

Uploaded `.mid` / `.midi` files join at CMR (no Basic Pitch):

- Notes, tempo map, time signature, and sustain CC64 come from the file
- RH/LH track names are kept; otherwise HandSeparator splits the piano
- Drum tracks are skipped
- The original file is the raw DAW MIDI download; score MIDI / MusicXML use the grand-staff writer

## Phase 8 — Quality / MT3 (implemented)

Per-job **Fast** vs **Quality**. Notation, cleaner, tempo map, and grand staff stay the same; only the note detector changes.

| Mode | Detector | Fallback |
|------|----------|----------|
| Fast (default) | Basic Pitch on CPU | understanding → enhanced legacy |
| Quality | MR-MT3 via `MT3_ENDPOINT` or `MT3_TRANSCRIBE_COMMAND` | **none** — never substitutes Basic Pitch |
| MIDI upload | file ingest at CMR | mode is ignored |

Quality is available when `MT3_ENDPOINT` or `MT3_TRANSCRIBE_COMMAND` is set. The GPU worker contract:

```
POST {MT3_ENDPOINT}
  multipart field `file` = audio
  optional Authorization: Bearer {MT3_API_KEY}
200 audio/midi            (MIDI bytes)
or 200 application/json   {"midi_base64": "<base64 MIDI>"}
```

`{output}` from `MT3_TRANSCRIBE_COMMAND` must be MIDI, not MusicXML. Dummy local wiring:

```bash
MT3_TRANSCRIBE_COMMAND=python scripts/example_mt3.py {input} {output}
# or
MT3_ENDPOINT=http://127.0.0.1:8090/transcribe
python scripts/example_mt3_http.py
```

Real GPU worker (MR-MT3 via `mt3-infer`): see `audio2score-week4/gpu-worker/README.md`.
An RTX 4000 Ada 20 GB box is enough. Set `MT3_ENDPOINT` to that pod's `/transcribe` URL.

Upload form field `mode=fast|quality`. `/health` exposes `quality.available`.

## How to enable MIDICleaner safely

1. Keep `TRANSCRIPTION_PIPELINE=legacy`.
2. Set `TRANSCRIPTION_SHADOW_CLEANER=1` and restart the worker — logs note-count deltas without changing results.
3. Run synthetic before/after:

```bash
cd audio2score-week4/backend
./.venv/bin/python -m benchmark.run_cleaner_benchmark
./.venv/bin/python -m pytest tests/test_cleaner_before_after.py -q
```

4. When fixtures pass and shadow logs look sane on real uploads, set `TRANSCRIPTION_USE_CLEANER=1`.
5. Only then consider `TRANSCRIPTION_PIPELINE=understanding`.

## Promotion criteria

**MIDICleaner → default on legacy path** when:

- All cleaner fixtures reach F1 ≥ 0.99 vs expected
- Readability score does not decrease on fixtures
- Shadow mode on real piano uploads shows fewer micro-notes / dupes without deleting melodic material

**Understanding pipeline → default** when:

- Cross-pipeline F1 vs legacy ≥ 0.85 on shared fixtures (unless intentionally editorial)
- Reference MIDI F1 (when available) ≥ legacy
- Score readability rubric + OSMD smoke pass

**MT3 / Quality** after CMR + cleaner + tempo map are stable (Phase 8).

## Phase 9 — Gemini music intelligence (optional)

Gemini is **not** a transcription engine. Fast still uses Basic Pitch; Quality still uses MT3. When `ENABLE_GEMINI_MUSIC_ANALYSIS=1` and `GEMINI_API_KEY` is set, the understanding pipeline builds a compact analysis packet (notes, tempo, meter, chords, uncertainties) and asks Gemini for structured JSON corrections. A validator applies only high-confidence, non-destructive patches. If Gemini is down, the job still completes.

**Models (Aug 2026 Developer API pricing):**

| Role | Default ID | Why |
|---|---|---|
| Default | `gemini-2.5-flash-lite` | Cheapest audio+JSON path: $0.10/1M text in, $0.30/1M audio in, $0.40/1M out. Audio ≈ 32 tokens/s. |
| Escalation | `gemini-2.5-flash` | Stronger reasoning on uncertain windows only: $0.30 text / $1.00 audio in, $2.50 out. |
| Optional upgrade | `gemini-3.5-flash-lite` | Same audio input rate as 2.5-lite, but $2.50 out (≈6×). Better JSON, not cheaper. |
| Avoid as default | `gemini-3.6-flash` | Current Google audio-example model; $1.50 / $7.50. |
| Avoid for this job | OpenAI `gpt-4o-mini-audio` | ~$10/1M audio tokens. |

Override with `GEMINI_DEFAULT_MODEL` / `GEMINI_REASONING_MODEL`. Deep escalation stays off until `ENABLE_GEMINI_DEEP_ANALYSIS=1`.

## Quality metrics

- Pitch / onset F-measure (50 ms tolerance)
- Note precision / recall
- Pedal CC IoU (piano)
- Readability: micro-note count, near-duplicate onsets, chord onset spread
- Score readability rubric (OSMD smoke)

## Migration rules

1. Characterization tests before algorithm swaps
2. Shadow mode until metrics beat baseline
3. One module at a time
4. MT3 / Quality after CMR + cleaner + tempo map are stable
