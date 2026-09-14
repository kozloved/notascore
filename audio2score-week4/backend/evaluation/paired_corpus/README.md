# Paired corpus workflow

Target: **10** licensed recordings first, then **100**. This directory is
tooling and documentation only. It does **not** contain recordings, score
MusicXML, or invented performed-note labels.

Reuse `evaluation/` discovery (`case.yaml`, splits, leakage checks). Put
real cases under `development/`, `holdout/`, `real_world/`, or
`human_reviewed/` — not here.

## Required identity for every case

Each case must identify:

- composition and performance (`composition_id`, `performance_id`)
- audio
- matching score MusicXML (written notation)
- performed-note reference MIDI, when available
- alignment / repeat / cut information
- instrument, meter, and musical challenges
- source and permitted use

Keep every performance or excerpt of the same composition in **one** split.
`check_split_leakage` warns if a `composition_id` or `performance_id`
appears in both development and holdout.

## Score reference vs performed timing

| Artifact | Meaning | Use |
|---|---|---|
| `reference.mid` / `reference.kind: performed` | Actual performed onsets and durations | Transcription F1, preservation |
| `score.musicxml` | Written notation, including repeats as written | Notation / readability only |
| `alignment` | Repeats, cuts, ornaments, expressive timing map | Join the two views |

Do **not** compare audio onsets directly against an unaligned score MIDI.
Ornaments, repeats, and rubato make that comparison false.

## Manifest template

See `template.case.yaml`. Copy it into a split directory once audio and
references are legally available.

## Initial ten slots

Tracked in `evaluation.paired_corpus.INITIAL_SLOTS`. Families 1–6 reuse the
existing human-reviewed checklist (`rubato`, `ornaments`, `pedal`,
`repeated_notes`, `meter_changes`) plus a simple-meter piano case. Slots
7–10 cover high piano, bass, quiet passages, and polyphonic piano.

**Current status:** every slot is missing audio, performed-note MIDI, score
MusicXML, alignment, and license metadata. Inventory:

```
python -m evaluation.paired_corpus
```

No quality gain is claimed while those inputs are missing.
