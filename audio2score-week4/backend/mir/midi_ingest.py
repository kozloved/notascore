"""Load a MIDI file into CMR notes + TempoMap (no audio transcription)."""

from __future__ import annotations

import re
import io
from dataclasses import dataclass
from pathlib import Path

from mir.types import Hand, NoteEvent, TempoMap, TempoPoint
from mir.performance import PerformanceSnapshot, snapshot_midi

# New ingest pairs each note-off with the oldest unmatched same-pitch
# note-on (FIFO). pretty_midi closes every open unison on the first off,
# which is why overlapping re-attacks used to ingest as a quarter plus
# leftover 32nds. Stored PerformanceSnapshots are not rewritten.
NOTE_PAIRING_FIFO = "fifo_same_pitch"

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


class NoPitchedNotesError(ValueError):
    """MIDI parsed, but no pitched (non-drum) notes were present.

    Distinct from malformed MIDI or transport failures. Callers that fall back
    to another AMT backend should match this type, not exception text.
    """

    def __init__(
        self,
        message: str = "No pitched notes found in MIDI file",
        *,
        midi_bytes: bytes | None = None,
        performance: PerformanceSnapshot | None = None,
        provider_raw_sha256: str | None = None,
        reason: str = "empty",
        source_path: str = "",
    ):
        super().__init__(message)
        self.midi_bytes = midi_bytes
        self.performance = performance
        self.provider_raw_sha256 = provider_raw_sha256
        self.reason = reason
        self.source_path = source_path


@dataclass
class IngestedMidi:
    notes: list[NoteEvent]
    tempo_map: TempoMap
    pedal_events: list[tuple[float, int]]
    time_sig_hint: str | None = None
    key_hint: str | None = None
    source_path: str = ""
    performance: PerformanceSnapshot | None = None


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


def _key_hint(midi) -> str | None:
    changes = getattr(midi, "key_signature_changes", None) or []
    if not changes:
        return None
    key_number = getattr(changes[0], "key_number", None)
    if key_number is None:
        return None
    try:
        import pretty_midi

        name = pretty_midi.key_number_to_key_name(int(key_number))
    except Exception:
        return None
    if not name:
        return None
    token = str(name).split()[0]
    return token or None


def fifo_notes_from_midi_bytes(data: bytes, midi) -> list[dict]:
    """Parse pitched note intervals with FIFO same-pitch pairing.

    ``midi`` is a PrettyMIDI object used only for tick-to-seconds. Drum
    channel 10 (MIDI channel 9) is tagged but still paired.
    """
    from collections import defaultdict, deque

    import mido

    mid = mido.MidiFile(file=io.BytesIO(data))
    notes: list[dict] = []
    for track_idx, track in enumerate(mid.tracks):
        abs_tick = 0
        programs = [0] * 16
        stacks: dict[tuple[int, int], deque] = defaultdict(deque)
        for msg in track:
            abs_tick += int(getattr(msg, "time", 0) or 0)
            if msg.type == "program_change":
                programs[int(msg.channel)] = int(msg.program)
                continue
            if msg.type == "note_on" and int(msg.velocity) > 0:
                stacks[(int(msg.channel), int(msg.note))].append(
                    (abs_tick, int(msg.velocity), programs[int(msg.channel)])
                )
                continue
            if msg.type != "note_off" and not (msg.type == "note_on" and int(msg.velocity) == 0):
                continue
            key = (int(msg.channel), int(msg.note))
            if not stacks[key]:
                continue
            start_tick, velocity, program = stacks[key].popleft()
            start = float(midi.tick_to_time(start_tick))
            end = float(midi.tick_to_time(abs_tick))
            if end <= start:
                continue
            notes.append(
                {
                    "track": track_idx,
                    "channel": key[0],
                    "program": program,
                    "pitch": key[1],
                    "start": start,
                    "end": end,
                    "velocity": velocity,
                    "is_drum": key[0] == 9,
                }
            )
    return notes


def tagged_pedal_events(performance) -> list[tuple[float, int, str]]:
    """CC64 events labeled by source track. Empty when the snapshot has none."""
    rows: list[tuple[float, int, str]] = []
    for track in getattr(performance, "tracks", ()) or ():
        for item in track.controls:
            if len(item) < 3 or int(item[1]) != 64:
                continue
            rows.append((float(item[0]), max(0, min(127, int(item[2]))), str(track.track_id)))
    rows.sort(key=lambda row: (row[0], row[2]))
    return rows


def ingest_midi(path: str | Path, *, source_backend="midi") -> IngestedMidi:
    import pretty_midi

    midi_path = Path(path)
    try:
        data = midi_path.read_bytes()
        midi = pretty_midi.PrettyMIDI(io.BytesIO(data))
    except Exception as exc:
        raise ValueError(f"Could not read MIDI file: {exc}") from exc

    performance = snapshot_midi(midi, data, backend=source_backend)
    notes = performance.to_notes()
    pedal: list[tuple[float, int]] = []

    for inst in midi.instruments:
        if inst.is_drum:
            continue
        for cc in inst.control_changes:
            if int(cc.number) == 64:
                pedal.append((float(cc.time), max(0, min(127, int(cc.value)))))

    if not notes:
        drum_count = sum(1 for n in performance.notes if n.is_drum)
        reason = "drum_only" if drum_count else "empty"
        raise NoPitchedNotesError(
            "No pitched notes found in MIDI file",
            midi_bytes=data,
            performance=performance,
            provider_raw_sha256=performance.midi_sha256,
            reason=reason,
            source_path=str(midi_path),
        )

    notes.sort(key=lambda n: (n.start_time, n.pitch))
    pedal.sort(key=lambda p: p[0])

    return IngestedMidi(
        notes=notes,
        tempo_map=tempo_map_from_pretty_midi(midi),
        pedal_events=pedal,
        time_sig_hint=_time_sig_hint(midi),
        key_hint=_key_hint(midi),
        source_path=str(midi_path),
        performance=performance,
    )
