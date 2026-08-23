"""MT3 backend stub — implement after CMR + cleaner + tempo are stable."""

from __future__ import annotations

from pathlib import Path

from mir.types import NoteEvent


class MT3Backend:
    name = "mt3"

    def transcribe_notes(self, audio_path: str | Path) -> list[NoteEvent]:
        raise NotImplementedError(
            "MT3 backend is not yet available. "
            "Use TRANSCRIPTION_BACKEND=basic_pitch or classical_dsp."
        )
