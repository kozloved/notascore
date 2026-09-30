# Autumn Walks: four-mode reproduction

Date: 2026-09-30. Engine SHA: `e958da6` (origin/main / PR #97). Meter forced to `3/4`.

## Canonical input

- File: Downloads stem + ` (2).mid`
- SHA256: `aae968993fe7aa03dd21d3ba77e2aa8cc143cd585b6d6b0e257f6d2156cf7cca`
- Role: treated as raw performance MIDI (100 notes, tempo map 120 BPM at t=0, no pedal events).
- Job ID / deployed settings for the user PDF remain unknown (per review).

## Opening performed timing (raw)

| Pitch | note_id | t (s) | start_beat | duration_beats |
|---|---|---:|---:|---:|
| 42 (bass) | track:0:note:8 | 0.200000 | 0.400000 | 3.6958 |
| 77 (F5) | track:0:note:9 | 0.230208 | 0.460417 | 3.6354 |

Hands after layout: bass LEFT voice `(1,0)`; F5 RIGHT voice `(0,0)`. Searched independently.

## Written opening under all four modes (after Readable fix)

| Mode | Settings | bass42 start | rh77 start | delta |
|---|---|---:|---:|---:|
| Standard + Literal | interpretation=literal, performance-score-1 | 0.375 | 0.5 | 0.125 |
| Standard + Readable | interpretation=readable, performance-score-1 | 0.5 | 0.5 | 0.0 |
| Experimental + Literal | interpretation=literal, performance-score-2 | 0.375 | 0.5 | 0.125 |
| Experimental + Readable | interpretation=readable, performance-score-2 | 0.5 | 0.5 | 0.0 |

Readable unifies the opening pulse. Literal keeps the performed delay. Re-ingesting `.score.mid` under Readable also snaps RH 3.125 → 3.0 with the bass.

Raw Bb `track:0:note:72` (performed ~0.26 beats) is labeled `ornament_style=acciaccatura` under Readable only; long written holds (score-export Bb at 1.5 beats) are not auto-ornamented.

## Written opening under all four modes (before fix)

Via `python -m mir.performance_cli … --meter 3/4` with interpretation / `--readable-v2` as labeled. Artifacts under `/tmp/autumn_walks_repro/before_*.decisions.json`.

| Mode | Settings | bass42 start | rh77 start | delta |
|---|---|---:|---:|---:|
| Standard + Literal | interpretation=literal, performance-score-1 | 0.375 | 0.5 | 0.125 |
| Standard + Readable | interpretation=readable, performance-score-1 | 0.375 | 0.5 | 0.125 |
| Experimental + Literal | interpretation=literal, performance-score-2 | 0.375 | 0.5 | 0.125 |
| Experimental + Readable | interpretation=readable, performance-score-2 | 0.375 | 0.5 | 0.125 |

All four modes kept a written 32nd between bass and RH F before the fix.

## `_onset_candidates` short-circuit

| raw | Literal | Readable | Readable v2 |
|---:|---|---|---|
| 3.125 | exact-only 3.125 | exact-only 3.125 | exact-only 3.125 |
| 0.4604 | multi; best 0.5 | multi; best 0.5 | multi; best 0.5 |
| 0.4000 | multi; best 0.5 | multi; best ~0.375/0.5 tied | same |

Re-ingesting `.score.mid` (SHA `bc4603a…8336de`) locks bass at 3.0 and RH at 3.125 in every mode because exact representable onsets return before Readable alternatives. That matches the review lead.

LH voice path for raw bass: candidates cost 0.375≈0.110 vs 0.5≈0.113; beam picks 0.375. RH independently picks 0.5. No cross-voice accompaniment alignment.

## Measure-9 window (raw vs score export)

Score export (printed measure 9, beats 24–27 @ ~166.7 BPM): Bb70 24.125/1.5, C72 24.25/1.5, C#73 25.125/0.75, Eb75 26/1.

Raw corresponding late cluster (120 BPM beat coords; not the same map): Bb70 `track:0:note:72` 23.6604/0.2604, C72 23.9208/0.4396, C#73 24.3604/0.8396, Eb75 25.1792/0.7417. Written under exp+readable: 23.75/0.25, 24.0/0.375, 24.375/0.875, 25.25/0.75. Bb is short in the raw file; long in the exported score MIDI (likely duration spelling / prior job), so ornament must not be inferred from the export duration alone.

## Provenance gaps

- Unknown: original job ID, deployed engine SHA, and UI settings for the supplied PDF / `.score.mid`.
- Confirmed independently: hashes, four-mode indifference on opening delta, exact-onset short-circuit, separate-voice search.
