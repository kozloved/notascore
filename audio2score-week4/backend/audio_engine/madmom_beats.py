"""madmom RNN + DBN downbeat tracking (tempo map + time signature)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import TempoMap, TempoPoint

MIN_BPM = 50.0
MAX_BPM = 200.0


@dataclass
class MadmomBeatResult:
    tempo_map: TempoMap
    time_signature: str | None
    beat_times: list[float] = field(default_factory=list)
    downbeat_times: list[float] = field(default_factory=list)
    beats_per_bar: int = 4
    bpm: float = 120.0


_RNN = None
_DBN = None


def madmom_available() -> bool:
    try:
        import madmom  # noqa: F401
        from madmom.features.downbeats import (  # noqa: F401
            DBNDownBeatTrackingProcessor,
            RNNDownBeatProcessor,
        )

        return True
    except Exception:
        return False


def _processors():
    global _RNN, _DBN
    if _RNN is None or _DBN is None:
        from madmom.features.downbeats import (
            DBNDownBeatTrackingProcessor,
            RNNDownBeatProcessor,
        )

        _RNN = RNNDownBeatProcessor()
        _DBN = DBNDownBeatTrackingProcessor(beats_per_bar=[3, 4], fps=100)
    return _RNN, _DBN


def track_downbeats(audio: NormalizedAudio) -> MadmomBeatResult | None:
    """Return beats + meter, or None if madmom is missing / fails."""
    if not madmom_available():
        return None
    y = np.asarray(audio.samples, dtype=np.float32)
    sr = int(audio.sample_rate)
    if y.size < sr // 4:
        return None
    try:
        from madmom.audio.signal import Signal

        rnn, dbn = _processors()
        act = rnn(Signal(y, sample_rate=sr))
        tracked = np.asarray(dbn(act), dtype=float)
    except Exception as exc:
        print(f"[madmom] downbeat tracking failed ({exc})")
        return None
    return result_from_beat_array(tracked)


def result_from_beat_array(tracked: np.ndarray) -> MadmomBeatResult | None:
    """Parse madmom ``[[time, beat_position], ...]`` (beat_position is 1-based)."""
    if tracked is None or tracked.size < 4:
        return None
    rows = np.atleast_2d(tracked)
    if rows.shape[1] < 2 or rows.shape[0] < 2:
        return None
    times = rows[:, 0].astype(float)
    positions = np.rint(rows[:, 1]).astype(int)
    order = np.argsort(times)
    times = times[order]
    positions = positions[order]

    intervals = np.diff(times)
    intervals = intervals[intervals > 1e-3]
    if intervals.size == 0:
        return None
    median_dt = float(np.median(intervals))
    bpm = 60.0 / median_dt
    while bpm < MIN_BPM:
        bpm *= 2
    while bpm > MAX_BPM:
        bpm /= 2

    beats_per_bar = _beats_per_bar(positions)
    time_signature = "3/4" if beats_per_bar == 3 else "4/4"

    downbeats = [float(t) for t, pos in zip(times, positions) if int(pos) == 1]
    beat_times = [float(t) for t in times]
    points = _tempo_points(times, positions, bpm, beats_per_bar)
    return MadmomBeatResult(
        tempo_map=TempoMap(points=points),
        time_signature=time_signature,
        beat_times=beat_times,
        downbeat_times=downbeats,
        beats_per_bar=beats_per_bar,
        bpm=float(bpm),
    )


def _beats_per_bar(positions: np.ndarray) -> int:
    """Infer 3/4 vs 4/4 from downbeat spacing (beat 1), not the max position."""
    pos = np.asarray(positions, dtype=int)
    downbeat_idx = np.flatnonzero(pos == 1)
    if downbeat_idx.size >= 2:
        gap = int(round(float(np.median(np.diff(downbeat_idx)))))
        if gap == 3:
            return 3
        return 4
    unique = int(np.max(pos)) if pos.size else 4
    return 3 if unique == 3 else 4


def _tempo_points(
    times: np.ndarray,
    positions: np.ndarray,
    bpm: float,
    beats_per_bar: int,
) -> list[TempoPoint]:
    """TempoMap from madmom beat times. Beat 0 at t=0; meter is stored separately."""
    del positions, beats_per_bar
    points: list[TempoPoint] = [
        TempoPoint(time_sec=0.0, beat=0.0, bpm=bpm, confidence=0.85)
    ]
    prev_t = 0.0
    prev_bpm = bpm
    beat = 0.0
    for i, raw_t in enumerate(times):
        t = float(raw_t)
        if t > prev_t:
            beat += (t - prev_t) * (prev_bpm / 60.0)
        local = prev_bpm
        if i + 1 < len(times):
            dt = float(times[i + 1] - t)
            if dt > 1e-3:
                local = min(MAX_BPM, max(MIN_BPM, 60.0 / dt))
        points.append(TempoPoint(time_sec=t, beat=beat, bpm=local, confidence=0.9))
        prev_t = t
        prev_bpm = local
    return points
