# Readable musical-context review — 2026-10-07

Reviewed main: `6763e0a`, latest merge PR #98 (Autumn Walks readability).

## Findings and changes

- The fast-figure guard counted notes rather than distinct attacks. A three-note block chord incorrectly prevented alignment with the bass. Count distinct onset times instead.
- Alignment cost counted every chord member, letting chord density pull the bass away from the pulse. Give each voice/track attack equal weight and use deterministic candidate ordering.
- Two distinct same-voice attacks inside the shared-beat window could collapse onto one onset. Preserve these figures, including repeated pitches.
- Ornament inference allowed simultaneous notes and searched across voices/tracks in one hand. Require positive anticipation and a primary note in the same voice and source track.

These changes affect Readable inference. Literal behavior and source MIDI are not rewritten. Exact simultaneity uses a numerical tolerance, not a new broad chord-clustering threshold. Rolled chords remain conservative.

## Verification

The four new regression cases reproduced three logic failures plus a test construction error on the baseline; after correcting the immutable-event test setup, all four pass with the fix. Existing Autumn Walks cases remain green.

Expanded targeted run: 131 passed, one HTTP-app test deselected, one audio-pipeline test blocked by missing librosa. An earlier run included the HTTP test, which was blocked by missing python-dotenv. Neither integration path is claimed verified. No original Autumn Walks input or new rendered PDF was available for visual comparison in this checkout.

## Remaining quality work

1. Connect explicit ornament decisions to grace-note engraving with source-note mapping and an independent playback representation. The latest merge documents this as unfinished; merely tagging articulation is insufficient.
2. Reproduce the documented 100-source/108-score-MIDI attack discrepancy on the original input. The performance writer already has an unsplit-event playback path, so the historical count alone does not establish its current cause.
3. Compare actual A4 renders on dense piano, compound meter, syncopation, and independent sustained voices. PDF aspect-ratio correction does not prove balanced pagination or canonical rhythm spelling.
4. Complete the attributed musical review corpus described in ENGINE_ROADMAP.md before claiming edition-quality output or promoting Experimental notation.

This is a targeted correctness/readability increment, not a full engine certification.
