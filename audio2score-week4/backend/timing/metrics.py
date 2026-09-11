"""Timing quality summary. Confidence is null unless the backend supplies it."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median, pstdev


@dataclass
class TimingQuality:
    backend: str
    beat_count: int
    median_bpm: float | None
    bpm_min: float | None
    bpm_max: float | None
    tempo_variability: float | None
    confidence: float | None
    fallback_used: bool
    backend_requested: str = ""
    backend_used: str = ""
    failure_reason: str = ""
    duration_ms: float | None = None
    audio_duration_sec: float | None = None
    realtime_factor: float | None = None

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "beat_count": self.beat_count,
            "median_bpm": self.median_bpm,
            "bpm_min": self.bpm_min,
            "bpm_max": self.bpm_max,
            "tempo_variability": self.tempo_variability,
            "confidence": self.confidence,
            "fallback_used": self.fallback_used,
            "backend_requested": self.backend_requested,
            "backend_used": self.backend_used,
            "failure_reason": self.failure_reason,
            "duration_ms": self.duration_ms,
            "audio_duration_sec": self.audio_duration_sec,
            "realtime_factor": self.realtime_factor,
        }


def quality_from_beat_times(
    beat_times: list[float],
    *,
    backend: str,
    fallback_used: bool,
    confidence: float | None = None,
    backend_requested: str = "",
    backend_used: str = "",
    failure_reason: str = "",
    duration_ms: float | None = None,
    audio_duration_sec: float | None = None,
) -> TimingQuality:
    bpms: list[float] = []
    for a, b in zip(beat_times, beat_times[1:]):
        dt = b - a
        if dt > 1e-9:
            bpms.append(60.0 / dt)
    med = float(median(bpms)) if bpms else None
    variability = None
    if med and len(bpms) >= 2:
        variability = float(pstdev(bpms) / med)
    rtf = None
    if duration_ms and audio_duration_sec and audio_duration_sec > 0:
        rtf = (duration_ms / 1000.0) / audio_duration_sec
    return TimingQuality(
        backend=backend,
        beat_count=len(beat_times),
        median_bpm=med,
        bpm_min=min(bpms) if bpms else None,
        bpm_max=max(bpms) if bpms else None,
        tempo_variability=variability,
        confidence=confidence,
        fallback_used=fallback_used,
        backend_requested=backend_requested or backend,
        backend_used=backend_used or backend,
        failure_reason=failure_reason,
        duration_ms=duration_ms,
        audio_duration_sec=audio_duration_sec,
        realtime_factor=rtf,
    )
