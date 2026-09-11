"""Route audio to the appropriate transcriber without picking a universal winner."""

from __future__ import annotations

from transcription_fed.base import TranscriptionCapabilities, TranscriptionContext, Transcriber


class MidiIngestTranscriber:
    name = "midi_ingest"
    capabilities = TranscriptionCapabilities(
        polyphonic=True, multi_instrument=True, supports_programs=True, supports_pitch_bend=True
    )

    def transcribe(self, audio_path: str, context: TranscriptionContext | None = None):
        from mir.midi_ingest import ingest_midi
        from mir.models import TranscriptionResult

        ingested = ingest_midi(audio_path)
        return TranscriptionResult(
            notes=list(ingested.notes),
            backend=self.name,
            audio_path=str(audio_path),
            extra={"performance": ingested.performance},
        )


class BasicPitchTranscriber:
    name = "basic_pitch"
    capabilities = TranscriptionCapabilities(monophonic=True, polyphonic=True, supports_velocity=True)

    def transcribe(self, audio_path: str, context: TranscriptionContext | None = None):
        from adapters.basic_pitch_backend import BasicPitchBackend
        from mir.models import TranscriptionResult

        notes = BasicPitchBackend().transcribe_notes(audio_path)
        return TranscriptionResult(notes=list(notes), backend=self.name, audio_path=str(audio_path))


class Mt3Transcriber:
    name = "mt3"
    capabilities = TranscriptionCapabilities(
        polyphonic=True, multi_instrument=True, supports_programs=True, supports_velocity=True
    )

    def transcribe(self, audio_path: str, context: TranscriptionContext | None = None):
        from adapters.mt3_backend import MT3Backend
        from mir.models import TranscriptionResult

        notes = MT3Backend().transcribe_notes(audio_path)
        return TranscriptionResult(notes=list(notes), backend=self.name, audio_path=str(audio_path))


def default_router() -> dict[str, Transcriber]:
    return {
        "midi": MidiIngestTranscriber(),
        "solo": BasicPitchTranscriber(),
        "stem": BasicPitchTranscriber(),
        "polyphonic": Mt3Transcriber(),
        "piano": Mt3Transcriber(),  # Transkun replaces this when enabled
    }


def select_transcriber(
    *,
    mode: str,
    instrument_hint: str | None = None,
    providers: dict[str, Transcriber] | None = None,
) -> Transcriber:
    from engine.flags import transkun_enabled
    from transcription_fed.transkun import TranskunTranscriber, transkun_available

    table = providers or default_router()
    if mode == "midi":
        return table["midi"]
    if instrument_hint == "piano" and transkun_enabled() and transkun_available():
        return TranskunTranscriber()
    if mode in ("polyphonic", "quality"):
        return table["polyphonic"]
    if mode == "stem":
        return table["stem"]
    return table.get("solo") or table["midi"]
