"""Stem separator protocol. Disabled providers must not invent stems."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


ALLOWED_STEMS = ("vocals", "piano", "guitar", "bass", "drums", "other")


@dataclass
class StemAudio:
    stem_id: str
    instrument: str
    path: str
    confidence: float | None = None
    model: str = ""
    model_version: str = ""
    duration_sec: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class SeparationResult:
    stems: list[StemAudio]
    model: str
    model_version: str = ""
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""


class StemSeparator(Protocol):
    name: str

    def separate(self, audio_path: str) -> SeparationResult:
        ...
