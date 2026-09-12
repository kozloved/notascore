# Engine review: fidelity and complexity

Date: 2026-09-12. Scope: the active `audio2score-week4/backend` tree,
production performance notation, editor import/export, and MIDI downloads.
Earlier audit documents describe older implementations and are historical.

## Assessment

Keep the core approach: immutable source notes in seconds, an explicit musical
time map, bounded notation decisions, and an exact notation plan. This is a
reasonable way to support rubato without forcing every performance onto a
constant-tempo grid. Rational score durations and per-note provenance are useful.

The surrounding structure is too complicated for the current product. The
pipeline, notation writer/planner, legacy transcription facade, and two
quantizers collectively occupy roughly 5,000 lines, with multiple ways to own
tempo, assign voices, spell rhythms, and recover from errors. More model flags
will not solve that coordination problem.

## Confirmed problems addressed in this review

1. **MIDI generated from engraving ties changed attacks in dense polyphony.**
   The new generated polyphony tests failed before the fix even where the
   MusicXML attack timeline was correct. MIDI is now built from unsplit events
   using the shared `notation_engine/playback.py` helper.
2. **Editor import converted each tied fragment into a new note.**
   It now reconstructs contiguous ties by part, voice, and pitch. A held note
   followed by a real repeat remains two attacks, not a series of bar fragments.
   Server-side editing no longer rounds all supplied timings to sixteenths.
3. **Validating the plan did not validate the delivered files.**
   Performance exports now check source identity, reparse MusicXML ties, and
   inspect MIDI note-on/note-off pairs. Pitch, attack count, onset, and release
   must match the quantized event stream. Files are staged before publication;
   corrupt exports and MIDI-write failures fail the job. Debug output records
   the result under `export_integrity`.
4. **Broad fallback could bypass fidelity failures.**
   `FallbackEngine` now propagates performance-mode failures and integrity
   failures instead of silently invoking legacy transcription and rewriting.
5. **Bar phase could be applied twice.**
   The audio pipeline aligned its musical time map, then passed downbeats from
   a different performance map into notation. That second shift is removed.
   Timing adapters also no longer invent downbeats every four beats when no
   measured downbeat evidence exists.
6. **Some pipeline tests used the wrong quantizer.**
   The shared historical fixture sets quantization to `off`. New fidelity tests
   explicitly select `performance`; the MIDI tempo regression now asserts that
   it ran that mode and passed the export integrity check.

## Components actually available

| Component | Local status after review | Decision |
| --- | --- | --- |
| madmom RNN + DBN beat/downbeat tracker | Installed; real click-track inference passed | Active through the existing default backend |
| FFmpeg | Installed; tracker resampling verified | Available to audio processing |
| Basic Pitch, ONNX, music21, pretty_midi | Already installed | Kept |
| MIR hands/voices and performance quantization | Already enabled | Kept |
| PM2S | No local torch/model checkout | Not enabled as a replacement quantizer |
| Transkun / Beat This | Adapters unconditionally raise unavailable | Flags cannot activate a working implementation |
| Separation / stem transcription | No configured separation endpoint | Not enabled |
| Fusion | Produces side artifacts after score export | Not enabled as a supposed score improvement |
| AudioSet tagging | Optional model packages absent | Not required for note-preservation checks |

madmom is pinned in requirements to the revision tested here. Health reports
both import availability and FFmpeg availability. These installations are local;
this review did not deploy dependencies or changes to a remote worker.

## Remaining non-obvious risks

- **Fusion does not feed the score.** `engine/orchestrator.py` completes score
  interpretation before `_fuse()` writes fused artifacts. Enabling fusion alone
  therefore does not improve the MusicXML. Its confidence-gated stem-only notes
  can also add notes to the separate fused MIDI, by design.
- **The editor still has a single-tempo model.** Its `tempo_bpm` field cannot
  retain a full rubato/tempo-change curve. Attack preservation is now checked,
  but editing is not yet a complete performance-preserving round trip.
- **The score is still a hypothesis.** Fixed timing tolerances, duration priors,
  and beam-search costs cannot establish the intended rhythm of arbitrary free
  playing. Correct note count is not evidence of correct meter or readability.
- **Timing has two representations.** MIDI event conversion uses the exact
  tempo map, while diagnostics still sample a `MusicalTimeMap` at integer beats.
  A future consumer must not use those samples to reinterpret subbeat MIDI
  tempo changes. Consolidate ownership before adding more timing backends.
- **Legacy modes remain distinct behaviors.** `off` still needs notation
  spelling; it is not an assurance of lossless MusicXML. The new strict source
  identity gate is on the production performance path, not every historical
  experimental quantizer.
- **Upstream transcription can already contain false notes.** The checks prove
  preservation relative to supplied notes. They cannot prove that AMT notes
  agree with the recording. Blind same-pitch deduplication would also delete
  real repeated notes and instrumental unisons.
- **Some capabilities are declared rather than implemented.** In particular,
  `transkun_available()` can report configured flags/checkpoints even though
  the adapter always raises. Configuration and operational readiness should be
  reported separately for every optional model.

## Recommended simplification order

1. Make one immutable per-job note set and one authoritative time mapping the
   inputs to both notation and playback. Pass explicit stage results instead
   of coordinating through many mutable `last_*` fields.
2. Keep the performance quantizer as the production implementation. Move
   legacy/adaptive/PM2S paths behind explicit comparison or experimental entry
   points; do not add new product behavior to each one.
3. Extend the editor model with source identity, voices, and a tempo curve so
   changing one pitch cannot change the timing model of the whole clip.
4. If federation is needed, reconcile before interpretation and make the source
   of every added or suppressed note reviewable. Keep a full-mix-only baseline.
5. Add human-reviewed recordings with rubato, ornaments, pedal, repeated notes,
   and meter changes. Evaluate acoustic correctness and score readability
   separately from the mechanical export checks.

## Validation

`tests/test_export_integrity.py` exercises all 21 bundled input MIDIs, eight
seeded polyphonic sequences, deliberately corrupted exports, ties versus real
repeats, editor round trips, the old-job MIDI download, and bar-origin alignment.
No source MIDI fixture is rewritten by these tests. The gate rejects duplicate,
missing, mistimed, orphan-tied, and unterminated exported notes rather than
publishing them. Further tests cover subbeat tempo changes and fast triplets.

The real madmom smoke test detected 16 beats and four downbeats at 120 BPM.
Final verification: 637 tests passed in the sandbox; the three Core ML tests
blocked by sandbox compilation passed on a separate unrestricted run, for 640
passing tests across runs. Four optional live integration/model tests were
excluded. No remote GPU service was invoked. `git diff --check` passed.
