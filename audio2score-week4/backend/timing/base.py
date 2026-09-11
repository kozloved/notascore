"""Beat / downbeat analyzer protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from timing.tempo_map import MusicalTimeMap


@dataclass
class BeatAnalysis:
    beat_times: list[float]
    downbeat_times: list[float]
    time_map: MusicalTimeMap
    model: str
    model_version: str = ""
    warnings: list[str] = field(default_factory=list)
    fallback_used: bool = False
    fallback_of: str = ""
    confidence: float | None = None


class BeatAnalyzer(Protocol):
    name: str

    def analyze(self, audio_path: str) -> BeatAnalysis:
        ...
