"""Load a MIDI file into CMR notes + TempoMap (no audio transcription)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from mir.types import Hand, NoteEvent, TempoMap, TempoPoint

MIDI_EXTENSIONS = {".mid", ".midi"}
MIDI_CONTENT_TYPES = {
    "audio/midi",
    "audio/mid",
    "audio/x-midi",
    "audio/sp-midi",
    "application/midi",
    "application/x-midi",
    "application/octet-stream",
    "binary/octet-stream",
}

_RH_TOKENS = {"rh", "r.h", "r.h.", "right", "treble"}
_LH_TOKENS = {"lh", "l.h", "l.h.", "left", "bass"}


def is_midi_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in MIDI_EXTENSIONS


def is_midi_upload(filename: str, content_type: str | None = None) -> bool:
    suffix = Path(filename).suffix.lower()
    if suffix in MIDI_EXTENSIONS:
        return True
    ctype = (content_type or "").lower()
    return ctype in MIDI_CONTENT_TYPES and suffix == ""


@dataclass
class IngestedMidi:
    notes: list[NoteEvent]
    tempo_map: TempoMap
    pedal_events: list[tuple[float, int]]
    time_sig_hint: str | None = None
    source_path: str = ""


def _tokens(name: str) -> set[str]:
    return set(re.split(r"[\s_\-/]+", (name or "").lower().strip()))


def hand_from_track_name(name: str) -> Hand:
    tokens = _tokens(name)
    if tokens & _RH_TOKENS:
        return Hand.RIGHT
    if tokens & _LH_TOKENS:
        return Hand.LEFT
    lowered = (name or "").lower()
    if "right" in lowered or "treble" in lowered:
        return Hand.RIGHT
    if "left" in lowered or re.search(r"\bbass\b", lowered):
        return Hand.LEFT
    return Hand.UNKNOWN


def tempo_map_from_pretty_midi(midi) -> TempoMap:
    times, tempi = midi.get_tempo_changes()
    if len(tempi) == 0:
        return TempoMap(
            points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0, confidence=0.5)]
        )
    points: list[TempoPoint] = []
    beat = 0.0
    prev_t = 0.0
    prev_bpm = float(tempi[0]) if float(tempi[0]) else 120.0
    for time_sec, bpm in zip(times, tempi):
        t = max(0.0, float(time_sec))
        b = float(bpm) if bpm else prev_bpm
        if t > prev_t:
            beat += (t - prev_t) * (prev_bpm / 60.0)
        points.append(TempoPoint(time_sec=t, beat=beat, bpm=b, confidence=1.0))
        prev_t, prev_bpm = t, b
    if points[0].time_sec > 1e-6:
        points.insert(
            0,
            TempoPoint(
                time_sec=0.0,
                beat=0.0,
                bpm=points[0].bpm,
                confidence=points[0].confidence,
            ),
        )
    else:
        points[0] = TempoPoint(
            time_sec=0.0,
            beat=0.0,
            bpm=points[0].bpm,
            confidence=points[0].confidence,
        )
    return TempoMap(points=points)


def _time_sig_hint(midi) -> str | None:
    changes = getattr(midi, "time_signature_changes", None) or []
    if not changes:
        return None
    ts = changes[0]
    num = getattr(ts, "numerator", None)
    den = getattr(ts, "denominator", None)
    if num and den:
        return f"{int(num)}/{int(den)}"
    return None


def ingest_midi(path: str | Path) -> IngestedMidi:
    import pretty_midi

    midi_path = Path(path)
    try:
        midi = pretty_midi.PrettyMIDI(str(midi_path))
    except Exception as exc:
        raise ValueError(f"Could not read MIDI file: {exc}") from exc

    notes: list[NoteEvent] = []
    pedal: list[tuple[float, int]] = []
    named_hands = 0

    for inst in midi.instruments:
        if inst.is_drum:
            continue
        hand = hand_from_track_name(inst.name or "")
        if hand != Hand.UNKNOWN:
            named_hands += 1
        for n in inst.notes:
            start = float(n.start)
            end = max(start + 0.01, float(n.end))
            notes.append(
                NoteEvent(
                    pitch=int(n.pitch),
                    start_time=start,
                    end_time=end,
                    velocity=max(1, min(127, int(n.velocity))),
                    confidence=1.0,
                    hand=hand,
                )
            )
        for cc in inst.control_changes:
            if int(cc.number) == 64:
                pedal.append((float(cc.time), max(0, min(127, int(cc.value)))))

    if not notes:
        raise ValueError("No pitched notes found in MIDI file")

    notes.sort(key=lambda n: (n.start_time, n.pitch))
    pedal.sort(key=lambda p: p[0])

    return IngestedMidi(
        notes=notes,
        tempo_map=tempo_map_from_pretty_midi(midi),
        pedal_events=pedal,
        time_sig_hint=_time_sig_hint(midi),
        source_path=str(midi_path),
    )
