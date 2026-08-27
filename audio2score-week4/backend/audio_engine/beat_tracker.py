"""Beat tracking and tempo map construction."""

from __future__ import annotations

import os

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import TempoMap, TempoPoint

MIN_BPM = 50.0
MAX_BPM = 200.0
# Onset-grid tempo may be slower than madmom's floor so a largo quarter-note
# melody (IOI ≈ 1.5s) prints as quarters instead of being doubled into halves.
GRID_MIN_BPM = 32.0
ONSET_CLUSTER_SEC = 0.06


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
    """Build TempoMap from audio (madmom downbeats when available, else librosa)."""

    def __init__(self, default_bpm: float = 120.0):
        self.default_bpm = default_bpm
        self.last_source = "librosa"
        self.last_time_signature: str | None = None
        self.last_beat_result = None

    def track(self, audio: NormalizedAudio) -> TempoMap:
        result_map, meter, source = self._track_with_meter(audio)
        self.last_source = source
        self.last_time_signature = meter
        return result_map

    def track_stable(self, audio: NormalizedAudio) -> TempoMap:
        tracked = stabilize_tempo_map(self.track(audio))
        return tracked

    def _track_with_meter(
        self, audio: NormalizedAudio
    ) -> tuple[TempoMap, str | None, str]:
        backend = os.getenv("BEAT_TRACKER_BACKEND", "madmom").strip().lower()
        if backend != "librosa":
            from audio_engine.madmom_beats import track_downbeats

            madmom_result = track_downbeats(audio)
            if madmom_result is not None:
                self.last_beat_result = madmom_result
                print(
                    f"[BeatTracker] madmom bpm={madmom_result.bpm:.1f} "
                    f"grouping={madmom_result.grouping_beats_per_bar or madmom_result.beats_per_bar} "
                    f"label={madmom_result.grouping_meter or madmom_result.time_signature} "
                    f"beats={len(madmom_result.beat_times)} "
                    f"search={madmom_result.grouping_search}"
                )
                return (
                    madmom_result.tempo_map,
                    madmom_result.time_signature,
                    "madmom",
                )
        self.last_beat_result = None
        return self._track_librosa(audio), None, "librosa"

    def _track_librosa(self, audio: NormalizedAudio) -> TempoMap:
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
            _tempo_dynamic, beats = librosa.beat.beat_track(
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


def cluster_onsets(
    onsets: list[float],
    window_sec: float = ONSET_CLUSTER_SEC,
) -> np.ndarray:
    """Collapse simultaneous chord attacks into one grid time."""
    times = np.array(
        sorted(float(t) for t in onsets if t == t),
        dtype=float,
    )
    if times.size == 0:
        return times
    clusters: list[float] = []
    bucket = [float(times[0])]
    for t in times[1:]:
        if float(t) - bucket[0] <= window_sec:
            bucket.append(float(t))
        else:
            clusters.append(float(np.median(bucket)))
            bucket = [float(t)]
    clusters.append(float(np.median(bucket)))
    return np.array(clusters, dtype=float)


def fit_constant_beat_grid(
    onsets: list[float],
    *,
    seed_bpm: float | None = None,
    beat_times: list[float] | None = None,
) -> TempoMap:
    """Build a constant-tempo grid anchored on the first beat note.

    MIDI / audio onsets are snapped later in beat space. Using a constant pulse
    from the first attack prevents an accelerating beat tracker from packing
    later notes closer together.
    """
    clusters = cluster_onsets(onsets)
    if clusters.size == 0:
        return constant_tempo_map(seed_bpm or 120.0)

    t0 = float(clusters[0])
    candidates: list[float] = []
    if seed_bpm and seed_bpm > 0:
        candidates.append(float(seed_bpm))
    if beat_times is not None and len(beat_times) >= 2:
        dts = np.diff(np.asarray(beat_times, dtype=float))
        dts = dts[dts > 1e-3]
        if dts.size:
            candidates.append(60.0 / float(np.median(dts)))

    if clusters.size >= 2:
        iois = np.diff(clusters)
        iois = iois[iois > 1e-3]
        if iois.size:
            med = float(np.median(iois))
            near = iois[(iois > 0.55 * med) & (iois < 1.45 * med)]
            period = float(np.median(near)) if near.size else med
            for factor in (0.25, 1.0 / 3.0, 0.5, 1.0, 2.0, 3.0, 4.0):
                bpm = 60.0 / max(period * factor, 1e-6)
                while bpm < GRID_MIN_BPM:
                    bpm *= 2.0
                while bpm > MAX_BPM:
                    bpm /= 2.0
                candidates.append(float(bpm))

    if not candidates:
        candidates.append(120.0)

    uniq: list[float] = []
    for bpm in candidates:
        if not any(abs(bpm - seen) < 0.25 for seen in uniq):
            uniq.append(float(bpm))

    def _score(bpm: float) -> float:
        quarter = 60.0 / max(bpm, 1e-6)
        rel = (clusters - t0) / quarter
        err = float(np.mean(np.abs(rel - np.round(rel))))
        tactus_pen = 0.0
        if clusters.size >= 2:
            ioi_beats = float(np.median(np.diff(clusters))) / quarter
            # 1, 2, or 4 beats between notes are all legitimate (quarters,
            # halves, wholes). Do not force the slow 40 BPM reading.
            nearest = min((1.0, 2.0, 4.0), key=lambda x: abs(ioi_beats - x))
            tactus_pen = abs(ioi_beats - nearest)
        seed_pen = 0.0
        if seed_bpm:
            octaves = [float(seed_bpm)]
            if 2.0 * seed_bpm <= MAX_BPM + 1e-6:
                octaves.append(2.0 * seed_bpm)
            seed_pen = 0.22 * min(
                abs(bpm - o) / max(o, 1.0) for o in octaves
            )
            # Reject folding a ~80/160 melody down to 40.
            if bpm < 0.75 * seed_bpm:
                seed_pen += 0.55
        return err + 0.10 * tactus_pen + seed_pen

    best = min(uniq, key=_score)
    while best < GRID_MIN_BPM:
        best *= 2.0
    while best > MAX_BPM:
        best /= 2.0

    tm = constant_tempo_map(best, confidence=0.92)
    tm.origin_sec = t0
    return tm


def align_tempo_map(tempo_map: TempoMap, target_bpm: float) -> TempoMap:
    """Scale a map so time 0 matches an onset-refined global BPM."""
    seed = tempo_map.bpm_at(0.0)
    if seed <= 1e-6 or target_bpm <= 0:
        return tempo_map
    return scale_tempo_map(tempo_map, float(target_bpm) / seed)


def beat_status() -> dict:
    from audio_engine.audioset_tagger import audioset_status
    from audio_engine.madmom_beats import madmom_available

    backend = os.getenv("BEAT_TRACKER_BACKEND", "madmom").strip().lower()
    return {
        "backend": backend or "madmom",
        "madmom_available": madmom_available(),
        "audioset": audioset_status(),
    }
