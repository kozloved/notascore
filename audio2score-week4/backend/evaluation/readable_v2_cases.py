"""Paired examples for readable-v2 diagnosis: short notes and small release gaps.

These are investigation fixtures, not production defaults. Expected notation is
musician-facing and does not treat fewer rests or ties as automatically better.
"""

from __future__ import annotations

from pathlib import Path

from evaluation.notation_fixtures import _write


def case_a_detached_regular_line(path: Path) -> str:
    """A. Detached performance of a regular quarter line.

    Expected: eight quarter notes on the beat (possibly with staccato), not
    sixteenths plus rests. The 80ms release gaps are articulation.
    """
    notes = []
    for i in range(8):
        start = i * 0.5
        notes.append((72, start, start + 0.42, 82))
    return _write(path, notes)


def case_b_short_notes_with_rests(path: Path) -> str:
    """B. Deliberate short notes followed by meaningful rests.

    Expected: sixteenth notes on the beat with visible rests filling the rest
    of each quarter. Do not extend each attack to the next downbeat.
    """
    notes = []
    for i in range(4):
        start = i * 0.5
        notes.append((76, start, start + 0.10, 88))
    return _write(path, notes)


def case_c_repeated_attacks_under_pedal(path: Path) -> str:
    """C. Repeated same-pitch attacks under sustain pedal.

    Expected: four repeated quarter notes, not one tied sustain. Pedal is a
    performance continuation, not a single written duration.

    The MIDI overlaps (release after the next attack) currently ingest as a
    quarter plus three 32nds on both engines. That remains a limitation.
    """
    notes = []
    for i in range(4):
        start = i * 0.5
        notes.append((67, start, start + 0.58, 80))
    return _write(path, notes, pedal=[(0.0, 127), (2.1, 0)])


def case_d_independent_sustain(path: Path) -> str:
    """D. Sustained independent voice under moving notes.

    Expected: left-hand whole note (or tied halves) against right-hand eighths.
    The moving attacks must not clip the hold.
    """
    notes = [(48, 0.0, 1.95, 70)]
    for i in range(8):
        start = i * 0.25
        notes.append((72 + (i % 4), start, start + 0.22, 86))
    return _write(path, notes)


READABLE_V2_CASES = {
    "A_detached_regular_line": case_a_detached_regular_line,
    "B_short_notes_with_rests": case_b_short_notes_with_rests,
    "C_repeated_attacks_under_pedal": case_c_repeated_attacks_under_pedal,
    "D_independent_sustain": case_d_independent_sustain,
}

EXPECTED_NOTATION = {
    "A_detached_regular_line": {
        "onset": "Eight attacks on successive quarter beats.",
        "release": "Written as quarters; 80ms gaps are articulation, not rests.",
        "engraving": "Single-voice quarter line. Staccato marks optional.",
    },
    "B_short_notes_with_rests": {
        "onset": "Four attacks on successive quarter beats.",
        "release": "Sounding sixteenths with visible rests through each quarter.",
        "engraving": "Do not fill to the next attack. The rest is the music.",
    },
    "C_repeated_attacks_under_pedal": {
        "onset": "Four repeated G4 attacks, one per quarter.",
        "release": "Repeated quarters, not one tied note. Pedal is performance.",
        "engraving": "Same pitch re-attacks stay separate under CC64.",
    },
    "D_independent_sustain": {
        "onset": "One bass attack plus eight treble eighths.",
        "release": "Bass lasts the bar; eighths keep their own releases.",
        "engraving": "Two independent voices. Do not clip the hold.",
    },
}
