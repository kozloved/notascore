"""Classical DSP transcription stack.

This adapter is not operational. Production transcription uses Basic Pitch
(solo) or remote YourMT3 (polyphonic). The DSP objects remain for inspection
only and must not be selected as a live backend.
"""

from __future__ import annotations

from pathlib import Path

from mir.types import NoteEvent


class ClassicalDspUnavailable(RuntimeError):
    pass


class ClassicalDspBackend:
    name = "classical_dsp"
    operational = False

    def __init__(self):
        self.normalizer = None
        self.onset_detector = None
        self.pitch_extractor = None
        self.decoder = None

    def transcribe_notes(self, audio_path: str | Path) -> list[NoteEvent]:
        raise ClassicalDspUnavailable(
            "Classical DSP adapter is not operational and is not a production "
            f"transcription backend (path={audio_path})."
        )
