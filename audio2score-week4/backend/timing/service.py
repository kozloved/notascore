"""Resolve one MusicalTimeMap per job. Never a second beat-tracker pass."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from timing.base import BeatAnalysis
from timing.existing_tracker import analysis_from_beat_times, analyze_from_tracker
from timing.metrics import TimingQuality, quality_from_beat_times
from timing.printed_tempo import ScoreTempoAnnotation, printed_tempo_annotations
from timing.tempo_map import MusicalTimeMap, sanitize_beat_times


@dataclass
class TimingResolution:
    time_map: MusicalTimeMap
    analysis: BeatAnalysis
    quality: TimingQuality
    printed: list[ScoreTempoAnnotation] = field(default_factory=list)
    fallback_used: bool = False
    backend_requested: str = "existing_tracker"
    backend_used: str = "existing_tracker"
    failure_reason: str = ""
    duration_ms: float = 0.0

    def to_dict(self, *, meter_candidates: list | None = None) -> dict[str, Any]:
        return {
            "backend": self.backend_used,
            "backend_requested": self.backend_requested,
            "backend_used": self.backend_used,
            "fallback_used": self.fallback_used,
            "failure_reason": self.failure_reason,
            "beat_times": list(self.time_map.beat_times),
            "downbeat_times": list(self.analysis.downbeat_times),
            "source": self.time_map.source,
            "printed_tempo": [
                {"beat": m.beat, "bpm": m.bpm, "mark": m.mark, "reason": m.reason}
                for m in self.printed
            ],
            "meter_candidates": meter_candidates,
            "quality": self.quality.to_dict(),
            "warnings": list(self.analysis.warnings),
        }

    def write_json(self, path: str | Path, *, meter_candidates: list | None = None) -> Path:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(self.to_dict(meter_candidates=meter_candidates), indent=2) + "\n")
        return dest


def _printed(time_map: MusicalTimeMap) -> list[ScoreTempoAnnotation]:
    series = time_map.interval_bpms()
    if not series:
        return []
    return printed_tempo_annotations(series, min_change_ratio=0.15, min_hold_beats=8.0)


def align_score_origin(timing: TimingResolution, first_note_sec: float, *,
                       downbeat_times=(), beats_per_bar=None) -> TimingResolution:
    mapped = timing.time_map.for_score(
        first_note_sec, downbeat_times=downbeat_times, beats_per_bar=beats_per_bar)
    if mapped is timing.time_map:
        return timing
    shift = mapped.seconds_to_beats(timing.time_map.beat_times[0])
    timing.time_map = mapped
    timing.analysis.time_map = mapped
    timing.analysis.beat_times = list(mapped.beat_times)
    timing.analysis.warnings.append(f"score origin translated by {shift:g} beats; performance timing preserved")
    timing.printed = _printed(mapped)
    timing.quality = quality_from_beat_times(
        list(mapped.beat_times), backend=timing.backend_used,
        fallback_used=timing.fallback_used, confidence=timing.quality.confidence,
        backend_requested=timing.backend_requested, backend_used=timing.backend_used,
        failure_reason=timing.failure_reason, duration_ms=timing.duration_ms,
        audio_duration_sec=timing.quality.audio_duration_sec)
    return timing


def _finish(
    time_map: MusicalTimeMap,
    analysis: BeatAnalysis,
    *,
    fallback_used: bool,
    backend_requested: str,
    backend_used: str,
    failure_reason: str,
    duration_ms: float,
    audio_duration_sec: float | None,
    confidence: float | None,
) -> TimingResolution:
    quality = quality_from_beat_times(
        list(time_map.beat_times),
        backend=backend_used,
        fallback_used=fallback_used,
        confidence=confidence,
        backend_requested=backend_requested,
        backend_used=backend_used,
        failure_reason=failure_reason,
        duration_ms=duration_ms,
        audio_duration_sec=audio_duration_sec,
    )
    return TimingResolution(
        time_map=time_map,
        analysis=analysis,
        quality=quality,
        printed=_printed(time_map),
        fallback_used=fallback_used,
        backend_requested=backend_requested,
        backend_used=backend_used,
        failure_reason=failure_reason,
        duration_ms=duration_ms,
    )


def _constant_fallback(
    *,
    bpm: float,
    duration_sec: float,
    backend_requested: str,
    failure_reason: str,
    duration_ms: float,
    audio_duration_sec: float | None,
) -> TimingResolution:
    time_map = MusicalTimeMap.from_bpm(bpm, duration_sec=max(duration_sec, 1.0))
    analysis = analysis_from_beat_times(list(time_map.beat_times), model=time_map.source)
    analysis.fallback_used = True
    analysis.fallback_of = backend_requested
    analysis.warnings.append(failure_reason)
    return _finish(
        time_map,
        analysis,
        fallback_used=True,
        backend_requested=backend_requested,
        backend_used=time_map.source,
        failure_reason=failure_reason,
        duration_ms=duration_ms,
        audio_duration_sec=audio_duration_sec,
        confidence=None,
    )


def resolve_from_beat_times(
    beat_times,
    *,
    downbeat_times=None,
    model: str = "explicit_beats",
    duration_sec: float = 1.0,
    audio_duration_sec: float | None = None,
    backend_requested: str = "existing_tracker",
    duration_ms: float = 0.0,
    confidence: float | None = None,
) -> TimingResolution:
    cleaned = sanitize_beat_times(beat_times)
    try:
        time_map = MusicalTimeMap.from_beat_times(cleaned, source=model)
        analysis = analysis_from_beat_times(
            list(time_map.beat_times),
            downbeat_times=list(downbeat_times or []),
            model=model,
        )
        return _finish(
            time_map,
            analysis,
            fallback_used=False,
            backend_requested=backend_requested,
            backend_used=model,
            failure_reason="",
            duration_ms=duration_ms,
            audio_duration_sec=audio_duration_sec,
            confidence=confidence,
        )
    except ValueError as exc:
        return _constant_fallback(
            bpm=120.0,
            duration_sec=duration_sec,
            backend_requested=backend_requested,
            failure_reason=str(exc),
            duration_ms=duration_ms,
            audio_duration_sec=audio_duration_sec,
        )


def resolve_from_tempo_map(
    tempo_map,
    *,
    duration_sec: float,
    backend_requested: str = "tempo_map",
    backend_used: str = "tempo_map",
    fallback_used: bool = True,
    failure_reason: str = "beat timestamps unavailable; sampled TempoMap",
    audio_duration_sec: float | None = None,
    duration_ms: float = 0.0,
) -> TimingResolution:
    try:
        time_map = MusicalTimeMap.from_tempo_map(tempo_map, duration_sec=duration_sec)
        analysis = analysis_from_beat_times(list(time_map.beat_times), model=time_map.source)
        analysis.fallback_used = fallback_used
        if failure_reason:
            analysis.warnings.append(failure_reason)
        return _finish(
            time_map,
            analysis,
            fallback_used=fallback_used,
            backend_requested=backend_requested,
            backend_used=backend_used,
            failure_reason=failure_reason,
            duration_ms=duration_ms,
            audio_duration_sec=audio_duration_sec,
            confidence=None,
        )
    except ValueError as exc:
        bpm = float(tempo_map.bpm_at(0.0)) if tempo_map is not None else 120.0
        return _constant_fallback(
            bpm=bpm or 120.0,
            duration_sec=duration_sec,
            backend_requested=backend_requested,
            failure_reason=str(exc),
            duration_ms=duration_ms,
            audio_duration_sec=audio_duration_sec,
        )


def resolve_from_existing_tracker(
    tracker,
    tempo_map,
    *,
    duration_sec: float,
    audio_duration_sec: float | None = None,
    tracker_wall_ms: float = 0.0,
) -> TimingResolution:
    """Reuse a tracker that already ran. Does not call track() again."""
    started = time.perf_counter()
    requested = "existing_tracker"
    analysis = analyze_from_tracker(tracker, tempo_map=tempo_map, duration_sec=duration_sec)
    elapsed = tracker_wall_ms + (time.perf_counter() - started) * 1000.0
    cleaned = sanitize_beat_times(analysis.beat_times)
    if len(cleaned) >= 2:
        try:
            time_map = MusicalTimeMap.from_beat_times(cleaned, source=analysis.model)
            downs = [t for t in analysis.downbeat_times if t == t]
            analysis.beat_times = list(time_map.beat_times)
            analysis.time_map = time_map
            if downs:
                analysis.downbeat_times = downs
            return _finish(
                time_map,
                analysis,
                fallback_used=analysis.fallback_used,
                backend_requested=requested,
                backend_used=analysis.model,
                failure_reason="; ".join(analysis.warnings) if analysis.fallback_used else "",
                duration_ms=elapsed,
                audio_duration_sec=audio_duration_sec,
                confidence=analysis.confidence,
            )
        except ValueError as exc:
            return resolve_from_tempo_map(
                tempo_map,
                duration_sec=duration_sec,
                backend_requested=requested,
                backend_used="tempo_map",
                failure_reason=str(exc),
                audio_duration_sec=audio_duration_sec,
                duration_ms=elapsed,
            )
    return resolve_from_tempo_map(
        tempo_map,
        duration_sec=duration_sec,
        backend_requested=requested,
        backend_used="tempo_map",
        failure_reason=analysis.warnings[0] if analysis.warnings else "too few beat times",
        audio_duration_sec=audio_duration_sec,
        duration_ms=elapsed,
    )
