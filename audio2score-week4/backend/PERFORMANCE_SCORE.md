# Performance-to-score engine

The `performance` mode is the default engine for the staged
performance-to-score rebuild. Explicit `adaptive` mode remains available.
It targets solo piano and single-stream pitched instruments, and preserves
source MIDI independently of notation. See `docs/PERFORMANCE_FOUNDATION.md`
at repository root for the staged migration and remaining release gates.

## Run

From the backend directory:

```sh
.venv/bin/python -m mir.performance_cli input.mid output.musicxml --meter 4/4
```

This reads the MIDI tempo map, creates a grand-staff or single-staff MusicXML
score, and writes `output.decisions.json`, `output.performance.json`, and
`output.score.mid`. It invokes no audio model or cloud service. Without
`--meter`, the MIDI meter hint or the existing meter estimator is used.

The existing upload pipeline defaults to `performance`. To select it explicitly:

```sh
TRANSCRIPTION_QUANTIZATION_MODE=performance
```

The pipeline's cleaning and enhancement settings still apply before this
engine. The standalone command bypasses those stages. Neither path changes
the original MIDI file through quantization.

## Implemented

- Copies with source IDs and immutable rational score-note records.
- Existing contextual Viterbi hand assignment and continuous voice separation.
- Per-voice bounded rhythm search with binary and triplet candidates, strict
  attack ordering, movement bounds, and small rhythm continuity costs.
- Chord attack groups, contextual melody/bass/accompaniment hypotheses, and
  four-bar analysis windows. Windows are not detected musical phrases.
- Named durations, dotted values, mixed binary/triplet voices, and long sustains.
- Whole-piece lane assignment so bar splitting cannot change a sustained
  note's staff or voice.
- Exact note/rest spelling, barline ties, and per-source coverage validation.
- Meter-aware duration spelling, including dotted compound beats, and explicit
  beam and tuplet boundary/group annotations computed during planning.
- MusicXML export through music21, without legacy fallback or duration
  sanitization in this mode. Unsupported interpretations fail explicitly.
- Synthetic regression fixtures, a MIDI-to-MusicXML integration test, and an
  offline A/B runner that reconstructs attacks from exported XML ties.

The search is bounded to 24 states per attack. Hand and voice inference are
currently sequential inputs to rhythm search, not a joint optimizer.
The decision report records timing changes and musical-role hypotheses.
Role confidence is an uncalibrated 0.4, not a probability of correctness.

## Next phases

1. Expand the baseline with musician-reviewed MT3 fixtures. The local A/B
   baseline below covers timing and export fidelity; hand/voice accuracy and
   visible-rest readability still need independently annotated references.
2. Retain competing hand/voice hypotheses and jointly rescore them with rhythm.
   Add pickup hypotheses, phrase boundaries, pedal-aware duration evidence,
   and tempo-map uncertainty. Address the observed onset regressions using
   additional fixtures rather than tuning solely to the three development pairs.
3. Add phrase-level correction controls and visual engraving evaluation in
   OSMD. Compare real desktop/mobile rendering and musician readability.

The planner uses music21's meter grammar for beam and tuplet grouping. Rendering
remains delegated to the existing renderer. It does not yet model ornaments, arbitrary
tuplets, cross-staff beaming, fingerings, or independently inferred pickups.
It does not correct missing or spurious MT3 pitches. A plausible score is an
interpretation of the MIDI, not proof of the composer's intent.

## Verification

```sh
.venv/bin/python -m pytest tests/test_performance_score.py tests/test_performance_cli.py -q
```

The tests check source immutability, exact timing, simultaneous subdivisions,
finer triplets, cross-bar source coverage, empty input, error propagation,
and MusicXML round-trip attacks and durations. Existing adaptive, hand,
voice, planner, and export safety tests remain relevant regression gates.

## Offline A/B baseline

```sh
.venv/bin/python -m evaluation.score_ab benchmark/corpus --out /tmp/notascore-score-ab-synthetic
.venv/bin/python -m evaluation.score_ab evaluation/development/NotaTestSamples --out /tmp/notascore-score-ab-development
```

Both engines receive the same ingested events and source tempo/meter metadata.
The runner writes each MusicXML file, reparses it, joins contiguous same-voice
ties, and uses the existing evaluation matcher. It reports reference timing
accuracy separately from fidelity to the engine's own quantized events.
No reference alignment, tempo fitting, or cloud transcription is performed.
Reported reference metrics use the existing 50 ms onset and 100 ms offset tolerances;
export fidelity uses 10 microseconds. Successful export alone is not a passing
accuracy result. Missing and spurious notes count against F1.

Local baseline: 21 synthetic pairs and three development raw/quantized pairs.
The development pair names do not establish that these are verified MT3
transcriptions or musician-reviewed score ground truth.

| Development case | Adaptive onset/pitch F1 | Performance onset/pitch F1 | Adaptive offset F1 | Performance offset F1 |
|---|---:|---:|---:|---:|
| Case1 | 1.000 | 0.857 | 0.571 | 0.857 |
| Case2 | 1.000 | 0.929 | 0.071 | 0.786 |
| Case3 | 1.000 | 1.000 | 1.000 | 1.000 |

All 21 synthetic pairs scored 1.000 onset/pitch and offset F1 for both engines.
All 24 pairs exported with 1.000 fidelity to the selected quantized events.
These small, mostly easy fixtures do not establish general superiority or
natural engraving. In particular, two development cases regress in onset
accuracy despite better duration accuracy. Performance was promoted to the
default by explicit product decision with these limitations retained. Set
`TRANSCRIPTION_QUANTIZATION_MODE=adaptive` to restore the previous engine.
