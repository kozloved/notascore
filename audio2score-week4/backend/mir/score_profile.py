"""Conservative instrument routing for the staged solo score engine."""

from dataclasses import dataclass, asdict
from statistics import median

from mir.types import InstrumentKind


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
