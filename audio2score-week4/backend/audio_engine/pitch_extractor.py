"""Pluggable pitch extraction (CQT salience, no FFT-peak→note)."""

from __future__ import annotations

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import PitchMatrix


class PitchExtractor:
    """Extract frame-wise pitch activations via CQT chroma salience."""

    def __init__(
        self,
        fmin: float | None = None,
        n_bins: int = 84,
        hop_length: int = 512,
    ):
        self.fmin = fmin if fmin is not None else librosa_note_to_hz(36)
        self.n_bins = n_bins
        self.hop_length = hop_length

    def extract(self, audio: NormalizedAudio) -> PitchMatrix:
        import librosa

        y = audio.samples
        sr = audio.sample_rate

        cqt = np.abs(
            librosa.cqt(
                y,
                sr=sr,
                hop_length=self.hop_length,
                fmin=self.fmin,
                n_bins=self.n_bins,
                bins_per_octave=12,
            )
        )
        # Normalize per frame
        cqt = cqt / (np.max(cqt, axis=0, keepdims=True) + 1e-8)
        times = librosa.frames_to_time(
            np.arange(cqt.shape[1]), sr=sr, hop_length=self.hop_length
        ).tolist()

        pitch_bins = list(range(36, 36 + self.n_bins))
        probabilities = cqt.T.tolist()

        mean_conf = float(np.mean(cqt[cqt > 0.1])) if np.any(cqt > 0.1) else 0.0

        return PitchMatrix(
            times=times,
            pitch_bins=pitch_bins,
            probabilities=probabilities,
            confidence=min(1.0, mean_conf),
        )


def librosa_note_to_hz(midi: int) -> float:
    import librosa

    return librosa.midi_to_hz(midi)
