# NotaScore Core Engine Audit

**Date:** 2026-08-24
**Scope:** Production request path, transcription backends, MIR / notation, data model, dead code.
**Rule followed:** inspect first; no deletions; no large rewrite before this document.

Live product code lives in `audio2score-week4/`. The top-level `backend/` tree is a disconnected stub. The top-level `README.md` Fast/Quality (Basic Pitch vs MR-MT3) story is **not** what the running API does.

---

## 1. Actual current request path

```
Browser (audio2score-week4/frontend)
  POST /upload  (audio only: wav/mp3/m4a/flac)
    → audio2score-week4/backend/main.py
    → LocalStorage / SupabaseStorage
    → SQLite jobs row (status=queued)
    → RQ enqueue process_job (job_queue.py)
Worker (worker.py)
    → tasks.process_job
    → transcription.get_engine()
    → engine.transcribe(audio_path, job_id) → MusicXML string
    → storage.save_text("{job_id}.musicxml")
    → job status=completed
GET /jobs/{id}/result?format=musicxml  → stored MusicXML
GET /jobs/{id}/result?format=midi      → MusicXML re-parsed by music21 → MIDI bytes
PDF                                    → client-side OSMD SVG → jsPDF (no server PDF)
```

There is **no Fast/Quality request parameter**. Upload does not accept a mode. Job schema has no engine/mode column.

`get_engine()` (`audio2score-week4/backend/transcription.py`):

| `TRANSCRIPTION_PIPELINE` | Result |
|---|---|
| unset / `understanding` (default) | `FallbackEngine(UnderstandingPipeline, BasicPitchEngine)` if `TRANSCRIPTION_PIPELINE_FALLBACK=1` (default) |
| `legacy` | `BasicPitchEngine` only |

Production `.env.example` / `.env.production.example` set `TRANSCRIPTION_PIPELINE=understanding`.

**Bug:** `/health` reports `pipeline` default `"legacy"` when the env var is unset, but `get_engine()` defaults to `"understanding"`.

Entry files:

- API: `audio2score-week4/backend/main.py`
- Queue: `audio2score-week4/backend/job_queue.py`
- Worker: `audio2score-week4/backend/worker.py`
- Job: `audio2score-week4/backend/tasks.py`
- Engine factory: `audio2score-week4/backend/transcription.py` → `get_engine()`
- Understanding orchestrator: `audio2score-week4/backend/mir/pipeline.py`

The root stub `backend/engines/engine_router.py` (`get_engine(mode)` → MR-MT3 vs Basic Pitch) is **not imported** by the API or worker.

---

## 2. Actual Fast transcription path

**Product docs say Fast = Basic Pitch.** The live stack has no Fast mode switch.

What actually runs for every audio job (default config):

```
Audio
 → AudioNormalizer (mono, 22050 Hz, peak 0.95)
 → InstrumentClassifier (heuristic spectral scores)
 → AudioSegmenter (silence split; tempo per segment unused for the tempo map)
 → write normalized WAV
 → BasicPitchBackend.transcribe_notes()     # TRANSCRIPTION_BACKEND=basic_pitch
 → MIDICleaner.clean()                      # always on in UnderstandingPipeline
 → PianoAudioAnalyzer if classifier == piano (velocity rewrite; pedal discarded)
 → _estimate_tempo: BeatTracker.bpm_at(0) + refine_tempo (single BPM)
 → ChordDetector.detect()                   # return value discarded
 → MelodyAccompanimentSeparator
 → notes_to_events (seconds → beats; role pitch-set → hand hint)
 → HandSeparator, VoiceSeparator, Dynamics, Articulation, PhraseDetector
 → NotationWriter.write_musicxml
      events → pretty_midi (RH/LH instruments) → music21.parse(MIDI)
      → score.quantize(divisors=(4,3)) → MusicXML
```

So “Fast” in production is: **Basic Pitch + UnderstandingPipeline**, not a lighter path.

`BasicPitchBackend` discards Basic Pitch’s third return value (note tuples with amplitude). Notes are taken from `pretty_midi` with `confidence=1.0` hardcoded.

---

## 3. Actual Quality transcription path

**Product docs say Quality = MR-MT3 (remote GPU).**

Reality:

- `adapters/mt3_backend.py` raises `NotImplementedError`.
- `backend/engines/mr_mt3_engine.py` is an empty class (`name='mr-mt3'`).
- `backend/workers/mr_mt3_worker.py` is a comment stub.
- `REMOTE_GPU_ARCHITECTURE.md` is one line of intent, not an implementation.
- `TRANSCRIPTION_BACKEND=mt3` would throw inside UnderstandingPipeline; `FallbackEngine` would then run **legacy BasicPitchEngine**. Quality would silently degrade, not improve.
- `scripts/example_mt3.py` writes a whole-rest MusicXML placeholder.

