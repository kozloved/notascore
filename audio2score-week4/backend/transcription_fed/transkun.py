"""Disabled Transkun V2 adapter. Not a production dependency until licensed."""

from __future__ import annotations

from engine.flags import transkun_checkpoint, transkun_enabled
from transcription_fed.base import TranscriptionCapabilities, TranscriptionContext


class TranskunUnavailable(RuntimeError):
    pass


class TranskunTranscriber:
    name = "transkun"
    capabilities = TranscriptionCapabilities(
        polyphonic=True, piano_specialist=True, supports_velocity=True
    )

    def transcribe(self, audio_path: str, context: TranscriptionContext | None = None):
        raise TranskunUnavailable(
            "Transkun V2 is disabled until code and checkpoint licenses "
            f"are documented (NEXTGEN_TRANSKUN={transkun_enabled()}, "
            f"checkpoint={transkun_checkpoint() or 'unset'})."
        )


def transkun_available() -> bool:
    return transkun_enabled() and bool(transkun_checkpoint())
