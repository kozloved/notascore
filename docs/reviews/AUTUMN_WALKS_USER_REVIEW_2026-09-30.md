# Autumn Walks: user review and artifact inspection

Date: 2026-09-30. Reviewer: the user in this conversation. This is actual user feedback, not an invented rating or a completed machine-schema review. No correction-time measurement was supplied. Job ID, deployed engine SHA, and settings of each attached export remain unknown. Latest remote code inspected: `e958da6` (PR #97). Local application code was not changed.

## User feedback / desired musical reading

- Overall recognisable, but rhythm and duration interpretation is too literal.
- Standard versus Experimental and Readable versus Literal showed little perceived difference. Separate exports for all four combinations were not supplied; this is the user's observation, not an independently measured comparison.
- Opening right-hand F should be on the beat with the bass despite a slight performed delay. The user identifies the bass as F sharp; do not change enharmonic spelling merely to match this description.
- Readable notation should absorb incidental tiny release gaps rather than show pervasive 32nd rests. This is not permission to remove intentional rests globally.
- Printed measure 9: user requests C, C sharp, E flat as three quarter-note pulses, with B flat treated as an ornament. Ornament placement/style should remain editable; do not delete its source attack or alter performed playback.
- A4 PDF should normally fit 3–4 bars per system where density permits, with balanced pagination and readable note size.
- Expressive tempo indications and return-to-normal-tempo indications should be optional in the editor. Distinguish meaningful tempo changes from small fluctuations; do not print an Italian word for every measured BPM change.

## Supplied files

Shared stem: `I'm releasing a new piano song called Autumn Walks in 2 days!  _) #piano #composer #neoclassical`.

- Downloads: stem + ` (1).pdf`; SHA256 `0c166698d145f0f987acccf8c424be0e13aa4ae47b554800f2232867e4bf1548`.
- Downloads: stem + `.score.mid`; SHA256 `bc4603a554aa0e04a434a9a914660c437bb294de95abce13042ca377778336de`.
- Downloads: stem + ` (2).mid`; SHA256 `aae968993fe7aa03dd21d3ba77e2aa8cc143cd585b6d6b0e257f6d2156cf7cca`.
- Desktop: stem + `.mp3`; ffprobe duration 16.874667 seconds. Audio was not independently listened to for musical adjudication in this inspection.

Files are provided for this review; no broader redistribution/license assumption is made. Original files were not modified or committed.

## Independently inspected evidence

PDF: 3 A4 portrait pages, jsPDF 4.2.1, 26,265,878 bytes. All pages rendered and inspected. Mostly 1–2 bars/system, many short rests/tied fragments, repeated decimal tempo marks (171.4, 166.7, 176.5). Final page contains only one system. The problem is not literally one bar on every line; it is sparse, unbalanced page layout and complex notation.

Both MIDI files decode to 100 attacks. This establishes count equality, not full source identity or transcription accuracy.

`.score.mid`: 10080 ticks/quarter, 7 tracks, 3/4. Bass MIDI 42 starts at beat 3; right-hand MIDI 77 (F5) at beat 3.125. Difference = 0.125 quarter-note beats, a notated 32nd; approximately 45 ms at the local tempo. `(2).mid` has a corresponding opening bass/F pair at 0.2/0.230208 seconds, but its role as the raw download is not yet confirmed.

In the score MIDI window corresponding to printed measure 9 (beats 24–27):

| MIDI pitch | Onset (beats) | Duration (beats) |
|---|---:|---:|
| 70 / B flat | 24.125 | 1.5 |
| 72 / C | 24.25 | 1.5 |
| 73 / C sharp | 25.125 | 0.75 |
| 75 / E flat | 26 | 1 |

The B flat is not short in this exported MIDI. Trace raw duration, pedal/release handling, voice allocation, and written duration before attributing the ornament defect solely to engraving.

Additional timing observation: `.score.mid` first/last attack-span bounds are 0.9–17.31 seconds; `(2).mid` bounds are 0.039583–16.383333 seconds. Roles/origins are unconfirmed. Investigate alignment and playback export separately; do not claim playback equivalence from equal counts.

## Code inspection leads (not proven root causes)

- `mir/performance_score.py::_onset_candidates` returns immediately for exactly representable attacks before checking Literal versus Readable. An exact 3.125 can therefore bypass simpler alternatives in Readable mode. Trace actual raw inputs and decision diagnostics before changing this.
- V2 small-release-gap filling excludes several release reasons, including independent holds and pedal tails. Determine which decisions block simplification on this sample; do not remove exclusions globally.
- `frontend/lib/sheet-pdf.js` rasterizes current preview SVGs and stretches each image to the whole A4 page. Investigate preview viewport influence, aspect ratio, margins, and a dedicated print layout before trying to force bar counts.

## Implementation priorities

1. Reproduce all four engine/interpretation combinations from one canonical input; persist settings and decision evidence, never infer settings from appearance.
2. Add this user's requested reading as an attributed development case. Fix contextual onset alignment and regular written durations with paired syncopation/rest/independent-voice counterexamples. Preserve raw performance and original attacks.
3. Trace measure 9's duration/ornament interpretation. Add explicit editable ornament representation if required, with source provenance and non-grace counterexamples.
4. Render PDF independently at stable A4 print dimensions, preserving aspect ratio; target 3–4 bars/system when readable, without clipping or splitting systems.
5. Separate full playback tempo from sparse printed tempo. Suppress redundant/jitter marks; expose optional meaningful slower/return indications in the editor.

Acceptance requires matched before/after MusicXML/PDF renders and decoded playback comparisons, not only green unit tests. Do not mark the wider P1/P2 program complete based on this one review.
