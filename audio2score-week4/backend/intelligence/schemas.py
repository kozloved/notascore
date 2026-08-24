"""Typed schemas for the analysis packet and Gemini JSON output."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def _as_dict(obj: Any) -> Any:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, list):
        return [_as_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _as_dict(v) for k, v in obj.items()}
    return obj


@dataclass
class AudioMetadata:
    duration_seconds: float = 0.0
    sample_rate: int = 0
    channels: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MidiNoteSummary:
    pitch: int
    start: float
    duration: float
    velocity: int
    confidence: float
    hand: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MusicalAnalysisPacket:
    job_id: str
    audio_metadata: AudioMetadata
    transcription: dict[str, Any]
    tempo: dict[str, Any]
    meter: dict[str, Any]
    beats: dict[str, Any]
    musical_features: dict[str, Any]
    uncertainties: dict[str, Any]
    piano: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "audio_metadata": self.audio_metadata.to_dict(),
            "transcription": self.transcription,
            "tempo": self.tempo,
            "meter": self.meter,
            "beats": self.beats,
            "musical_features": self.musical_features,
            "uncertainties": self.uncertainties,
            "piano": self.piano,
        }


@dataclass
class Correction:
    type: str
    time_start: float
    time_end: float
    existing_value: dict[str, Any]
    proposed_value: dict[str, Any]
    confidence: float
    reason: str
    requires_deep_analysis: bool = False
    final_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Correction:
        return cls(
            type=str(raw.get("type") or "pitch"),
            time_start=float(raw.get("time_start") or 0.0),
            time_end=float(raw.get("time_end") or 0.0),
            existing_value=dict(raw.get("existing_value") or {}),
            proposed_value=dict(raw.get("proposed_value") or {}),
            confidence=float(raw.get("confidence") or 0.0),
            reason=str(raw.get("reason") or ""),
            requires_deep_analysis=bool(raw.get("requires_deep_analysis")),
            final_confidence=float(raw.get("final_confidence") or 0.0),
        )


@dataclass
class GeminiAnalysis:
    overall_confidence: float = 0.0
    instrument_analysis: dict[str, Any] = field(default_factory=dict)
    musical_structure: dict[str, Any] = field(default_factory=dict)
    tempo_analysis: dict[str, Any] = field(default_factory=dict)
    meter_analysis: dict[str, Any] = field(default_factory=dict)
    transcription_validation: dict[str, Any] = field(default_factory=dict)
    corrections: list[Correction] = field(default_factory=list)
    model: str = ""
    cache_hit: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["corrections"] = [c.to_dict() for c in self.corrections]
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any], model: str = "") -> GeminiAnalysis:
        corrections = [
            Correction.from_dict(item)
            for item in (raw.get("corrections") or [])
            if isinstance(item, dict)
        ]
        return cls(
            overall_confidence=float(raw.get("overall_confidence") or 0.0),
            instrument_analysis=dict(raw.get("instrument_analysis") or {}),
            musical_structure=dict(raw.get("musical_structure") or {}),
            tempo_analysis=dict(raw.get("tempo_analysis") or {}),
            meter_analysis=dict(raw.get("meter_analysis") or {}),
            transcription_validation=dict(
                raw.get("transcription_validation") or {}
            ),
            corrections=corrections,
            model=model or str(raw.get("model") or ""),
            cache_hit=bool(raw.get("cache_hit")),
            raw=raw,
        )


EMPTY_ANALYSIS = GeminiAnalysis()
