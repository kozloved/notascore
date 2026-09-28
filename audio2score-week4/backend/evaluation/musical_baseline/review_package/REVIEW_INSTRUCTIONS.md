# P1 musical baseline — review instructions

## Purpose

Assess short examples on **four independent dimensions**. Do not collapse them
into one pass/fail. Export success is not musical quality.

## Dimensions

1. **Acoustic accuracy** — only when suitable audio and reference labels exist.
   Most synthetic package cases mark this `not_applicable`.
2. **Musical interpretation accuracy** — meter, pickup, voices, rests,
   articulation, duration spelling.
3. **Export integrity** — mechanical MusicXML/MIDI identity (may be pre-filled).
4. **Human correction effort** — minutes/edits to make the score usable.

Unreviewed dimensions must stay unreviewed. Do not invent scores.

## How to review

1. Open each case under `development/` or `held_out/`.
2. Play `v1.score.mid` / `v2.score.mid` when present.
3. Open `v1.musicxml` / `v2.musicxml` (and OSMD HTML if generated with `--render`).
4. Use `note_index.json` and phrase extracts; cite `source_note_id`.
5. Fill `REVIEW_FORM.md` and copy attribution + ratings into `review.json`.

## Contracts

- Default remains `performance-score-1`; `performance-score-2` is opt-in.
- Preserve original MIDI bytes, source identities, performed timing, tuplets,
  ties, accepted corrections, and user locks.
- Compare staff, musical-voice grouping, and printed lanes separately.
- Do not retune the engine merely because case 138 printed lanes move.

## Attribution required

Every completed review needs reviewer name, date, and which dimensions were
actually assessed. Gaps stay listed in `inventory.json`.
