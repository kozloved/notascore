# Canonical rest engraving review

Reviewed main at `6763e0a6741c82f8d28284b2e286993867d44bba` (PR #98,
September 30). This review addresses the shared exact score planner; it does
not certify general transcription accuracy or deployed PDF quality.

## Latest update

PR #98 adds bounded Readable onset alignment, editable ornament decisions,
aspect-preserving A4 PDF assembly, and sparse printed tempo. The existing
Autumn Walks paired counterexamples pass. Its acceptance report explicitly
states that ornament decisions are not yet engraved as MusicXML grace notes.
Experimental notation remains opt-in.

## Fixed in this increment

- Rests previously inherited sustained-note syncopation rules. An eighth-note
  rest starting halfway through a beat could become a dotted quarter rest
  spanning the following pulse. Silence now exposes pulse boundaries regardless
  of the note syncopation setting. Note attacks, durations, ties, and ownership
  are unchanged by this engraving pass.
- Simple 2/4 and 4/4 retain aligned half rests. Triple meter uses separate beat
  rests; compound meter retains dotted beat rests. Partial gaps retain exact
  rational duration rather than moving the following attack.
- Empty primary lanes and entirely empty staves previously used structural
  rests, which the writer hides. They now have visible musical rests; empty
  secondary lanes still use hidden structural fillers. MusicXML serialization
  produces visible whole-measure rests in 3/4, 4/4, and 6/8.
- Tuplet annotation previously excluded rests. Rests now share the explicit
  tuplet ratio and bracket group, including when a rest opens a triplet.

## Validation

199 tests passed across canonical-rest engraving, Autumn Walks Readable,
shared engraving, notation interpretation, articulation ownership, Readable
v2 cases, notation integrity, export safety, export integrity, fidelity
regressions, revision safety, orchestration, and simple-score tests.
One FastAPI/Starlette dependency deprecation warning remains.

21 dedicated rest tests cover paired simple/compound examples, unchanged note
syncopation, source coverage, secondary-lane visibility, and actual MusicXML
serialization of full-bar rests and rest-led triplets.

A synthetic three-bar piano example was rendered before/after with Verovio
and inspected: the dotted offbeat rest becomes eighth + quarter rests;
blank primary measures and the unused bass staff now show measure rests.
This is secondary-renderer evidence, not an OSMD browser or production PDF
smoke test. No GPU/audio-model inference was run; audio tests use mocks.

## Next musical-quality milestones

1. Implement editable grace-note engraving with explicit source IDs and a
   defined score-playback timing contract. Do not turn source notes into
   zero-duration events merely to obtain small noteheads.
2. Evaluate stable voice and hand separation on reference piano excerpts,
   including melody inside chords, crossing hands, repeated unisons, and a
   held inner voice. Compare the same MIDI under Literal and Readable modes.
3. Add rendered acceptance examples for 3/4, 6/8, syncopation, mixed tuplets,
   pickups, and multi-voice silences in the actual OSMD/PDF export path.
   Measure readability alongside pitch/onset/duration fidelity before changing
   the default notation algorithm.

The engine has useful provenance and export-integrity protections, but passing
these regressions alone is insufficient evidence of publisher-quality notation
on arbitrary MIDI or audio.

## Pre-merge follow-up (October 8)

GitHub's foundation job exposed a tempo regression after PR #98: the CLI wrote
MIDI directly from the sparsely marked engraving score, losing performance
tempo changes. The CLI now uses the shared MusicXML/playback exporter; when
`preserve_midi_tempo` is set without a `playback_tempo` payload, playback reads
the full source tempo map independently of printed marks. The existing tempo
regression now covers expressive, opening-only, and disabled printed tempo.
Canonical-rest tests are also included in the foundation CI job.
