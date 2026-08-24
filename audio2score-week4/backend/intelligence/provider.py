"""Provider abstraction for musical analysis models."""

from __future__ import annotations

from typing import Protocol

from intelligence.schemas import GeminiAnalysis, MusicalAnalysisPacket


class MusicAnalysisProvider(Protocol):
    name: str

    def analyse(
        self,
        packet: MusicalAnalysisPacket,
        *,
        model: str,
        audio_bytes: bytes | None,
        audio_mime: str,
        task: str,
    ) -> tuple[GeminiAnalysis, dict]:
        """Return analysis plus usage metadata. Must not raise on soft failures."""
        ...
