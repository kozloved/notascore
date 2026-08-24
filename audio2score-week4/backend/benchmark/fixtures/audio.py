"""Render deterministic additive-synthesis WAV from reference notes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


def render_notes_wav(
    notes: list[dict[str, Any]],
    path: str | Path,
    *,
    sample_rate: int = 22050,
    tail_sec: float = 0.35,
) -> Path:
    """Write a reproducible WAV. Not piano-like; used only as Fast-mode input."""
    if not notes:
        raise ValueError("Cannot render empty note list")
    end = max(float(n["end_time"]) for n in notes) + tail_sec
    n_samples = max(1, int(round(end * sample_rate)))
    audio = np.zeros(n_samples, dtype=np.float64)
    for note in notes:
        freq = 440.0 * (2.0 ** ((int(note["pitch"]) - 69) / 12.0))
        start = max(0.0, float(note["start_time"]))
        stop = max(start + 0.02, float(note["end_time"]))
        i0 = int(round(start * sample_rate))
        i1 = min(n_samples, int(round(stop * sample_rate)))
        if i1 <= i0:
            continue
        t = np.arange(i1 - i0, dtype=np.float64) / sample_rate
        vel = max(1, min(127, int(note.get("velocity") or 80)))
        amp = 0.08 + 0.12 * (vel / 127.0)
        attack = max(1, int(0.01 * sample_rate))
        release = max(1, int(0.05 * sample_rate))
        env = np.ones(i1 - i0, dtype=np.float64)
        env[: min(attack, len(env))] = np.linspace(0.0, 1.0, min(attack, len(env)))
        if release < len(env):
            env[-release:] = np.linspace(1.0, 0.0, release)
        audio[i0:i1] += amp * env * np.sin(2.0 * np.pi * freq * t)
    peak = np.max(np.abs(audio)) if audio.size else 1.0
    if peak > 0.95:
        audio *= 0.95 / peak
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), audio.astype(np.float32), sample_rate)
    return out
