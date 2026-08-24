"""Optional AudioSet taggers (YAMNet / PANNs) for instrument family hints.

These models label sound events (piano, guitar, speech). They do not track
beats or meter — madmom owns that. Disabled unless ENABLE_AUDIOSET_TAGGER=1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import InstrumentKind

_YAMNET = None
_YAMNET_NAMES: list[str] | None = None
_PANNS = None


def _env_on(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def audioset_enabled() -> bool:
    return _env_on("ENABLE_AUDIOSET_TAGGER", default=False)


def yamnet_available() -> bool:
    try:
        import tensorflow_hub  # noqa: F401

        return True
    except Exception:
        return False


def panns_available() -> bool:
    try:
        import panns_inference  # noqa: F401

        return True
    except Exception:
        return False


def audioset_status() -> dict:
    return {
        "enabled": audioset_enabled(),
        "yamnet_available": yamnet_available(),
        "panns_available": panns_available(),
        "backend": _preferred_backend(),
    }


def _preferred_backend() -> str | None:
    preferred = os.getenv("AUDIOSET_TAGGER", "auto").strip().lower()
    if preferred == "yamnet" and yamnet_available():
        return "yamnet"
    if preferred == "panns" and panns_available():
        return "panns"
    if preferred == "off":
        return None
    if panns_available():
        return "panns"
    if yamnet_available():
        return "yamnet"
    return None


@dataclass
class AudioSetTags:
    backend: str
    scores: dict[InstrumentKind, float]
    top_labels: list[tuple[str, float]]


_PIANO = ("piano", "organ", "harpsichord", "keyboard (musical)", "electric piano")
_GUITAR = ("acoustic guitar", "electric guitar", "bass guitar", "guitar")
_VOICE = ("speech", "singing", "choir", "narration, monologue", "male speech", "female speech")
_DRUMS = ("drum", "drum kit", "snare drum", "bass drum", "hi-hat", "cymbal", "percussion")


def _family_scores(label_scores: dict[str, float]) -> dict[InstrumentKind, float]:
    def _sum(names: tuple[str, ...]) -> float:
        total = 0.0
        for name, score in label_scores.items():
            low = name.lower()
            if any(key in low for key in names):
                total = max(total, float(score))
        return min(1.0, total)

    return {
        InstrumentKind.PIANO: _sum(_PIANO),
        InstrumentKind.GUITAR: _sum(_GUITAR),
        InstrumentKind.VOICE: _sum(_VOICE),
        InstrumentKind.DRUMS: _sum(_DRUMS),
        InstrumentKind.UNKNOWN: 0.0,
    }


def tag_audio(audio: NormalizedAudio) -> AudioSetTags | None:
    if not audioset_enabled():
        return None
    backend = _preferred_backend()
    if backend == "panns":
        return _tag_panns(audio)
    if backend == "yamnet":
        return _tag_yamnet(audio)
    return None


def _resample_mono(audio: NormalizedAudio, target_sr: int) -> np.ndarray:
    y = np.asarray(audio.samples, dtype=np.float32)
    if y.ndim > 1:
        y = y.mean(axis=0)
    sr = int(audio.sample_rate)
    if sr == target_sr:
        return y
    import librosa

    return librosa.resample(y, orig_sr=sr, target_sr=target_sr).astype(np.float32)


def _tag_yamnet(audio: NormalizedAudio) -> AudioSetTags | None:
    global _YAMNET, _YAMNET_NAMES
    try:
        import tensorflow as tf
        import tensorflow_hub as hub
    except Exception:
        return None
    try:
        if _YAMNET is None:
            _YAMNET = hub.load("https://tfhub.dev/google/yamnet/1")
            class_map = _YAMNET.class_map_path().numpy()
            _YAMNET_NAMES = [
                line.decode("utf-8").strip().split(",")[-1]
                if isinstance(line, bytes)
                else str(line).strip().split(",")[-1]
                for line in tf.io.gfile.GFile(class_map).readlines()[1:]
            ]
        waveform = _resample_mono(audio, 16000)
        scores, _, _ = _YAMNET(waveform)
        mean = np.mean(scores.numpy(), axis=0)
        names = _YAMNET_NAMES or []
        label_scores = {
            names[i]: float(mean[i]) for i in range(min(len(names), mean.size))
        }
        ranked = sorted(label_scores.items(), key=lambda kv: -kv[1])[:8]
        return AudioSetTags(
            backend="yamnet",
            scores=_family_scores(label_scores),
            top_labels=ranked,
        )
    except Exception as exc:
        print(f"[AudioSet] YAMNet failed ({exc})")
        return None


def _tag_panns(audio: NormalizedAudio) -> AudioSetTags | None:
    global _PANNS
    try:
        from panns_inference import AudioTagging, labels as panns_labels
    except Exception:
        return None
    try:
        if _PANNS is None:
            _PANNS = AudioTagging(checkpoint_path=None, device="cpu")
        waveform = _resample_mono(audio, 32000)
        clipwise, _ = _PANNS.inference(waveform[None, :])
        mean = np.asarray(clipwise[0], dtype=float)
        names = list(panns_labels)
        label_scores = {
            names[i]: float(mean[i]) for i in range(min(len(names), mean.size))
        }
        ranked = sorted(label_scores.items(), key=lambda kv: -kv[1])[:8]
        return AudioSetTags(
            backend="panns",
            scores=_family_scores(label_scores),
            top_labels=ranked,
        )
    except Exception as exc:
        print(f"[AudioSet] PANNs failed ({exc})")
        return None
