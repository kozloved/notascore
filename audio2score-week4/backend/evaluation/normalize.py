"""Normalize reference MIDI into comparable musical note events.

Never mutates the original MIDI file on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mir.midi_ingest import ingest_midi
from mir.types import Hand, NoteEvent


@dataclass
class NormalizedReference:
    """In-memory ground truth derived from a reference MIDI."""

    notes: list[NoteEvent]
    tempo_bpm: float | None = None
    time_signature: str | None = None
    has_hand_labels: bool = False
    track_count: int = 0
    source_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "note_count": len(self.notes),
            "tempo_bpm": self.tempo_bpm,
            "time_signature": self.time_signature,
            "has_hand_labels": self.has_hand_labels,
            "track_count": self.track_count,
            "source_path": self.source_path,
            "hands": {
                "left": sum(1 for n in self.notes if n.hand == Hand.LEFT),
                "right": sum(1 for n in self.notes if n.hand == Hand.RIGHT),
                "unknown": sum(
                    1
                    for n in self.notes
                    if n.hand not in (Hand.LEFT, Hand.RIGHT)
                ),
            },
        }


def normalize_reference_midi(path: str | Path) -> NormalizedReference:
    """Load reference MIDI into NoteEvents (pitch + onset/offset seconds + optional hands)."""
    midi_path = Path(path)
    ingested = ingest_midi(midi_path)

    # Track count via pretty_midi without rewriting the file
    track_count = 0
    try:
        import pretty_midi

        pm = pretty_midi.PrettyMIDI(str(midi_path))
        track_count = sum(1 for inst in pm.instruments if not inst.is_drum)
    except Exception:
        track_count = 0

    labeled = sum(1 for n in ingested.notes if n.hand in (Hand.LEFT, Hand.RIGHT))
    tempo = None
    if ingested.tempo_map is not None and ingested.tempo_map.points:
        tempo = float(ingested.tempo_map.bpm_at(0.0))

    return NormalizedReference(
        notes=list(ingested.notes),
        tempo_bpm=tempo,
        time_signature=ingested.time_sig_hint,
        has_hand_labels=labeled > 0,
        track_count=track_count,
        source_path=str(midi_path.resolve()),
        extra={"pedal_events": len(ingested.pedal_events)},
    )
