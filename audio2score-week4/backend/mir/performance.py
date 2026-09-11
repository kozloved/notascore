"""Immutable acoustic evidence, independent of mutable interpretation events.

The MIDI checksum identifies the original bytes, which must be retained
separately. This JSON model is an analysis view, not a lossless MIDI serializer.
Track IDs identify PrettyMIDI instrument streams (not original SMF chunk indices).
"""

from dataclasses import asdict, dataclass
import hashlib
import json
from math import isfinite
from pathlib import Path

from mir.types import Hand, InstrumentKind, NoteEvent


def instrument_for_program(program: int) -> InstrumentKind:
    if 0 <= program <= 7:
        return InstrumentKind.PIANO
    if 16 <= program <= 23:
        return InstrumentKind.ORGAN
    if 24 <= program <= 31:
        return InstrumentKind.GUITAR
    if 32 <= program <= 39:
        return InstrumentKind.BASS
    if 40 <= program <= 51:
        return InstrumentKind.STRINGS
    if 52 <= program <= 54:
        return InstrumentKind.VOICE
    if 56 <= program <= 63:
        return InstrumentKind.BRASS
    if 64 <= program <= 79:
        return InstrumentKind.WINDS
    return InstrumentKind.UNKNOWN


@dataclass(frozen=True)
class SourceNote:
    note_id: str
    pitch: int
    start_sec: float
    end_sec: float
    velocity: int
    confidence: float
    track_id: str = ""
    program: int | None = None
    is_drum: bool = False
    instrument: str = "unknown"
    hand_hint: str = "unknown"


@dataclass(frozen=True)
class SourceTrack:
    track_id: str
    program: int
    name: str
    is_drum: bool
    # time, controller number, value; time, bend value
    controls: tuple[tuple[float, int, int], ...] = ()
    pitch_bends: tuple[tuple[float, int], ...] = ()


@dataclass(frozen=True)
class PerformanceSnapshot:
    source_backend: str
    notes: tuple[SourceNote, ...]
    tracks: tuple[SourceTrack, ...] = ()
    tempo_changes: tuple[tuple[float, float], ...] = ()
    meter_changes: tuple[tuple[float, int, int], ...] = ()
    midi_sha256: str | None = None
    schema_version: int = 1

    def __post_init__(self):
        if self.schema_version != 1:
            raise ValueError("Unsupported performance schema version")
        if any(not isinstance(value, tuple) for value in (
                self.notes, self.tracks, self.tempo_changes, self.meter_changes)):
            raise TypeError("Performance collections must be immutable tuples")
        ids = [n.note_id for n in self.notes]
        if any(not ident for ident in ids) or len(ids) != len(set(ids)):
            raise ValueError("Source note IDs must be nonempty and unique")
        for n in self.notes:
            if (not all(isfinite(v) for v in (n.start_sec, n.end_sec, n.confidence))
                    or n.start_sec < 0 or n.end_sec <= n.start_sec
                    or not 0 <= n.pitch <= 127 or not 1 <= n.velocity <= 127):
                raise ValueError(f"Invalid source note: {n.note_id}")

    @classmethod
    def from_notes(cls, notes, backend):
        return cls(backend, tuple(SourceNote(
            n.ensure_ids(i).note_id, n.pitch, n.start_time, n.end_time,
            n.velocity, n.confidence, n.source_track_id, n.source_program,
            instrument=n.instrument.value, hand_hint=n.hand.value,
        ) for i, n in enumerate(notes)))

    def to_notes(self):
        return [NoteEvent(
            n.pitch, n.start_sec, n.end_sec, n.velocity, n.confidence,
            hand=Hand(n.hand_hint), note_id=n.note_id,
            source_backend=self.source_backend,
            original_start_time=n.start_sec, original_end_time=n.end_sec,
            source_track_id=n.track_id, source_program=n.program,
            instrument=InstrumentKind(n.instrument),
            hand_locked=n.hand_hint in ("left", "right"),
        ) for n in self.notes if not n.is_drum]

    def write_json(self, path):
        Path(path).write_text(json.dumps(asdict(self), indent=2, allow_nan=False) + "\n",
                              encoding="utf-8")

    @classmethod
    def read_json(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["notes"] = tuple(SourceNote(**n) for n in data["notes"])
        data["tracks"] = tuple(SourceTrack(
            **{**t, "controls": tuple(tuple(c) for c in t["controls"]),
               "pitch_bends": tuple(tuple(b) for b in t["pitch_bends"])}
        ) for t in data["tracks"])
        for key in ("tempo_changes", "meter_changes"):
            data[key] = tuple(tuple(item) for item in data[key])
        return cls(**data)

    def verify_midi(self, data: bytes):
        if self.midi_sha256 is None or hashlib.sha256(data).hexdigest() != self.midi_sha256:
            raise ValueError("Original MIDI checksum mismatch")


def snapshot_midi(midi, data: bytes, *, backend="midi"):
    from mir.midi_ingest import hand_from_track_name

    tracks, notes = [], []
    for ti, inst in enumerate(midi.instruments):
        track = f"track:{ti}"
        kind = InstrumentKind.DRUMS if inst.is_drum else instrument_for_program(inst.program)
        hand = hand_from_track_name(inst.name) if kind == InstrumentKind.PIANO else Hand.UNKNOWN
        tracks.append(SourceTrack(track, int(inst.program), inst.name, bool(inst.is_drum),
                                  tuple((float(c.time), int(c.number), int(c.value)) for c in inst.control_changes),
                                  tuple((float(b.time), int(b.pitch)) for b in inst.pitch_bends)))
        for ni, note in enumerate(inst.notes):
            notes.append(SourceNote(f"{track}:note:{ni}", int(note.pitch), float(note.start), float(note.end),
                                    int(note.velocity), 1.0, track, int(inst.program), bool(inst.is_drum),
                                    kind.value, hand.value))
    times, bpms = midi.get_tempo_changes()
    return PerformanceSnapshot(
        backend, tuple(notes), tuple(tracks),
        tuple((float(t), float(b)) for t, b in zip(times, bpms)),
        tuple((float(t.time), int(t.numerator), int(t.denominator)) for t in midi.time_signature_changes),
        hashlib.sha256(data).hexdigest(),
    )
