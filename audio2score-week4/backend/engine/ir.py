"""Derived interpretation records. Source notes stay immutable."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class NoteEvidence:
    backend: str
    onset_sec: float
    offset_sec: float
    confidence: float = 1.0
    stem_id: str = ""
    model_version: str = ""
    pitch: int | None = None


@dataclass
class InterpretedNote:
    source_note_id: str
    beat_onset: float
    beat_offset: float
    instrument: str = "unknown"
    instrument_confidence: float = 0.0
    role: str | None = None
    role_confidence: float = 0.0
    staff_candidate: int | None = None
    voice_candidate: int | None = None
    hand_candidate: str | None = None
    chord_group: str | None = None
    phrase_id: int | None = None
    interpretation_evidence: list[NoteEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["interpretation_evidence"] = [asdict(e) for e in self.interpretation_evidence]
        return data


@dataclass
class InterpretedPerformance:
    notes: list[InterpretedNote] = field(default_factory=list)
    meter: str | None = None
    meter_confidence: float | None = None
    meter_status: str = "ok"  # ok | METER_AMBIGUOUS
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notes": [n.to_dict() for n in self.notes],
            "meter": self.meter,
            "meter_confidence": self.meter_confidence,
            "meter_status": self.meter_status,
            "extra": dict(self.extra),
        }