There is **no Quality path**. Both the marketing modes collapse to Basic Pitch.

---

## 4. MIDI upload path

**Does not exist.**

`main.py` `ALLOWED_EXTENSIONS` = `{.wav, .mp3, .m4a, .flac}`. No `.mid` / `.midi`. No parser that starts at MIDI → CMR.

The architecture doc’s “MIDI file ───→ MIDICleaner → CMR” line is unimplemented.

---

## 5. Raw MIDI preservation path

**Partial, then discarded.**

Understanding and legacy both write `{job_id}.mid` under `bp_{job_id}/` as a **working file** for music21. That file is:

- tempo-aligned (single BPM);
- already cleaned;
- on the understanding path, split into RH/LH pretty_midi instruments;
- **not** stored as a job artifact;
- **not** the MIDI the user downloads.

User MIDI download is `MusicXML → music21 → MIDI`, so it is quantized, spelled, and flattened by music21. Pedal, raw onsets, confidence, and backend provenance are gone.

Raw Basic Pitch MIDI (pre-clean, pre-quantize) is never saved.

---

## 6. Current fallback behavior

`FallbackEngine.transcribe`:

1. Run `UnderstandingPipeline`.
2. On **any** exception, print `[PipelineFallback]` and run `BasicPitchEngine` (enhanced legacy).

Triggers include: no notes, MT3 `NotImplementedError`, music21 failures, classifier/librosa errors.

Silent quality change: the client still gets MusicXML with no flag that fallback ran. Job record has no `engine_used` field.

Legacy `BasicPitchEngine` (fallback / `TRANSCRIPTION_PIPELINE=legacy`):

```
normalize? → Basic Pitch → MIDICleaner? (flag, default on in .env)
 → PianoAnalyzer? → single-BPM tempo + last-note duration pad
 → pretty_midi → music21.quantize → MusicXML
```

Differences vs understanding: no hand/voice/dynamics/articulation/phrase layers; last-note padding; optional cleaner flag; same music21 quantize.

---

## 7. Duplicate pipelines

| Concern | Copy A | Copy B | Notes |
|---|---|---|---|
| Transcription facade | `audio2score-week4/backend/transcription.py` `BasicPitchEngine` | `mir/pipeline.py` `UnderstandingPipeline` | Both call Basic Pitch + cleaner + tempo + music21 quantize. Musical features are **only** on A’s understanding sibling, not shared. |
| Engine router | week4 `get_engine()` | root `backend/engines/engine_router.py` | Stub is dead. |
| Tempo | `detect_tempo` / `refine_tempo` / `_estimate_tempo` | `BeatTracker.track()` full `TempoMap` | Tracker map is thrown away; only `bpm_at(0)` seeds refine. Segment tempos unused. |
| Hand assignment | `MelodyAccompanimentSeparator` pitch gates (60 / 48) | `notes_to_events` melody→RH, bass→LH by **pitch set** | Then `HandSeparator` skips any non-UNKNOWN hand. Role pre-assignment **disables** the separator for those pitches. |
| Quantization | `BasicPitchEngine` `score.quantize` | `NotationWriter` same `score.quantize` | Duplicated music21 nearest-grid. |
| MIDI export | working `.mid` | GET `format=midi` from MusicXML | Two different MIDI meanings. |
| Frontend | `frontend/app/page.jsx` | `frontend/app/dashboard` + `UploadPanel` | Two upload UIs; neither has Fast/Quality. |
| Benchmark location | `audio2score-week4/backend/benchmark/` | (none at repo-root `backend/benchmark/`) | Existing suite compares cleaner fixtures via mocked notes, not real audio/MusicXML. |

---

## 8. Dead or unreachable code

| Item | Status |
|---|---|
| `backend/engines/*`, `backend/workers/mr_mt3_worker.py`, `backend/notation/README.md` | Not on `sys.path` of the running app. Dead stubs. |
| `MT3Backend.transcribe_notes` | Reachable only if `TRANSCRIPTION_BACKEND=mt3`; then raises. |
| `ClassicalDspBackend` | Reachable via env; **not** production default. Experimental DSP stack. |
| `ChordDetector.detect` return | Computed, unused. |
| `PianoAnalysis.pedal_events` | Computed, unused. |
| `AudioSegment.estimated_tempo` | Unused for TempoMap. |
| `MusicalEvent.phrase_id` | Set, never consumed by the writer. |
| `ScoreMeta.key_hint`, `time_sig_hint` | Never populated. |
| `NotationWriter.write_from_events_direct` | Tests only; production uses MIDI round-trip. |
| `TRANSCRIPTION_ENGINE` (`placeholder` / `command` in week4 README) | README is stale. `get_engine()` does not read this variable. Health displays it only. |
| `example_mt3.py` | Demo placeholder, not wired unless someone sets `MT3_TRANSCRIBE_COMMAND` — and that command path is **not** in current `get_engine()`. |
| `frontend_redesign/` | Mock UI, not the live Next app. |
| Octave-ghost removal | **Does not exist** (despite being a risk if added naively). |

