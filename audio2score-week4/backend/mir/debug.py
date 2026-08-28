"""Structured per-job debug output for the canonical pipeline."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PipelineDebug:
    job_id: str = ""
    pipeline: str = "understanding"
    transcription_mode: str = "solo"
    source_backend: str = "unknown"
    raw_note_count: int = 0
    cleaned_note_count: int = 0
    removed_notes: list[dict[str, Any]] = field(default_factory=list)
    uncertain_notes: list[dict[str, Any]] = field(default_factory=list)
    detected_instrument: str = "unknown"
    instrument_confidence: float = 0.0
    tempo_hypotheses: list[dict[str, Any]] = field(default_factory=list)
    selected_tempo_bpm: float = 120.0
    selected_meter: str = "4/4"
    meter_confidence: float = 0.0
    selected_key: str = "C"
    key_confidence: float = 0.0
    hand_assignments: dict[str, int] = field(default_factory=dict)
    voice_assignments: dict[str, int] = field(default_factory=dict)
    quantization_decisions: list[dict[str, Any]] = field(default_factory=list)
    fallback_used: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def write_json(self, path: str | Path) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.to_dict(), indent=2, default=str), encoding="utf-8")
        return out
