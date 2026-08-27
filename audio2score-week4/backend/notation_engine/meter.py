"""Time signature and key hints from quantized MusicalEvent[]."""

from __future__ import annotations

from mir.types import MusicalEvent

DEFAULT_TIME_SIG = "4/4"

_CANDIDATES: tuple[tuple[str, float, tuple[float, ...]], ...] = (
    ("4/4", 4.0, (0.0, 2.0)),
    ("3/4", 3.0, (0.0,)),
    ("2/4", 2.0, (0.0,)),
    ("6/8", 3.0, (0.0, 1.5)),
)

# Krumhansl-Schmuckler key profiles
_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
_PC_NAMES = ("C", "C#", "D", "E-", "E", "F", "F#", "G", "A-", "A", "B-", "B")


def estimate_time_signature(events: list[MusicalEvent]) -> str:
    """Keep 4/4 unless another meter is clearly a better fit for barline onsets."""
    if len(events) < 6:
        return DEFAULT_TIME_SIG
    onsets = [e.start_beat for e in events]
    end = max(e.start_beat + e.duration_beats for e in events)

    def _score(bar_len: float, strong: tuple[float, ...]) -> float:
        hits = 0
        total = 0
        t = 0.0
        while t + 0.25 < end:
            for beat in strong:
                target = t + beat
                if any(abs(o - target) <= 0.12 for o in onsets):
                    hits += 1
                total += 1
            t += bar_len
        return hits / max(total, 1)

    scores = {name: _score(bar, strong) for name, bar, strong in _CANDIDATES}
    best = max(scores, key=lambda k: scores[k])
    if best != DEFAULT_TIME_SIG and scores[best] >= scores[DEFAULT_TIME_SIG] + 0.12:
        return best
    return DEFAULT_TIME_SIG


def _unique_pcs(events: list[MusicalEvent]) -> set[int]:
    return {int(e.pitch) % 12 for e in events}


def _exact_triad_key(pcs: set[int]) -> str | None:
    """If the texture is only a major or minor triad, return that key."""
    if len(pcs) != 3:
        return None
    major = None
    minor = None
    for root in pcs:
        third_maj = (root + 4) % 12
        third_min = (root + 3) % 12
        fifth = (root + 7) % 12
        if {third_maj, fifth} <= pcs:
            major = _PC_NAMES[root]
        if {third_min, fifth} <= pcs:
            minor = _PC_NAMES[root].lower()
    if major and not minor:
        return major
    if minor and not major:
        return minor
    return None


def estimate_key(events: list[MusicalEvent]) -> str | None:
    """Return a music21 key name (e.g. 'C' or 'a') when the profile is decisive."""
    usable = [e for e in events if 36 <= int(e.pitch) <= 96]
    if len(usable) < 4:
        return None
    triad = _exact_triad_key(_unique_pcs(usable))
    if triad:
        return triad
    hist = [0.0] * 12
    # Short melodies: unique pitch classes so a repeated dominant/tonic
    # (or a split last note) does not flip F minor into C.
    if len(usable) < 16:
        seen = {int(e.pitch) % 12 for e in usable}
        for pc in seen:
            hist[pc] = 1.0
    else:
        for ev in usable:
            hist[ev.pitch % 12] += max(ev.duration_beats, 0.25)

    def _corr(profile: tuple[float, ...], shift: int) -> float:
        rotated = [profile[(i - shift) % 12] for i in range(12)]
        mean_h = sum(hist) / 12.0
        mean_p = sum(rotated) / 12.0
        num = sum((hist[i] - mean_h) * (rotated[i] - mean_p) for i in range(12))
        den_h = sum((hist[i] - mean_h) ** 2 for i in range(12)) ** 0.5
        den_p = sum((rotated[i] - mean_p) ** 2 for i in range(12)) ** 0.5
        if den_h < 1e-9 or den_p < 1e-9:
            return 0.0
        return num / (den_h * den_p)

    ranked: list[tuple[float, str]] = []
    for shift in range(12):
        ranked.append((_corr(_MAJOR, shift), _PC_NAMES[shift]))
        ranked.append((_corr(_MINOR, shift), _PC_NAMES[shift].lower()))
    ranked.sort(reverse=True)
    best_score, best_key = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    if best_score < 0.4 or best_score - second < 0.08:
        return None
    return best_key


def bar_length(time_sig: str) -> float:
    """QuarterLength of one bar."""
    try:
        num, den = time_sig.split("/", 1)
        return (float(num) * 4.0) / float(den)
    except (ValueError, ZeroDivisionError):
        return 4.0