---

## 9. Experimental code currently affecting production

These run on the default understanding path (`TRANSCRIPTION_USE_MIR_LAYERS=1`):

1. **`HandSeparator`** — hard split `pitch >= 60 → RH else LH`. Affects MIDI instrument split, therefore staff grouping after music21 MIDI import.
2. **`VoiceSeparator`** — new voice whenever two notes overlap on the same hand. **Then voices are dropped** in `NotationWriter._events_to_midi` (pretty_midi has no voice). Net effect: overlap-only voices do extra work and vanish.
3. **`DynamicsExtractor`** — every note gets a dynamic from velocity. Writer maps by **pitch only** (`dynamic_map = {e.pitch: e.dynamic}`), so the last note of that pitch wins and music21 may stamp many dynamics.
4. **`ArticulationDetector`** — duration `< 0.35` beat → staccato; small gap → legato. After MIDI round-trip, lookup is `(pitch, round(offset, 3))` which often misses.
5. **`PhraseDetector`** — gap-based IDs, unused downstream.
6. **`InstrumentClassifier`** — coarse heuristics; piano vs not gates `PianoAudioAnalyzer`, which **replaces Basic Pitch velocities** with onset-envelope mapping (destroys original velocity).
7. **`MIDICleaner`** — always on in understanding (no `TRANSCRIPTION_USE_CLEANER` gate). Drops notes shorter than 40 ms; merges same-pitch onsets within 25 ms; snaps “chords” within 50 ms to a common onset. Destructive, no KEEP/SUPPRESS/UNCERTAIN, no reasons.
8. **`music21.quantize(4, 3)`** — global nearest-grid; invents tuplets; no meter hypothesis; no voice awareness.

`ClassicalDspBackend` does **not** affect production unless the env is changed.

---

## 10. Current data model

### Raw notes (`mir.types.NoteEvent`)

`pitch, start_time, end_time, velocity, confidence`

Missing: note id, source backend, original timestamps, channel, pitch bends, pedal, provenance.

### Notation events (`mir.types.MusicalEvent`)

`pitch, start_beat, duration_beats, velocity, instrument, voice, hand, phrase_id, articulation, dynamic, confidence, source_backend`

This is a **flattened hybrid**: performance time has already been converted to beats with a single BPM; hand/voice/phrase hang off the same object that the writer mostly ignores.

### Supporting types

- `TempoMap` / `TempoPoint` — implemented, collapsed to one BPM in the pipeline.
- `MusicalRole` — melody/bass/accomp lists; matching in `notes_to_events` is by **pitch integer**, so every C4 is “melody” if any C4 was.
- `ScoreMeta` — display tempo, unused key/time hints, unused segments.
- `Hand` — LEFT / RIGHT / UNKNOWN. No AMBIGUOUS. UNKNOWN is overwritten by the 60-split.

There is **no** `TranscriptionResult`, `RawPerformance`, `MusicalStructure`, or `NotationPlan`. music21 is the implicit structure engine.

---

## 11. Where information is lost

Ordered along the live path:

1. **Basic Pitch amplitude / confidence** dropped (`_, midi_data, _ = predict(...)`).
2. **Pitch bends** dropped.
3. **Multi-instrument MIDI** flattened to one note list.
4. **MIDICleaner** deletes micro-notes; merges duplicates (can fuse repeated notes); chord-snaps independent lines into one onset.
5. **Piano analyzer** overwrites velocity; pedal never attached.
6. **Tempo map** reduced to one BPM; beat times unused; no meter.
7. **Chord labels** thrown away.
8. **Role → hand by pitch set** mis-labels later notes of the same pitch.
9. **HandSeparator** middle-C split; no span, motion, or crossing.
10. **VoiceSeparator** overlap-only; no continuity.
11. **Seconds → beats** with constant tempo; original times not stored on `MusicalEvent`.
12. **NotationWriter MIDI round-trip**:
    - voices gone;
    - UNKNOWN/AMBIGUOUS would collapse to RH (`else rh`);
    - music21 infers meters, ties, chords, spelling;
    - simultaneous notes on one instrument become chords regardless of voice.
13. **Quantize** snaps every offset/duration independently (plus music21’s own chord grouping).
14. **Dynamics** remapped by pitch; **articulations** often fail to reattach; **phrases** unused.
15. **Stored artifact is MusicXML only.** User MIDI is a second lossy encode.
16. **Fallback** hides which engine produced the file.

