"""Beat tracking and tempo map construction."""

from __future__ import annotations

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import TempoMap, TempoPoint

MIN_BPM = 50.0
MAX_BPM = 200.0


def _recompute_beats(points: list[TempoPoint]) -> list[TempoPoint]:
    if not points:
        return []
    ordered = sorted(points, key=lambda p: p.time_sec)
    out: list[TempoPoint] = []
    beat = 0.0
    prev_t = 0.0
    prev_bpm = ordered[0].bpm
    for pt in ordered:
        if pt.time_sec > prev_t:
            beat += (pt.time_sec - prev_t) * (prev_bpm / 60.0)
        out.append(
            TempoPoint(
                time_sec=pt.time_sec,
                beat=beat,
                bpm=pt.bpm,
                confidence=pt.confidence,
            )
        )
        prev_t = pt.time_sec
        prev_bpm = pt.bpm
    return out


def stabilize_tempo_map(
    tempo_map: TempoMap,
    *,
    min_change_ratio: float = 0.08,
    min_hold_sec: float = 2.0,
    median_window: int = 8,
) -> TempoMap:
    """Merge per-beat jitter into real tempo regions."""
    points = tempo_map.sorted_points()
    if not points:
        return TempoMap(
            points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0, confidence=0.5)]
        )
    if len(points) == 1:
        pt = points[0]
        if pt.time_sec <= 1e-6:
            return TempoMap(points=list(points))
        return TempoMap(
            points=_recompute_beats(
                [TempoPoint(0.0, 0.0, pt.bpm, pt.confidence), pt]
            )
        )

    bpms = np.array([p.bpm for p in points], dtype=float)
    half = max(1, median_window // 2)
    smoothed = np.empty_like(bpms)
    for i in range(len(bpms)):
        lo = max(0, i - half)
        hi = min(len(bpms), i + half + 1)
        smoothed[i] = float(np.median(bpms[lo:hi]))

    regions: list[TempoPoint] = []
    start_idx = 0
    region_bpm = float(smoothed[0])
    for i in range(1, len(points)):
        held = points[i].time_sec - points[start_idx].time_sec >= min_hold_sec
        changed = abs(float(smoothed[i]) - region_bpm) / max(region_bpm, 1e-6) >= min_change_ratio
        if changed and held:
            regions.append(
                TempoPoint(
                    time_sec=points[start_idx].time_sec,
                    beat=0.0,
                    bpm=region_bpm,
                    confidence=float(
                        np.mean([p.confidence for p in points[start_idx:i]])
                    ),
                )
            )
            start_idx = i
            region_bpm = float(smoothed[i])
        else:
            region_bpm = float(np.median(smoothed[start_idx : i + 1]))
    regions.append(
        TempoPoint(
            time_sec=points[start_idx].time_sec,
            beat=0.0,
            bpm=region_bpm,
            confidence=float(np.mean([p.confidence for p in points[start_idx:]])),
        )
    )

    if regions[0].time_sec > 1e-6:
        regions.insert(
            0,
            TempoPoint(
                time_sec=0.0,
                beat=0.0,
                bpm=regions[0].bpm,
                confidence=regions[0].confidence,
            ),
        )
    else:
        regions[0] = TempoPoint(
            time_sec=0.0,
            beat=0.0,
            bpm=regions[0].bpm,
            confidence=regions[0].confidence,
        )

    return TempoMap(points=_recompute_beats(regions))


def scale_tempo_map(tempo_map: TempoMap, factor: float) -> TempoMap:
    """Scale every region BPM (keeps relative ritardandi/accelerandi)."""
    if factor <= 0 or abs(factor - 1.0) < 1e-9:
        return TempoMap(points=_recompute_beats(tempo_map.sorted_points()))
    scaled: list[TempoPoint] = []
    for pt in tempo_map.sorted_points():
        bpm = float(pt.bpm) * factor
        bpm = min(MAX_BPM, max(MIN_BPM, bpm))
        scaled.append(
            TempoPoint(
                time_sec=pt.time_sec,
                beat=0.0,
                bpm=bpm,
                confidence=pt.confidence,
            )
        )
    return TempoMap(points=_recompute_beats(scaled))


class BeatTracker:
    """Build TempoMap from audio (supports local tempo via beat intervals)."""

    def __init__(self, default_bpm: float = 120.0):
        self.default_bpm = default_bpm

    def track(self, audio: NormalizedAudio) -> TempoMap:
        import librosa

        y = audio.samples
        sr = audio.sample_rate
        if y.size < sr // 4:
            return TempoMap(
                points=[
                    TempoPoint(time_sec=0.0, beat=0.0, bpm=self.default_bpm, confidence=0.5)
                ]
            )

        tempo_global = self.default_bpm
        try:
            estimate = librosa.feature.rhythm.tempo(y=y, sr=sr)
            if len(estimate):
                tempo_global = float(estimate[0])
        except Exception:
            try:
                estimate = librosa.beat.tempo(y=y, sr=sr)
                if len(estimate):
                    tempo_global = float(estimate[0])
            except Exception:
                pass

        while tempo_global < 50:
            tempo_global *= 2
        while tempo_global > 200:
            tempo_global /= 2

        try:
            tempo_dynamic, beats = librosa.beat.beat_track(
                y=y, sr=sr, units="time", bpm=tempo_global
            )
            beat_times = np.atleast_1d(beats)
        except Exception:
            beat_times = np.array([])

        points: list[TempoPoint] = [
            TempoPoint(
                time_sec=0.0,
                beat=0.0,
                bpm=tempo_global,
                confidence=0.7,
            )
        ]

        if beat_times.size >= 2:
            for i in range(len(beat_times) - 1):
                dt = float(beat_times[i + 1] - beat_times[i])
                if dt <= 0:
                    continue
                local_bpm = 60.0 / dt
                if 40 <= local_bpm <= 220:
                    points.append(
                        TempoPoint(
                            time_sec=float(beat_times[i]),
                            beat=float(i),
                            bpm=local_bpm,
                            confidence=0.8,
                        )
                    )

        return TempoMap(points=points)

    def track_stable(self, audio: NormalizedAudio) -> TempoMap:
        return stabilize_tempo_map(self.track(audio))


def constant_tempo_map(bpm: float, confidence: float = 0.9) -> TempoMap:
    return TempoMap(
        points=[
            TempoPoint(
                time_sec=0.0,
                beat=0.0,
                bpm=float(bpm) if bpm else 120.0,
                confidence=confidence,
            )
        ]
    )


def align_tempo_map(tempo_map: TempoMap, target_bpm: float) -> TempoMap:
    """Scale a map so time 0 matches an onset-refined global BPM."""
    seed = tempo_map.bpm_at(0.0)
    if seed <= 1e-6 or target_bpm <= 0:
        return tempo_map
    return scale_tempo_map(tempo_map, float(target_bpm) / seed)
