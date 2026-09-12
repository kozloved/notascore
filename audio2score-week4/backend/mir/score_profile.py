"""Conservative instrument routing for the staged solo score engine."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from statistics import median
from typing import Sequence

from mir.performance import instrument_for_program
from mir.types import InstrumentKind, MusicalEvent, NoteEvent, copy_event


@dataclass(frozen=True)
class ScoreProfile:
    grand_staff: bool
    program: int | None
    clef: str
    evidence: str

    def to_dict(self):
        return asdict(self)


def score_profile(events):
    programs = {e.source_program for e in events if e.source_program is not None}
    kinds = {e.instrument for e in events if e.instrument != InstrumentKind.UNKNOWN}
    tracks = {e.source_track_id for e in events if e.source_track_id}
    if len(programs) > 1 or (not programs and len(kinds) > 1):
        raise ValueError("Ensemble score interpretation is not yet validated; provide one instrument per MIDI")
    program = next(iter(programs), None)
    piano = 0 <= program <= 7 if program is not None else kinds <= {InstrumentKind.PIANO}
    if not piano and len(tracks) > 1:
        raise ValueError("Multiple solo-instrument tracks require ensemble interpretation")
    return ScoreProfile(piano, program,
                        "bass" if events and median(e.pitch for e in events) < 60 else "treble",
                        "midi_program" if program is not None else "instrument_prediction" if kinds else "piano_compatibility_assumption")


def _dominant_program(events: Sequence) -> int:
    programs = [int(e.source_program) for e in events if getattr(e, "source_program", None) is not None]
    if not programs:
        return 0
    piano = [p for p in programs if 0 <= p <= 7]
    pool = piano or programs
    return Counter(pool).most_common(1)[0][0]


def collapse_for_solo_notation(events: Sequence):
    """Keep every attack; unify program/tracks so the solo planner can run.

    Used for MT3 / polyphonic outputs that carry multiple GM programs. The
    raw provider MIDI and performance snapshot stay untouched upstream.
    Returns (events, profile, warning_or_none).
    """
    rows = list(events)
    try:
        return rows, score_profile(rows), None
    except ValueError as exc:
        message = str(exc)
        if "Ensemble" not in message and "ensemble" not in message.lower():
            raise

    dominant = _dominant_program(rows)
    kind = instrument_for_program(dominant)
    piano = 0 <= dominant <= 7
    collapsed = []
    for event in rows:
        changes = {
            "source_program": dominant,
            "instrument": kind,
        }
        if not piano:
            changes["source_track_id"] = ""
        if isinstance(event, MusicalEvent):
            collapsed.append(copy_event(event, **changes))
        elif isinstance(event, NoteEvent):
            from dataclasses import replace

            collapsed.append(replace(event, **changes))
        else:
            collapsed.append(event)
    profile = score_profile(collapsed)
    warning = (
        f"Multi-instrument MIDI collapsed to program {dominant} "
        f"({kind.value}) for solo notation; source attacks preserved"
    )
    # Mark collapse in profile evidence without changing ScoreProfile shape.
    profile = ScoreProfile(
        grand_staff=profile.grand_staff,
        program=profile.program,
        clef=profile.clef,
        evidence=f"{profile.evidence};solo_collapse",
    )
    return collapsed, profile, warning
