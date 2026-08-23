"""Classical DSP transcription stack."""

from __future__ import annotations

from pathlib import Path

from audio_engine.normalizer import AudioNormalizer
from audio_engine.onset_detector import OnsetDetector
from audio_engine.pitch_extractor import PitchExtractor
from audio_engine.polyphonic_decoder import PolyphonicDecoder
from mir.types import NoteEvent


class ClassicalDspBackend:
    name = "classical_dsp"

    def __init__(self):
        self.normalizer = AudioNormalizer()
        self.onset_detector = OnsetDetector()
        self.pitch_extractor = PitchExtractor()
        self.decoder = PolyphonicDecoder()

    def transcribe_notes(self, audio_path: str | Path) -> list[NoteEvent]:
        audio = self.normalizer.normalize(audio_path)
        onsets = self.onset_detector.detect(audio)
        matrix = self.pitch_extractor.extract(audio)
        return self.decoder.decode(matrix, onsets)
