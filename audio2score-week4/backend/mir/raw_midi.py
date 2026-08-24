"""Write cleaned NoteEvent lists to MIDI without notation quantization."""

from __future__ import annotations

from pathlib import Path

from mir.types import NoteEvent


def job_raw_midi_path(audio_path: str | Path, job_id: str) -> Path:
    return Path(audio_path).parent / f"bp_{job_id}" / f"{job_id}.raw.mid"


def write_notes_to_midi(
    notes: list[NoteEvent],
    path: str | Path,
    bpm: float = 120.0,
) -> Path:
    import pretty_midi

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    midi = pretty_midi.PrettyMIDI(initial_tempo=float(bpm) if bpm else 120.0)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    for n in notes:
        start = float(n.start_time)
        end = max(start + 0.01, float(n.end_time))
        inst.notes.append(
            pretty_midi.Note(
                velocity=max(1, min(127, int(n.velocity))),
                pitch=int(n.pitch),
                start=start,
                end=end,
            )
        )
    midi.instruments.append(inst)
    midi.write(str(out))
    return out


def write_job_raw_midi(
    audio_path: str | Path,
    job_id: str,
    notes: list[NoteEvent],
    bpm: float = 120.0,
) -> Path:
    path = job_raw_midi_path(audio_path, job_id)
    return write_notes_to_midi(notes, path, bpm=bpm)
