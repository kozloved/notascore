"""Transcription provider protocol. Existing adapters wrap into this."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from mir.models import TranscriptionResult


@dataclass(frozen=True)
class TranscriptionCapabilities:
    monophonic: bool = False
    polyphonic: bool = False
    multi_instrument: bool = False
    piano_specialist: bool = False
    supports_velocity: bool = True
    supports_pitch_bend: bool = False
    supports_programs: bool = False


@dataclass
class TranscriptionContext:
    instrument_hint: str | None = None
    stem_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class Transcriber(Protocol):
    name: str
    capabilities: TranscriptionCapabilities

    def transcribe(self, audio_path: str, context: TranscriptionContext | None = None) -> TranscriptionResult:
        ...
