"""MIDI time conversion audit helpers (Checkpoint 9B).

NotaScore loads reference MIDI via pretty_midi, which converts ticks→seconds
using the file's tempo map. This module documents and tests that conversion
without changing production ingest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import pretty_midi

from mir.midi_ingest import ingest_midi, tempo_map_from_pretty_midi
from mir.types import NoteEvent


CONVERSION_METHOD_DOC = """
MIDI time conversion method (production path)
=============================================

1. evaluation.normalize.normalize_reference_midi(path)
2. → mir.midi_ingest.ingest_midi(path)
3. → pretty_midi.PrettyMIDI(path)
4. NoteEvent.start_time / end_time = float(pretty_midi.Note.start / .end)

pretty_midi converts MIDI ticks to seconds using:
  - the file's tempo map (set_tempo / tempo change events)
  - resolution (ticks per quarter note / PPQ)

There is NO application-level tick→seconds math for note matching.
TempoMap built by tempo_map_from_pretty_midi is used later for
notation/beats, NOT for onset+pitch F1.

Implication: if a DAW exports note ticks at musical tempo T but embeds
a wrong tempo meta (e.g. 120), pretty_midi seconds are stretched by
(T_meta / T_true) relative to audio.
"""


@dataclass
class MidiTimingAudit:
    path: str
    resolution_ppq: int
    tempo_events: list[tuple[float, float]]  # (time_sec, bpm)
    note_count: int
    first_onset_sec: float | None
    last_offset_sec: float | None
    duration_sec: float
    ticks_of_first_note: int | None
    conversion_method: str = "pretty_midi_Note.start_seconds"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_midi_file(path: str | Path) -> MidiTimingAudit:
    """Inspect tempo map and note timing of a MIDI file via pretty_midi."""
    midi_path = Path(path)
    pm = pretty_midi.PrettyMIDI(str(midi_path))
    times, tempi = pm.get_tempo_changes()
    tempo_events = [
        (float(t), float(b)) for t, b in zip(times.tolist(), tempi.tolist())
    ]
    notes = [n for inst in pm.instruments if not inst.is_drum for n in inst.notes]
    notes.sort(key=lambda n: (n.start, n.pitch))
    first = float(notes[0].start) if notes else None
    last = float(notes[-1].end) if notes else None
    duration = float(last - first) if notes and first is not None and last is not None else 0.0
    # Recover ticks of first note if possible via internal mapping
    ticks_first = None
    if notes:
        try:
            # pretty_midi stores seconds; estimate ticks via tempo at start
            bpm = float(tempi[0]) if len(tempi) else 120.0
            ticks_first = int(round(first * (bpm / 60.0) * pm.resolution))
        except Exception:
            ticks_first = None
    return MidiTimingAudit(
        path=str(midi_path.resolve()),
        resolution_ppq=int(pm.resolution),
        tempo_events=tempo_events,
        note_count=len(notes),
        first_onset_sec=first,
        last_offset_sec=last,
        duration_sec=duration if notes else float(pm.get_end_time()),
        ticks_of_first_note=ticks_first,
    )


def write_constant_tempo_midi(
    path: Path,
    notes: Sequence[tuple[int, float, float]],
    *,
    bpm: float,
    resolution: int = 220,
) -> Path:
    """Write a MIDI whose absolute note seconds are known at ``bpm``.

    Uses pretty_midi with initial_tempo so round-trip ingest must recover
    the same absolute seconds (within floating tolerance).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pm = pretty_midi.PrettyMIDI(initial_tempo=float(bpm), resolution=resolution)
    inst = pretty_midi.Instrument(program=0, name="Test")
    for pitch, start, end in notes:
        inst.notes.append(
            pretty_midi.Note(
                velocity=80,
                pitch=int(pitch),
                start=float(start),
                end=float(end),
            )
        )
    pm.instruments.append(inst)
    pm.write(str(path))
    return path


def write_tempo_change_midi(
    path: Path,
    *,
    bpm_a: float,
    bpm_b: float,
    change_at_sec: float,
    notes: Sequence[tuple[int, float, float]],
    resolution: int = 220,
) -> Path:
    """Write MIDI with a tempo change; notes given in absolute seconds."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pm = pretty_midi.PrettyMIDI(initial_tempo=float(bpm_a), resolution=resolution)
    # Inject tempo change via pretty_midi internals (seconds-based)
    # Create a tempo change event at change_at_sec
    pm._tick_scales = [(0, 60.0 / (float(bpm_a) * pm.resolution))]
    change_tick = int(round(change_at_sec / (60.0 / (float(bpm_a) * pm.resolution))))
    pm._tick_scales.append(
        (change_tick, 60.0 / (float(bpm_b) * pm.resolution))
    )
    pm._update_tick_to_time(max(change_tick, 1))
    inst = pretty_midi.Instrument(program=0, name="Test")
    for pitch, start, end in notes:
        inst.notes.append(
            pretty_midi.Note(
                velocity=80,
                pitch=int(pitch),
                start=float(start),
                end=float(end),
            )
        )
    pm.instruments.append(inst)
    # Ensure tempo change table is consistent after write/read by also
    # setting start tempos via remove_invalid_notes path; rewrite via ticks.
    pm.write(str(path))
    return path


def load_notes_seconds(path: str | Path) -> list[NoteEvent]:
    """Production-equivalent note load (ingest_midi → seconds)."""
    return list(ingest_midi(path).notes)


def tempo_events_dict(path: str | Path) -> list[dict[str, float]]:
    audit = audit_midi_file(path)
    return [{"time_sec": t, "bpm": b} for t, b in audit.tempo_events]


def conversion_method_doc() -> str:
    return CONVERSION_METHOD_DOC
