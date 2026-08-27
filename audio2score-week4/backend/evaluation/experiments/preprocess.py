"""Experiment-only audio preprocessing (Checkpoint 9A).

Preserves time alignment: silence trim zeros leading/trailing regions in place
instead of deleting samples (so absolute onset times remain valid vs reference MIDI).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from evaluation.experiments.config import PreprocessConfig, PRODUCTION_SAMPLE_RATE


@dataclass
class AudioProbe:
    """Diagnostic metadata for an audio buffer (before or after preprocess)."""

    sample_rate: int
    channels: int
    duration_sec: float
    peak_level: float
    rms_level: float
    leading_silence_sec: float
    trailing_silence_sec: float
    num_samples: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PreprocessResult:
    samples: np.ndarray
    sample_rate: int
    input_probe: AudioProbe
    output_probe: AudioProbe
    config: PreprocessConfig
    path: Path | None = None
    notes: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "input": self.input_probe.to_dict(),
            "output": self.output_probe.to_dict(),
            "path": str(self.path) if self.path else None,
            "notes": list(self.notes or []),
            "duration_delta_sec": (
                self.output_probe.duration_sec - self.input_probe.duration_sec
            ),
            "time_alignment_preserved": abs(
                self.output_probe.duration_sec - self.input_probe.duration_sec
            )
            < 1e-6
            or (
                # Zeroing silence keeps length even if "trim" flag is set.
                self.output_probe.num_samples == self.input_probe.num_samples
                or (
                    self.config.target_sr is not None
                    and abs(
                        self.output_probe.duration_sec - self.input_probe.duration_sec
                    )
                    < 0.02
                )
            ),
        }


def _silence_edges(
    y: np.ndarray, sr: int, *, top_db: float = 40.0
) -> tuple[float, float]:
    if y.size == 0 or sr <= 0:
        return 0.0, 0.0
    import librosa

    intervals = librosa.effects.split(y, top_db=top_db)
    if len(intervals) == 0:
        return float(len(y) / sr), float(len(y) / sr)
    lead = float(intervals[0][0] / sr)
    trail = float((len(y) - intervals[-1][1]) / sr)
    return lead, trail


def probe_audio(y: np.ndarray, sr: int, *, channels: int = 1) -> AudioProbe:
    y = np.asarray(y, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(y)))) if y.size else 0.0
    lead, trail = _silence_edges(y, sr)
    return AudioProbe(
        sample_rate=int(sr),
        channels=int(channels),
        duration_sec=float(len(y) / sr) if sr else 0.0,
        peak_level=peak,
        rms_level=rms,
        leading_silence_sec=lead,
        trailing_silence_sec=trail,
        num_samples=int(y.size),
    )


def load_raw_audio(path: str | Path) -> tuple[np.ndarray, int, int]:
    """Load audio preserving channels for probing; returns (mono_or_multi, sr, n_ch)."""
    import librosa
    import soundfile as sf

    path = Path(path)
    info = sf.info(str(path))
    n_ch = int(info.channels)
    # Load without resample; keep multi-channel for channel count probe then mix.
    y_multi, sr = librosa.load(str(path), mono=False, sr=None)
    if y_multi.ndim == 1:
        return y_multi.astype(np.float32), int(sr), 1
    return y_multi.astype(np.float32), int(sr), int(y_multi.shape[0])


def _to_mono(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=np.float32)
    if y.ndim == 1:
        return y
    # librosa multi-channel: (channels, samples)
    return np.mean(y, axis=0).astype(np.float32)


def _zero_edge_silence(y: np.ndarray, sr: int, *, top_db: float) -> np.ndarray:
    """Zero leading/trailing silence in place (keeps duration / time alignment)."""
    import librosa

    if y.size == 0:
        return y
    intervals = librosa.effects.split(y, top_db=top_db)
    out = np.zeros_like(y)
    if len(intervals) == 0:
        return out
    for start, end in intervals:
        out[start:end] = y[start:end]
    return out


def apply_preprocess(
    audio_path: str | Path,
    config: PreprocessConfig,
    *,
    out_path: str | Path | None = None,
) -> PreprocessResult:
    """Apply experiment preprocessing and optionally write a WAV."""
    import librosa
    import soundfile as sf

    notes: list[str] = []
    y_raw, sr_in, n_ch = load_raw_audio(audio_path)
    y_mono_for_probe = _to_mono(y_raw)
    input_probe = probe_audio(y_mono_for_probe, sr_in, channels=n_ch)

    if config.use_production_normalizer:
        from audio_engine.normalizer import AudioNormalizer

        normalizer = AudioNormalizer(
            target_sr=PRODUCTION_SAMPLE_RATE,
            peak_target=config.peak_target,
            trim_silence=False,
        )
        normalized = normalizer.normalize(audio_path)
        y = normalized.samples
        sr = int(normalized.sample_rate)
        notes.append("used production AudioNormalizer (mono, DC, 22050, peak)")
    else:
        y = _to_mono(y_raw) if config.mono else y_mono_for_probe
        if not config.mono and y_raw.ndim > 1:
            notes.append("non-mono requested but experiment path still mixes for BP")
            y = _to_mono(y_raw)
        sr = int(sr_in)

        if config.trim_silence:
            # Alignment-preserving: zero edges rather than delete samples.
            y = _zero_edge_silence(y, sr, top_db=config.trim_top_db)
            notes.append(
                "trim_silence=True applied as in-place zeroing of edge silence "
                "(duration preserved for absolute-time matching)"
            )

        if config.remove_dc and y.size:
            y = y - np.mean(y)

        if config.target_sr is not None and sr != config.target_sr:
            y = librosa.resample(y, orig_sr=sr, target_sr=config.target_sr)
            sr = int(config.target_sr)
            notes.append(f"resampled to {sr} Hz")

        if config.peak_normalize and y.size:
            peak = float(np.max(np.abs(y)))
            if peak > 1e-8:
                y = y * (config.peak_target / peak)
            notes.append(f"peak normalized to {config.peak_target}")

        y = y.astype(np.float32)

    output_probe = probe_audio(y, sr, channels=1)

    written = None
    if out_path is not None:
        written = Path(out_path)
        written.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(written), y, sr)

    return PreprocessResult(
        samples=y,
        sample_rate=sr,
        input_probe=input_probe,
        output_probe=output_probe,
        config=config,
        path=written,
        notes=notes,
    )


def detect_redundant_preprocess(
    config: PreprocessConfig, reference: PreprocessConfig
) -> str | None:
    """Return explanation if config is redundant with reference fingerprint."""
    if config.fingerprint() == reference.fingerprint():
        return (
            f"Preprocess {config.name!r} duplicates {reference.name!r} "
            f"(fingerprint={config.fingerprint()})"
        )
    return None
