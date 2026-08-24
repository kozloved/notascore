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


ALLOWED_TYPES_ALIASES = {
    "remove_note": "pitch",
    "delete_note": "pitch",
    "drop_note": "pitch",
    "drop": "pitch",
    "update_note": "pitch",
    "change_note": "pitch",
    "change_pitch": "pitch",
    "extend_note": "timing",
    "note_modification": "pitch",
    "modify_note": "pitch",
    "timing": "timing",
}

_CONFIDENCE_WORDS = {
    "very high": 0.95,
    "high": 0.9,
    "medium": 0.65,
    "moderate": 0.65,
    "low": 0.35,
    "very low": 0.2,
}


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text in _CONFIDENCE_WORDS:
        return _CONFIDENCE_WORDS[text]
    try:
        return float(text)
    except ValueError:
        return default


def _first_note_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return dict(value[0])
    return {}


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
        existing = dict(raw.get("existing_value") or {})
        proposed = dict(raw.get("proposed_value") or {})
        original = _first_note_dict(
            raw.get("original_notes") or raw.get("existing_notes")
        )
        corrected_raw = raw.get("corrected_notes")
        if original:
            existing = {**original, **existing}
        if isinstance(corrected_raw, list) and not corrected_raw:
            proposed = {**proposed, "drop": True, "pitch": existing.get("pitch")}
        else:
            corrected = _first_note_dict(corrected_raw or raw.get("proposed_notes"))
            if corrected:
                proposed = {**corrected, **proposed}
                start = _as_float(corrected.get("start"), _as_float(raw.get("time_start")))
                duration = _as_float(corrected.get("duration"))
                if duration and "end_time" not in proposed:
                    proposed["start_time"] = start
                    proposed["end_time"] = start + duration
                    proposed["pitch"] = corrected.get("pitch", existing.get("pitch"))
        ctype = str(raw.get("type") or raw.get("action") or "pitch")
        ctype = ALLOWED_TYPES_ALIASES.get(ctype, ctype)
        if proposed.get("drop") or raw.get("action") in {"delete", "remove"}:
            ctype = "pitch"
            proposed["drop"] = True
            if existing.get("pitch") is not None:
                proposed.setdefault("pitch", existing.get("pitch"))
        elif (
            existing.get("pitch") is not None
            and proposed.get("pitch") is not None
            and int(existing.get("pitch") or 0) != int(proposed.get("pitch") or 0)
        ):
            ctype = "pitch"
        elif proposed.get("end_time") or proposed.get("duration"):
            if ctype not in {"tempo", "meter", "instrument", "hand", "voice"}:
                ctype = "timing"
        return cls(
            type=ctype,
            time_start=_as_float(raw.get("time_start") or existing.get("start")),
            time_end=_as_float(raw.get("time_end")),
            existing_value=existing,
            proposed_value=proposed,
            confidence=_as_float(raw.get("confidence")),
            reason=str(raw.get("reason") or ""),
            requires_deep_analysis=bool(raw.get("requires_deep_analysis")),
            final_confidence=_as_float(raw.get("final_confidence")),
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
            overall_confidence=_as_float(raw.get("overall_confidence")),
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
