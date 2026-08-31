"""Write cleaned notes to MIDI without notation quantization."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from mir.types import Hand, MusicalEvent, NoteEvent, TempoMap, TempoPoint

PIANO_SPLIT_PITCH = 60
GM_ACOUSTIC_GRAND = 0


def job_raw_midi_path(audio_path: str | Path, job_id: str) -> Path:
    return Path(audio_path).parent / f"bp_{job_id}" / f"{job_id}.raw.mid"


def job_validated_midi_path(audio_path: str | Path, job_id: str) -> Path:
    return Path(audio_path).parent / f"bp_{job_id}" / f"{job_id}.validated.mid"


def job_score_midi_path(audio_path: str | Path, job_id: str) -> Path:
    return Path(audio_path).parent / f"bp_{job_id}" / f"{job_id}.score.mid"


def job_notation_midi_path(audio_path: str | Path, job_id: str) -> Path:
    """Alias of the notation-stage MIDI (readable score, not performance)."""
    return job_score_midi_path(audio_path, job_id)


def _hand_for_pitch(pitch: int) -> str:
    return "right" if int(pitch) >= PIANO_SPLIT_PITCH else "left"


def _hand_value(hand) -> str:
    if isinstance(hand, Hand):
        return hand.value
    return str(hand)


def hands_aligned_with_notes(
    notes: list[NoteEvent], events: list[MusicalEvent]
) -> list[str]:
    """Match MIR hand labels onto original (seconds) notes by pitch/order."""
    if not notes:
        return []
    if len(notes) != len(events):
        return [_hand_for_pitch(n.pitch) for n in notes]
    note_order = sorted(range(len(notes)), key=lambda i: (notes[i].start_time, notes[i].pitch))
    event_order = sorted(events, key=lambda e: (e.start_beat, e.pitch))
    hands = [_hand_for_pitch(n.pitch) for n in notes]
    for index, ev in zip(note_order, event_order):
        hand = _hand_value(ev.hand)
        if hand in ("left", "right"):
            hands[index] = hand
    return hands


def apply_tempo_changes(midi, tempo_map: TempoMap | None, fallback_bpm: float = 120.0) -> None:
    """Write a tempo track without changing note times in seconds."""
    points: list[TempoPoint]
    if tempo_map and tempo_map.points:
        points = tempo_map.sorted_points()
    else:
        points = [
            TempoPoint(
                time_sec=0.0,
                beat=0.0,
                bpm=float(fallback_bpm) if fallback_bpm else 120.0,
            )
        ]
    if points[0].time_sec > 1e-6:
        points = [
            TempoPoint(
                time_sec=0.0,
                beat=0.0,
                bpm=points[0].bpm,
                confidence=points[0].confidence,
            )
        ] + points

    resolution = midi.resolution
    first_bpm = max(1.0, float(points[0].bpm) if points[0].bpm else 120.0)
    last_tick = 0.0
    last_scale = 60.0 / (first_bpm * resolution)
    previous_time = 0.0
    tick_scales = [(0, last_scale)]
    last_time = 0.0
    for pt in points[1:]:
        tempo = max(1.0, float(pt.bpm) if pt.bpm else first_bpm)
        tick = last_tick + max(0.0, pt.time_sec - previous_time) / last_scale
        tick_scale = 60.0 / (tempo * resolution)
        if abs(tick_scale - last_scale) / max(last_scale, 1e-12) < 0.01:
            continue
        tick_i = int(round(tick))
        if tick_i == tick_scales[-1][0]:
            tick_scales[-1] = (tick_i, tick_scale)
        else:
            tick_scales.append((tick_i, tick_scale))
        previous_time = pt.time_sec
        last_time = pt.time_sec
        last_tick, last_scale = tick, tick_scale

    midi._tick_scales = tick_scales
    end = 0.0
    try:
        end = float(midi.get_end_time())
    except Exception:
        end = last_time
    extra = max(0.0, end - last_time) / last_scale if last_scale else 0.0
    max_tick = int(max(tick_scales[-1][0] + 1, last_tick + extra + 1))
    midi._update_tick_to_time(max_tick)


def write_notes_to_midi(
    notes: list[NoteEvent],
    path: str | Path,
    bpm: float = 120.0,
    *,
    hands: Sequence[str] | None = None,
    pedal_events: Iterable[tuple[float, int]] | None = None,
    split_hands: bool = True,
    tempo_map: TempoMap | None = None,
) -> Path:
    import pretty_midi

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    initial = float(bpm) if bpm else 120.0
    if tempo_map and tempo_map.points:
        initial = float(tempo_map.bpm_at(0.0)) or initial

    midi = pretty_midi.PrettyMIDI(initial_tempo=initial)
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

    apply_tempo_changes(midi, tempo_map, fallback_bpm=initial)
    midi.write(str(out))
    return out


def write_events_to_midi(
    events: list[MusicalEvent],
    path: str | Path,
    bpm: float = 120.0,
    pedal_events: Iterable[tuple[float, int]] | None = None,
    tempo_map: TempoMap | None = None,
) -> Path:
    """Unquantized MIDI from CMR events (seconds via tempo map when given)."""
    notes: list[NoteEvent] = []
    hands: list[str] = []
    spb = 60.0 / float(bpm if bpm else 120.0)
    for ev in events:
        if tempo_map is not None:
            start = tempo_map.beats_to_seconds(ev.start_beat)
            end = tempo_map.beats_to_seconds(ev.start_beat + ev.duration_beats)
        else:
            start = ev.start_beat * spb
            end = start + ev.duration_beats * spb
        notes.append(
            NoteEvent(
                pitch=ev.pitch,
                start_time=start,
                end_time=end,
                velocity=ev.velocity,
                confidence=ev.confidence,
            )
        )
        hands.append(_hand_value(ev.hand))
    return write_notes_to_midi(
        notes,
        path,
        bpm=bpm,
        hands=hands,
        pedal_events=pedal_events,
        split_hands=True,
        tempo_map=tempo_map,
    )


def write_job_stage_midi(
    path: Path,
    notes: list[NoteEvent],
    bpm: float = 120.0,
    *,
    pedal_events: Iterable[tuple[float, int]] | None = None,
    split_hands: bool = False,
    tempo_map: TempoMap | None = None,
) -> Path:
    return write_notes_to_midi(
        notes,
        path,
        bpm=bpm,
        pedal_events=pedal_events,
        split_hands=split_hands,
        tempo_map=tempo_map,
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
    tempo_map: TempoMap | None = None,
) -> Path:
    path = job_raw_midi_path(audio_path, job_id)
    if notes is not None and events is not None:
        return write_notes_to_midi(
            notes,
            path,
            bpm=bpm,
            hands=hands_aligned_with_notes(notes, events),
            pedal_events=pedal_events,
            split_hands=split_hands,
            tempo_map=tempo_map,
        )
    if events is not None:
        return write_events_to_midi(
            events,
            path,
            bpm=bpm,
            pedal_events=pedal_events,
            tempo_map=tempo_map,
        )
    return write_notes_to_midi(
        notes or [],
        path,
        bpm=bpm,
        pedal_events=pedal_events,
        split_hands=split_hands,
        tempo_map=tempo_map,
    )
