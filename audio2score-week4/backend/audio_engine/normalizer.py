"""Normalize audio for deterministic downstream processing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Union

import numpy as np

DEFAULT_SAMPLE_RATE = 22050
PEAK_TARGET = 0.95


@dataclass
class NormalizedAudio:
    samples: np.ndarray
    sample_rate: int
    source_path: str | None = None
    peak_before: float = 0.0
    peak_after: float = 0.0

    @property
    def duration_sec(self) -> float:
        return len(self.samples) / self.sample_rate if self.sample_rate else 0.0


class AudioNormalizer:
    """Decode, mono-mix, resample, DC-remove, peak-normalize."""

    def __init__(
        self,
        target_sr: int = DEFAULT_SAMPLE_RATE,
        peak_target: float = PEAK_TARGET,
        trim_silence: bool = False,
    ):
        self.target_sr = target_sr
        self.peak_target = peak_target
        self.trim_silence = trim_silence

    def normalize(self, source: Union[str, Path, np.ndarray], sr: int | None = None) -> NormalizedAudio:
        import librosa

        source_path = None
        if isinstance(source, (str, Path)):
            source_path = str(source)
            y, sr_in = librosa.load(source_path, mono=True, sr=None)
        else:
            y = np.asarray(source, dtype=np.float32)
            if y.ndim > 1:
                y = np.mean(y, axis=0)
            sr_in = sr or self.target_sr

        peak_before = float(np.max(np.abs(y))) if y.size else 0.0

        if self.trim_silence and y.size:
            intervals = librosa.effects.split(y, top_db=40)
            if len(intervals):
                chunks = [y[s:e] for s, e in intervals]
                y = np.concatenate(chunks)

        y = y - np.mean(y) if y.size else y

        if sr_in != self.target_sr:
            y = librosa.resample(y, orig_sr=sr_in, target_sr=self.target_sr)
            sr_in = self.target_sr

        peak = float(np.max(np.abs(y))) if y.size else 0.0
        if peak > 1e-8:
            y = y * (self.peak_target / peak)
        peak_after = float(np.max(np.abs(y))) if y.size else 0.0

        return NormalizedAudio(
            samples=y.astype(np.float32),
            sample_rate=sr_in,
            source_path=source_path,
            peak_before=peak_before,
            peak_after=peak_after,
        )

    def write_wav(self, audio: NormalizedAudio, path: Union[str, Path]) -> Path:
        """Persist normalized samples for backends that require a file path."""
        import soundfile as sf

        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out), audio.samples, audio.sample_rate)
        return out
