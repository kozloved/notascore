# Autumn Walks acceptance evidence (increment: Readable + PDF + printed tempo)

Engine tip at change: branch `cursor/engine-autumn-walks-readable` from `e958da6`.
Canonical input SHA256: `aae968993fe7aa03dd21d3ba77e2aa8cc143cd585b6d6b0e257f6d2156cf7cca` (`(2).mid`).
Meter: `3/4`. Job ID / deployed settings for the user PDF remain unknown.

## Settings used for after renders

| Label | interpretation | algorithm_version | printed_tempo_detail |
|---|---|---|---|
| std+literal | literal | performance-score-1 | expressive (default) |
| std+readable | readable | performance-score-1 | expressive |
| exp+literal | literal | performance-score-2 | expressive |
| exp+readable | readable | performance-score-2 | expressive |

v2 remains opt-in (`--readable-v2` / Experimental).

## Opening (bass MIDI 42 vs RH F MIDI 77)

| Mode | Before delta | After delta |
|---|---:|---:|
| std+literal | 0.125 | 0.125 |
| std+readable | 0.125 | 0.0 (both 0.5) |
| exp+literal | 0.125 | 0.125 |
| exp+readable | 0.125 | 0.0 (both 0.5) |

Score-export re-ingest (`.score.mid`): Readable snaps 3.125 → 3.0 with bass; Literal keeps 3.125.

## Measure-9 Bb (raw `track:0:note:72`)

- Performed duration ~0.26 beats; written duration remains positive (~0.25) for playback/export integrity.
- Readable decision: `ornament_style=acciaccatura`, `editable=true`, primary `track:0:note:73`.
- Literal: no ornament mark.
- Long written hold (score-export Bb at 1.5 beats): not auto-ornamented.

MusicXML grace engraving of ornaments is not yet wired; the interpretation is explicit and editable in decisions / articulation=`ornament`.

## PDF assembly

- `assembleScorePdf` no longer stretches each SVG to the full A4 page.
- Stable print width `PRINT_SVG_WIDTH=720`, half-inch margins, aspect ratio preserved, top-aligned.
- OSMD spacing tightened slightly; bars/system still content-driven (target 3–4 when density permits).

## Printed tempo

- Performance path no longer dumps `preserve_midi_tempo` points onto the page.
- Sparse `printed_tempo` / opening-only when no printed payload.
- Editor control: `printed_tempo_detail` = expressive | opening | off (persisted in notation settings).
- Gradual slowing → `rit.`; discrete plateau → BPM; return → `a tempo`. Playback keeps the full curve.

## Playback decode (after std+readable `.score.mid`)

- Raw attacks: 100. Score MIDI attacks: 108 (ties/splits from engraving; counts alone are not fidelity).
- Opening pair aligned at written beat (score MIDI both ~0.25s at display tempo).
- Short Bb attack near 11.83s retained in score MIDI.
- Timing/origin differ from `(2).mid` vs `.score.mid` as documented in the user review; not assumed equal.

## Tests run

- `tests/test_autumn_walks_readable.py` (paired counterexamples)
- `tests/test_readable_v2_cases.py`, `tests/test_engine_orchestrator.py`, `tests/test_notation_settings.py`
- `tests/test_export_integrity.py`, `tests/test_simple_score.py`, `tests/test_osmd_config.py`
- Frontend: `lib/sheet-pdf.test.ts`, `lib/notation-style.test.ts`

Artifacts under `/tmp/autumn_walks_repro/` (before/after MusicXML + decisions). Not deployed. Musical-quality program not claimed complete.
