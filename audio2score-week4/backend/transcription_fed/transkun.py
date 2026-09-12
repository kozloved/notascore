"""Disabled Transkun V2 adapter. Not a production dependency until licensed."""

from __future__ import annotations

from engine.flags import transkun_checkpoint, transkun_enabled, transkun_operational
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
            f"operational={transkun_operational()}, "
            f"checkpoint={transkun_checkpoint() or 'unset'})."
        )


def transkun_available() -> bool:
    """Operational readiness for routing. Configured flags never imply this."""
    return transkun_operational()


def transkun_status() -> dict:
    from engine.flags import transkun_configured, transkun_enabled, transkun_operational

    return {
        "configured": transkun_configured(),
        "operational": transkun_operational(),
        "enabled": transkun_enabled(),
    }
