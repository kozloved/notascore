# Human-reviewed recordings

This split is for musician-reviewed performances, not the mechanical export
gate. Acoustic correctness and score readability are scored as **separate**
tracks. A case can pass export checks and still fail readability.

Do not commit copyrighted recordings. Generate the repo-safe MIDI fixtures
with:

```
python -m evaluation.human_review --prepare --root evaluation/human_reviewed
python -m evaluation.human_review --root evaluation/human_reviewed
```

## Required families

| Case | What to review |
|---|---|
| `rubato` | Tempo flexibility; bar alignment vs performed time |
| `ornaments` | Grace / crushed notes stay in the acoustic set |
| `pedal` | Sustain pedal; written duration vs ringing |
| `repeated_notes` | Same-pitch reattacks are not merged |
| `meter_changes` | 4/4 → 3/4 (or similar); do not hide behind a single meter |

## Tracks

1. **acoustic** — performed reference vs transcribed notes in seconds.
2. **readability** — notation plan metrics and the human rubric (rests, ties,
   voices, meter). Independent of F1.
3. **export** — mechanical MusicXML/MIDI identity, timelines, no fallback.

Human ratings live in `review.json` beside each case (optional until a
musician fills them in). Automated runs never invent a "beautiful score"
score from export F1.
