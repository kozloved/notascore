# Real-sample review checklist

Use this for **live job** evidence destined for musician review. Reuses the
existing evaluation package / `review.json` structures — no new review app.

Keep synthetic package cases labeled `synthetic_repo_fixture`. Do not bind
older reviews to rebuilt artifact hashes without re-review.

## Per sample

| Field | Value |
|---|---|
| Job ID | |
| Engine commit / version evidence | |
| Algorithm (`performance-score-1` / `performance-score-2`) | |
| Original audio (path or storage key) | |
| Unedited output (MusicXML + score MIDI + playback) | |
| Corrected output (after edits; same IDs) | |
| Timestamp / measure cited | |
| Edits applied (`source_note_id` + fields) | |
| Correction time (minutes) | |
| Reviewer + `reviewed_at` (ISO) | |

## Workflow

1. Record engine SHA and job ID before exporting artifacts.
2. Save unedited MusicXML, score MIDI, and original audio alongside the job.
3. Apply corrections; save corrected exports without rewriting source MIDI.
4. Cite measure/timestamp and list each edit by `source_note_id`.
5. Fill `review.json` attribution + interpretation + correction-effort
   dimensions (same schema as the synthetic package).
6. Run report-only validation against live hashes:
   `python -m evaluation.musical_baseline --report-reviews …`
7. Mark acoustic accuracy only when audio + reference labels exist.

## Limits

- Synthetic fixtures do not prove acoustic accuracy or P1 completion.
- P1 remains incomplete until attributed real reviews exist.
- Default remains v1; v2 stays opt-in.
