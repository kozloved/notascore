"""madmom RNN + DBN downbeat tracking (tempo map + grouping evidence).

Tempo uses beats_per_bar=[3, 4] so the beat grid stays a quarter-note family.
A second DBN with beats_per_bar=[3, 4, 6] records grouping evidence, including
6-beat compound bars. Grouping is never a final meter by itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from mir.types import TempoMap, TempoPoint

MIN_BPM = 50.0
MAX_BPM = 200.0
TEMPO_BEATS_PER_BAR = [3, 4]
GROUP_BEATS_PER_BAR = [3, 4, 6]


@dataclass
class MadmomBeatResult:
    tempo_map: TempoMap
    time_signature: str | None
    beat_times: list[float] = field(default_factory=list)
    downbeat_times: list[float] = field(default_factory=list)
    beats_per_bar: int = 4
    bpm: float = 120.0
    grouping_beats_per_bar: int | None = None
    grouping_meter: str | None = None
    grouping_beat_times: list[float] = field(default_factory=list)
    grouping_positions: list[int] = field(default_factory=list)
    grouping_search: list[int] = field(default_factory=lambda: list(GROUP_BEATS_PER_BAR))


_RNN = None
_DBN_TEMPO = None
_DBN_GROUP = None
_GROUP_SEARCH = list(GROUP_BEATS_PER_BAR)


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
    global _RNN, _DBN_TEMPO, _DBN_GROUP, _GROUP_SEARCH
    if _RNN is None:
        from madmom.features.downbeats import RNNDownBeatProcessor

        _RNN = RNNDownBeatProcessor()
    if _DBN_TEMPO is None:
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor

        _DBN_TEMPO = DBNDownBeatTrackingProcessor(
            beats_per_bar=TEMPO_BEATS_PER_BAR, fps=100
        )
    if _DBN_GROUP is None:
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor

        try:
            _DBN_GROUP = DBNDownBeatTrackingProcessor(
                beats_per_bar=GROUP_BEATS_PER_BAR, fps=100
            )
            _GROUP_SEARCH = list(GROUP_BEATS_PER_BAR)
        except Exception as exc:
            print(f"[madmom] 6-beat DBN unavailable ({exc}); grouping uses [3, 4]")
            _DBN_GROUP = _DBN_TEMPO
            _GROUP_SEARCH = list(TEMPO_BEATS_PER_BAR)
    return _RNN, _DBN_TEMPO, _DBN_GROUP


def track_downbeats(audio: NormalizedAudio) -> MadmomBeatResult | None:
    """Return beats + grouping evidence, or None if madmom is missing / fails."""
    if not madmom_available():
        return None
    y = np.asarray(audio.samples, dtype=np.float32)
    sr = int(audio.sample_rate)
    if y.size < sr // 4:
        return None
    try:
        from madmom.audio.signal import Signal

        rnn, dbn_tempo, dbn_group = _processors()
        act = rnn(Signal(y, sample_rate=sr))
        tracked_tempo = np.asarray(dbn_tempo(act), dtype=float)
        tracked_group = tracked_tempo
        if dbn_group is not dbn_tempo:
            tracked_group = np.asarray(dbn_group(act), dtype=float)
    except Exception as exc:
        print(f"[madmom] downbeat tracking failed ({exc})")
        return None
    result = result_from_beat_array(tracked_tempo)
    if result is None:
        return None
    group = result_from_beat_array(tracked_group)
    result.grouping_search = list(_GROUP_SEARCH)
    if group is not None:
        result.grouping_beats_per_bar = group.beats_per_bar
        result.grouping_meter = group.time_signature
        result.grouping_beat_times = list(group.beat_times)
        rows = np.atleast_2d(tracked_group)
        if rows.size and rows.shape[1] >= 2:
            result.grouping_positions = [int(round(float(p))) for p in rows[:, 1]]
    else:
        result.grouping_beats_per_bar = result.beats_per_bar
        result.grouping_meter = result.time_signature
        result.grouping_beat_times = list(result.beat_times)
    return result


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
    time_signature = _grouping_label(beats_per_bar)

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
        grouping_beats_per_bar=beats_per_bar,
        grouping_meter=time_signature,
        grouping_beat_times=beat_times,
        grouping_positions=[int(p) for p in positions],
        grouping_search=list(_GROUP_SEARCH),
    )


def _grouping_label(beats_per_bar: int) -> str:
    if beats_per_bar == 6:
        return "6/8"
    if beats_per_bar == 3:
        return "3/4"
    if beats_per_bar == 2:
        return "2/4"
    return "4/4"


def _beats_per_bar(positions: np.ndarray) -> int:
    """Infer grouping size from downbeat spacing (beat 1), not a final meter."""
    pos = np.asarray(positions, dtype=int)
    downbeat_idx = np.flatnonzero(pos == 1)
    if downbeat_idx.size >= 2:
        gap = int(round(float(np.median(np.diff(downbeat_idx)))))
        if gap in (2, 3, 6):
            return gap
        return 4
    unique = int(np.max(pos)) if pos.size else 4
    if unique in (2, 3, 6):
        return unique
    return 4


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
