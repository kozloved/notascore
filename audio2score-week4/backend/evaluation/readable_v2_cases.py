"""Paired examples for readable-v2 diagnosis: short notes and small release gaps.

These are investigation fixtures, not production defaults. Expected notation is
musician-facing and does not treat fewer rests or ties as automatically better.
"""

from __future__ import annotations

from pathlib import Path

import hashlib
import pretty_midi

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

    The MIDI file overlaps (release after the next attack). pretty_midi
    collapses those unisons on the first note-off; new ingest FIFO-pairs them
    back to four ~0.58s performed notes. Readable mode then writes quarters
    and must not tie across the re-attacks.
    """
    notes = []
    for i in range(4):
        start = i * 0.5
        notes.append((67, start, start + 0.58, 80))
    return _write(path, notes, pedal=[(0.0, 127), (2.1, 0)])


def case_e_repeated_attacks_no_pedal(path: Path) -> str:
    """E. Repeated same-pitch attacks with no CC64.

    Expected: four separate quarters. Re-attack pairing does not require pedal.
    """
    notes = []
    for i in range(4):
        start = i * 0.5
        notes.append((67, start, start + 0.58, 80))
    return _write(path, notes)


def case_f_overlapping_unisons(path: Path) -> str:
    """F. Independent overlapping unisons (two voices, same pitch).

    Expected: two G4s starting together, both lasting a half note. Do not
    merge into one attack or steal one note's release.
    """
    return _write(path, [(67, 0.0, 1.0, 80), (67, 0.02, 1.0, 74)])


def case_g_held_voice_same_staff(path: Path) -> str:
    """G. Sustained independent voice under moving notes on the SAME staff.

    Expected: held G4 for a whole bar against four quarter notes above it.
    The moving attacks must not clip the hold.
    """
    notes = [(67, 0.0, 1.95, 70)]
    for i in range(4):
        start = i * 0.5
        notes.append((76 + i, start, start + 0.42, 86))
    return _write(path, notes)


def case_h_foreign_track_pedal(path: Path) -> str:
    """H. Pedal events belonging to another source track.

    Track 0: four detached sixteenths with visible rests.
    Track 1: a held bass note plus CC64. Pedal on that stream must not
    lengthen track 0.
    """
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    midi.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0.0))
    piano = pretty_midi.Instrument(0, name="Piano")
    for i in range(4):
        start = i * 0.5
        piano.notes.append(pretty_midi.Note(velocity=88, pitch=76, start=start, end=start + 0.10))
    other = pretty_midi.Instrument(0, name="Bass")
    other.notes.append(pretty_midi.Note(velocity=60, pitch=36, start=0.0, end=1.95))
    other.control_changes.append(pretty_midi.ControlChange(number=64, value=127, time=0.0))
    other.control_changes.append(pretty_midi.ControlChange(number=64, value=0, time=2.0))
    midi.instruments.extend([piano, other])
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    "E_repeated_attacks_no_pedal": case_e_repeated_attacks_no_pedal,
    "F_overlapping_unisons": case_f_overlapping_unisons,
    "G_held_voice_same_staff": case_g_held_voice_same_staff,
    "H_foreign_track_pedal": case_h_foreign_track_pedal,
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
    "E_repeated_attacks_no_pedal": {
        "onset": "Four repeated G4 attacks, one per quarter, no CC64.",
        "release": "Repeated quarters. Legato MIDI overlap is not a tie.",
        "engraving": "Re-attacks stay separate without pedal evidence.",
    },
    "F_overlapping_unisons": {
        "onset": "Two independent G4 attacks near the same instant.",
        "release": "Both last a half note. Neither steals the other's off.",
        "engraving": "Two printed lanes or voices; do not merge unisons.",
    },
    "G_held_voice_same_staff": {
        "onset": "Held G4 plus four upper-quarter attacks on one staff.",
        "release": "The hold lasts the bar; moving notes keep their releases.",
        "engraving": "Two independent voices on the same staff.",
    },
    "H_foreign_track_pedal": {
        "onset": "Four short treble attacks on track 0.",
        "release": "Sixteenths plus rests. Foreign-track CC64 does not lengthen them.",
        "engraving": "Do not fill to the next attack from another stream's pedal.",
    },
}
