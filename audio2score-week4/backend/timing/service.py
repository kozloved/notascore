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
    # Tracker/performance snapshot. Score-time retune must not overwrite these.
    performance_beat_times: tuple[float, ...] = ()
    performance_median_bpm: float | None = None
    tempo_scale: float = 1.0
    retune_reason: str = ""

    @property
    def confidence(self) -> float | None:
        return self.quality.confidence

    @property
    def audio_duration_sec(self) -> float | None:
        return self.quality.audio_duration_sec

    def score_median_bpm(self) -> float | None:
        return self.quality.median_bpm

    def to_dict(self, *, meter_candidates: list | None = None) -> dict[str, Any]:
        score_beats = list(self.time_map.beat_times)
        perf_beats = list(self.performance_beat_times) if self.performance_beat_times else score_beats
        score_bpm = self.quality.median_bpm
        perf_bpm = (
            self.performance_median_bpm
            if self.performance_median_bpm is not None
            else score_bpm
        )
        retuned = abs(float(self.tempo_scale) - 1.0) > 1e-9
        return {
            "backend": self.backend_used,
            "backend_requested": self.backend_requested,
            "backend_used": self.backend_used,
            "fallback_used": self.fallback_used,
            "failure_reason": self.failure_reason,
            "beat_times": score_beats,
            "downbeat_times": list(self.analysis.downbeat_times),
            "source": self.time_map.source,
            "printed_tempo": [
                {"beat": m.beat, "bpm": m.bpm, "mark": m.mark, "reason": m.reason}
                for m in self.printed
            ],
            "meter_candidates": meter_candidates,
            "quality": self.quality.to_dict(),
            "warnings": list(self.analysis.warnings),
            "performance": {
                "median_bpm": perf_bpm,
                "beat_times": perf_beats,
            },
            "score": {
                "tempo_scale": self.tempo_scale,
                "median_bpm": score_bpm,
                "beat_times": score_beats,
            },
            "retuned": retuned,
            "reason": self.retune_reason or None,
            "tempo_scale": self.tempo_scale,
            "score_median_bpm": score_bpm,
            "performance_median_bpm": perf_bpm,
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


def _snapshot_performance(timing: TimingResolution) -> None:
    """Capture tracker tempo once. Later score-time maps must not replace it."""
    if timing.performance_beat_times:
        return
    timing.performance_beat_times = tuple(timing.time_map.beat_times)
    timing.performance_median_bpm = timing.quality.median_bpm


def maps_logically_equal(left: MusicalTimeMap, right: MusicalTimeMap, *, tol: float = 1e-9) -> bool:
    """Same beat instants (seconds), independent of object identity."""
    if len(left.beat_times) != len(right.beat_times):
        return False
    return all(abs(a - b) <= tol for a, b in zip(left.beat_times, right.beat_times))


def score_time_fingerprint(timing: TimingResolution) -> dict[str, Any]:
    """Derived checks that every score-time consumer should agree on."""
    tm = timing.time_map
    first_sec = tm.beat_times[0] if tm.beat_times else None
    first_beat = tm.seconds_to_beats(first_sec) if first_sec is not None else None
    series = tm.interval_bpms()
    opening_map_bpm = series[0][1] if series else None
    opening_printed = next((m.bpm for m in timing.printed if m.bpm is not None), None)
    return {
        "beat_count": len(tm.beat_times),
        "first_beat_sec": first_sec,
        "first_beat_index": first_beat,
        "median_bpm": timing.quality.median_bpm,
        "printed_opening_bpm": opening_printed,
        "map_opening_bpm": opening_map_bpm,
        "analysis_beat_count": len(timing.analysis.beat_times),
        "analysis_beats_match": list(tm.beat_times) == list(timing.analysis.beat_times),
        "analysis_map_beats_match": list(tm.beat_times) == list(timing.analysis.time_map.beat_times),
        "quality_beat_count": timing.quality.beat_count,
        "tempo_scale": timing.tempo_scale,
        "performance_median_bpm": timing.performance_median_bpm,
        "score_median_bpm": timing.quality.median_bpm,
    }


def score_time_consistency_issues(timing: TimingResolution) -> list[str]:
    """Logical agreement between the active map and derived timing state."""
    issues: list[str] = []
    fp = score_time_fingerprint(timing)
    if not fp["analysis_beats_match"]:
        issues.append("analysis.beat_times disagrees with time_map")
    if not fp["analysis_map_beats_match"]:
        issues.append("analysis.time_map disagrees with time_map")
    if fp["quality_beat_count"] != fp["beat_count"]:
        issues.append(
            f"quality.beat_count={fp['quality_beat_count']} != map beat_count={fp['beat_count']}"
        )
    recomputed = quality_from_beat_times(
        list(timing.time_map.beat_times),
        backend=timing.backend_used,
        fallback_used=timing.fallback_used,
        confidence=timing.quality.confidence,
        backend_requested=timing.backend_requested,
        backend_used=timing.backend_used,
        failure_reason=timing.failure_reason,
        duration_ms=timing.duration_ms,
        audio_duration_sec=timing.quality.audio_duration_sec,
    )
    if timing.quality.median_bpm is not None and recomputed.median_bpm is not None:
        if abs(timing.quality.median_bpm - recomputed.median_bpm) > 1e-6:
            issues.append("quality.median_bpm disagrees with active map")
    opening_map = fp["map_opening_bpm"]
    opening_printed = fp["printed_opening_bpm"]
    if opening_map and opening_printed is not None:
        if abs(opening_printed - opening_map) / max(opening_map, 1.0) > 0.08:
            issues.append(
                f"printed opening bpm={opening_printed} disagrees with map bpm={opening_map}"
            )
    if (
        timing.performance_median_bpm
        and timing.quality.median_bpm
        and abs(float(timing.tempo_scale) - 1.0) > 1e-9
    ):
        expected = timing.performance_median_bpm * float(timing.tempo_scale)
        if abs(timing.quality.median_bpm - expected) / max(abs(expected), 1.0) > 0.08:
            issues.append(
                f"score bpm={timing.quality.median_bpm} disagrees with "
                f"performance_bpm={timing.performance_median_bpm} * scale={timing.tempo_scale}"
            )
    return issues


def apply_score_time_map(
    timing: TimingResolution,
    new_map: MusicalTimeMap,
    *,
    reason: str,
    tempo_scale: float | None = None,
) -> TimingResolution:
    """Replace the active score-time map and refresh every derived field.

    Raw performed seconds are not stored here and are never modified.
    Tracker/performance tempo is snapshotted once and preserved.
    """
    _snapshot_performance(timing)
    timing.time_map = new_map
    timing.analysis.time_map = new_map
    timing.analysis.beat_times = list(new_map.beat_times)
    timing.analysis.warnings.append(reason)
    timing.printed = _printed(new_map)
    timing.quality = quality_from_beat_times(
        list(new_map.beat_times),
        backend=timing.backend_used,
        fallback_used=timing.fallback_used,
        confidence=timing.quality.confidence,
        backend_requested=timing.backend_requested,
        backend_used=timing.backend_used,
        failure_reason=timing.failure_reason,
        duration_ms=timing.duration_ms,
        audio_duration_sec=timing.quality.audio_duration_sec,
    )
    if tempo_scale is not None:
        timing.tempo_scale = float(tempo_scale)
        timing.retune_reason = reason
    elif not timing.retune_reason:
        timing.retune_reason = reason
    return timing


def align_score_origin(timing: TimingResolution, first_note_sec: float, *,
                       downbeat_times=(), beats_per_bar=None) -> TimingResolution:
    mapped = timing.time_map.for_score(
        first_note_sec, downbeat_times=downbeat_times, beats_per_bar=beats_per_bar)
    if mapped is timing.time_map:
        return timing
    shift = mapped.seconds_to_beats(timing.time_map.beat_times[0])
    return apply_score_time_map(
        timing,
        mapped,
        reason=(
            f"score origin translated by {shift:g} beats; performance timing preserved"
        ),
    )


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
        performance_beat_times=tuple(time_map.beat_times),
        performance_median_bpm=quality.median_bpm,
        tempo_scale=1.0,
        retune_reason="",
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
