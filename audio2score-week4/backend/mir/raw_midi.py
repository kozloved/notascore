"""Write cleaned notes to MIDI without notation quantization."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from mir.types import Hand, MusicalEvent, NoteEvent

PIANO_SPLIT_PITCH = 60
GM_ACOUSTIC_GRAND = 0


def job_raw_midi_path(audio_path: str | Path, job_id: str) -> Path:
    return Path(audio_path).parent / f"bp_{job_id}" / f"{job_id}.raw.mid"


def job_score_midi_path(audio_path: str | Path, job_id: str) -> Path:
    return Path(audio_path).parent / f"bp_{job_id}" / f"{job_id}.score.mid"


def _hand_for_pitch(pitch: int) -> str:
    return "right" if int(pitch) >= PIANO_SPLIT_PITCH else "left"


def write_notes_to_midi(
    notes: list[NoteEvent],
    path: str | Path,
    bpm: float = 120.0,
    *,
    hands: Sequence[str] | None = None,
    pedal_events: Iterable[tuple[float, int]] | None = None,
    split_hands: bool = True,
) -> Path:
    import pretty_midi

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    midi = pretty_midi.PrettyMIDI(initial_tempo=float(bpm) if bpm else 120.0)
    rh = pretty_midi.Instrument(program=GM_ACOUSTIC_GRAND, name="RH")
    lh = pretty_midi.Instrument(program=GM_ACOUSTIC_GRAND, name="LH")
    single = pretty_midi.Instrument(program=GM_ACOUSTIC_GRAND, name="Piano")

    for index, n in enumerate(notes):
        start = float(n.start_time)
        end = max(start + 0.01, float(n.end_time))
        note = pretty_midi.Note(
            velocity=max(1, min(127, int(n.velocity))),
            pitch=int(n.pitch),
            start=start,
            end=end,
        )
        if not split_hands:
            single.notes.append(note)
            continue
        hand = None
        if hands is not None and index < len(hands):
            hand = hands[index]
        if hand not in ("left", "right"):
            hand = _hand_for_pitch(n.pitch)
        (lh if hand == "left" else rh).notes.append(note)

    if split_hands:
        if rh.notes:
            midi.instruments.append(rh)
        if lh.notes:
            midi.instruments.append(lh)
        if not midi.instruments:
            midi.instruments.append(single)
    else:
        midi.instruments.append(single)

    if pedal_events:
        ccs = [
            pretty_midi.ControlChange(
                number=64,
                value=max(0, min(127, int(value))),
                time=max(0.0, float(time_sec)),
            )
            for time_sec, value in pedal_events
        ]
        for inst in midi.instruments:
            inst.control_changes.extend(ccs)

    midi.write(str(out))
    return out


def write_events_to_midi(
    events: list[MusicalEvent],
    path: str | Path,
    bpm: float = 120.0,
    pedal_events: Iterable[tuple[float, int]] | None = None,
) -> Path:
    """Unquantized MIDI from CMR events (seconds via constant tempo)."""
    spb = 60.0 / float(bpm if bpm else 120.0)
    notes: list[NoteEvent] = []
    hands: list[str] = []
    for ev in events:
        start = ev.start_beat * spb
        notes.append(
            NoteEvent(
                pitch=ev.pitch,
                start_time=start,
                end_time=start + ev.duration_beats * spb,
                velocity=ev.velocity,
                confidence=ev.confidence,
            )
        )
        hand = ev.hand.value if isinstance(ev.hand, Hand) else str(ev.hand)
        hands.append(hand)
    return write_notes_to_midi(
        notes,
        path,
        bpm=bpm,
        hands=hands,
        pedal_events=pedal_events,
        split_hands=True,
    )


def write_job_raw_midi(
    audio_path: str | Path,
    job_id: str,
    notes: list[NoteEvent] | None = None,
    bpm: float = 120.0,
    *,
    events: list[MusicalEvent] | None = None,
    pedal_events: Iterable[tuple[float, int]] | None = None,
    split_hands: bool = True,
) -> Path:
    path = job_raw_midi_path(audio_path, job_id)
    if events is not None:
        return write_events_to_midi(events, path, bpm=bpm, pedal_events=pedal_events)
    return write_notes_to_midi(
        notes or [],
        path,
        bpm=bpm,
        pedal_events=pedal_events,
        split_hands=split_hands,
    )