---

## 12. Architectural risks

1. **Two pipelines, two feature sets.** New musical logic is added only on understanding, while fallback/benchmark still use legacy music21 quantize. Easy to “fix hands” in MIR and never see them in the score.
2. **music21 as the musical brain.** Hands/voices/meter/rhythm are inferred again after we already computed (and then discarded) structure.
3. **Destructive cleaning without provenance.** Short notes, including legitimate ornaments, disappear.
4. **Middle-C hand split** produces unreadable piano music (melody below C4 on bass, bass walks onto treble).
5. **Overlap ≠ voice.** Chords explode into extra voices; true polyphony is not tracked; writer would chord them anyway.
6. **No meter model.** 6/8 vs 3/4 vs 4/4 is whatever music21 guesses from quantized MIDI.
7. **Stub Quality path.** Enabling MT3 currently means fallback to legacy, not a better model.
8. **No job-level debug record.** Cannot inspect removed notes, meter, hands, or voices after a production job.
9. **Health/docs lie** about engine, pipeline default, and Fast/Quality.
10. **Root `backend/` vs `audio2score-week4/backend/`** invites edits to the wrong tree.
11. **Benchmark is not a musical benchmark.** It checks note F1 of cleaner fixtures through two pipelines that share Basic Pitch mocks. No hand/voice/meter/notation metrics; no reference MusicXML.
12. **Characterization tests freeze the wrong behavior** (e.g. overlapping C+E must be two voices).

---

## 13. Recommended canonical pipeline

```
Audio
 → normalize
 → analyze (instrument, segments, beat tracker)     # observations, not decisions
 → transcribe (Fast: Basic Pitch; Quality: future MT3 — same adapter interface)
 → TranscriptionResult (notes + confidence + backend + raw MIDI bytes)
 → RawPerformance (notes, CC, pedal, tempo observations, source metadata)
 → cleanup (classify KEEP / SUPPRESS / UNCERTAIN; log reasons; shadow-capable)
 → tempo / beat analysis (keep the map; do not collapse yet)
 → MusicalStructure
      tempo map, meter hypotheses + selection, key hypotheses,
      phrases, roles, hands (Viterbi), voices (continuity)
 → NotationPlan
      measures, staves, voices, durations, rests, ties, tuplets,
      clefs, key/time signatures  — explicit decisions
 → MusicXML writer (music21 as export library only)
```

**Rules**

- Fast and Quality differ **only** at the transcription adapter. Downstream is one pipeline.
- Legacy `BasicPitchEngine` stays as fallback + benchmark baseline. Do not add new musical features there.
- Do not delete unused modules yet (classical DSP, MT3 stub, root engine stubs).
- Preserve uncertainty and provenance on every note.
- Do not let music21 invent meter, voices, or hand assignment.
- MIDI upload should enter at `RawPerformance`.
- Persist raw MIDI + debug JSON beside MusicXML (even if the public API still returns MusicXML first).

Exact files to change are listed in `docs/CANONICAL_PIPELINE.md`.

---

## Appendix A — Production flags (actual defaults)

| Variable | Code default | `.env` / prod example |
|---|---|---|
| `TRANSCRIPTION_PIPELINE` | `understanding` | `understanding` |
| `TRANSCRIPTION_PIPELINE_FALLBACK` | `1` | `1` |
| `TRANSCRIPTION_BACKEND` | `basic_pitch` | `basic_pitch` |
| `TRANSCRIPTION_USE_CLEANER` | `0` in code, **legacy only** | `1` |
| `TRANSCRIPTION_USE_MIR_LAYERS` | `1` | `1` |
| `TRANSCRIPTION_USE_NORMALIZER` | `1` | `1` |
| `TRANSCRIPTION_USE_BEAT_TRACKER` | `1` | `1` |
| `TRANSCRIPTION_USE_PIANO_ANALYZER` | `1` | `1` |
| Understanding cleaner | always on | n/a |

## Appendix B — Test / benchmark inventory

**Tests (week4):** characterization, enhanced legacy, understanding pipeline, MIR notation (thin), MIDI cleaner, cleaner before/after, tempo map, instrument classifier, chord/role, pitch/poly decode, segmenter/onset, normalizer, MT3 stub, benchmark harness.

**Gaps vs required suite:** no hand-crossing cases, no voice continuity, no measure-sum tests, no octave-doubling vs ghost, no triplet/syncopation/tie tests, no MusicXML voice preservation.

**Benchmark:** three synthetic cleaner fixtures; cross-pipeline note F1; readability heuristic (micro-notes, dupes, chord spread). No reference audio corpus in-repo.
