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


def case_i_detached_triplet_groups(path: Path) -> str:
    """I. Two detached regular triplet-eighth groups; last group before silence.

    Expected: six written triplet eighths (1/3). The last note of each group,
    including the final group before silence, is a triplet eighth — not a
    sixteenth plus a tiny triplet rest. Performed 0.14s gaps are articulation.
    """
    notes = []
    # 120 BPM: quarter = 0.5s, triplet eighth = 0.5/3 s.
    pulse = 0.5 / 3.0
    for start in (0.0, pulse, 2 * pulse, 1.0, 1.0 + pulse, 1.0 + 2 * pulse):
        notes.append((72, start, start + 0.14, 84))
    return _write(path, notes)


def case_j_intentional_short_triplet_rests(path: Path) -> str:
    """J. Triplet-spaced attacks that are intentionally short.

    Expected: three short notes (32nds / shorter than a sixteenth) at 0, 1/3,
    2/3 with visible rests through each triplet pulse. Remaining to the 1/3
    pulse is a full sixteenth or more, so v2 must not fill — including the
    last note before silence.
    """
    notes = []
    pulse = 0.5 / 3.0
    for i in range(3):
        start = i * pulse
        notes.append((76, start, start + 0.04, 88))
    return _write(path, notes)


def case_k_repeated_triplet_pitches(path: Path) -> str:
    """K. Repeated same-pitch triplet eighths, last group before silence.

    Expected: six C5 triplet eighths. Re-attacks stay separate. The last
    note is 1/3, matching its siblings.
    """
    notes = []
    pulse = 0.5 / 3.0
    for i in range(6):
        start = i * pulse
        notes.append((72, start, start + 0.14, 82))
    return _write(path, notes)


def case_l_held_voice_under_triplets(path: Path) -> str:
    """L. Held independent bass under a detached triplet line.

    Expected: bass lasts the written span (a half note or tied equivalent).
    Six treble triplet eighths, including the last before silence. The
    moving attacks must not clip the hold.
    """
    notes = [(48, 0.0, 0.95, 70)]
    pulse = 0.5 / 3.0
    for i in range(6):
        start = i * pulse
        notes.append((72 + (i % 3), start, start + 0.14, 86))
    return _write(path, notes)


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


def case_final_short_then_silence(path: Path) -> str:
    """Held-out: four quarters, then a short attack followed by silence.

    Expected: the last note stays short with a visible rest. Filling it to
    the bar because leftover < a sixteenth would erase intentional silence.
    Not used to tune the last-note triplet pulse.
    """
    notes = [(72, i * 0.5, i * 0.5 + 0.45, 80) for i in range(4)]
    notes.append((74, 2.0, 2.10, 86))
    return _write(path, notes)


def case_irregular_triplet_intervals(path: Path) -> str:
    """Held-out: three attacks with irregular, not 1/3, spacing.

    Expected: keep the performed spacing family. Do not invent a regular
    triplet eighth grid or fill the last note to 1/3.
    """
    # 120 BPM seconds: 0.00, 0.19, 0.41 — not 0, 1/6, 2/6.
    notes = [
        (72, 0.00, 0.12, 84),
        (74, 0.19, 0.31, 82),
        (76, 0.41, 0.53, 80),
    ]
    return _write(path, notes)


def case_mixed_families_after_bar(path: Path) -> str:
    """Held-out: binary quarters, triplet eighths, then binary again.

    Expected: keep both families. The last triplet before the binary return
    must not steal the following quarter onset or invent a tiny rest.
    """
    notes = [(60, i * 0.5, i * 0.5 + 0.45, 76) for i in range(4)]
    pulse = 0.5 / 3.0
    for i in range(6):
        start = 2.0 + i * pulse
        notes.append((72 + i % 3, start, start + 0.14, 84))
    for i in range(4):
        start = 3.0 + i * 0.5
        notes.append((67, start, start + 0.45, 78))
    return _write(path, notes)


def case_near_barline_short_release(path: Path) -> str:
    """Held-out: a short attack just before the barline, then silence.

    Expected: written sixteenth (or shorter) plus the remaining rest. Filling
    leftover < sixteenth to the barline would hide the rest.
    """
    notes = [(72, i * 0.5, i * 0.5 + 0.45, 80) for i in range(3)]
    # Beat 4 of bar 1: 1.5s at 120 BPM. Short 16th-like release.
    notes.append((76, 1.75, 1.85, 88))
    return _write(path, notes)


def case_independent_voices_mixed_release(path: Path) -> str:
    """Held-out: held bass vs detached treble with different releases.

    Expected: bass lasts the bar. Treble keeps its own short releases and
    rests. Do not clip the hold or fill the moving line from the bass.
    """
    notes = [(48, 0.0, 1.95, 68), (50, 0.0, 0.42, 70)]
    for i in range(4):
        start = i * 0.5
        notes.append((72 + i, start, start + 0.12, 86))
    return _write(path, notes)


def case_long_monophonic_phrase(path: Path) -> str:
    """Held-out: 40 bars of a monophonic scale for multi-page export.

    Expected: one voice, intact measures, raw MIDI preserved. Used for
    pagination evidence, not last-note heuristic tuning.
    """
    notes = []
    pitches = [60, 62, 64, 65, 67, 69, 71, 72]
    for bar in range(40):
        for i, pitch in enumerate(pitches):
            start = (bar * 4 + i) * 0.5
            notes.append((pitch, start, start + 0.45, 80))
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
    "I_detached_triplet_groups": case_i_detached_triplet_groups,
    "J_intentional_short_triplet_rests": case_j_intentional_short_triplet_rests,
    "K_repeated_triplet_pitches": case_k_repeated_triplet_pitches,
    "L_held_voice_under_triplets": case_l_held_voice_under_triplets,
}

# Held-out investigation material. None of these were used to tune the
# last-note triplet-pulse fill in performance-score-2.
HELDOUT_CASES = {
    "final_short_then_silence": case_final_short_then_silence,
    "irregular_triplet_intervals": case_irregular_triplet_intervals,
    "mixed_families_after_bar": case_mixed_families_after_bar,
    "near_barline_short_release": case_near_barline_short_release,
    "independent_voices_mixed_release": case_independent_voices_mixed_release,
    "long_monophonic_phrase": case_long_monophonic_phrase,
}

HELDOUT_META = {
    "final_short_then_silence": {"meter": "4/4", "tempo": 120},
    "irregular_triplet_intervals": {"meter": "4/4", "tempo": 120},
    "mixed_families_after_bar": {"meter": "4/4", "tempo": 120},
    "near_barline_short_release": {"meter": "4/4", "tempo": 120},
    "independent_voices_mixed_release": {"meter": "4/4", "tempo": 120},
    "long_monophonic_phrase": {"meter": "4/4", "tempo": 120},
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
    "I_detached_triplet_groups": {
        "onset": "Two groups of three attacks at triplet-eighth spacing, gap of a quarter.",
        "release": "All six written as triplet eighths (1/3), including each group-ending note.",
        "engraving": "No sixteenth plus tiny triplet rest on the last note before silence.",
    },
    "J_intentional_short_triplet_rests": {
        "onset": "Three attacks at triplet-eighth spacing.",
        "release": "Sounding 32nds (or shorter) with visible rests through each 1/3 pulse.",
        "engraving": "Do not fill the last note. Remaining >= a sixteenth is a rest.",
    },
    "K_repeated_triplet_pitches": {
        "onset": "Six repeated C5 attacks at triplet-eighth spacing.",
        "release": "Six separate triplet eighths. Last note matches its siblings.",
        "engraving": "Same-pitch re-attacks stay separate; last duration is 1/3.",
    },
    "L_held_voice_under_triplets": {
        "onset": "One bass attack plus six treble triplet-eighth attacks.",
        "release": "Bass lasts its span; treble last note is a triplet eighth.",
        "engraving": "Two independent voices. Do not clip the hold.",
    },
    "mixed_tuplets": {
        "onset": "Four quarters, then six triplet-eighth attacks starting at beat 4.",
        "release": "v1: sixteenths at triplet onsets. v2: all six written 1/3, including the last.",
        "engraving": "Keep the binary quarters. Do not invent a tiny triplet rest after the last eighth.",
    },
    "final_short_then_silence": {
        "onset": "Four quarter attacks, then one short attack on the next beat.",
        "release": "Last note stays short. The following silence is a rest, not leftover articulation.",
        "engraving": "Do not fill the last note to the barline.",
    },
    "irregular_triplet_intervals": {
        "onset": "Three irregular attacks, not on a 1/3 grid.",
        "release": "Keep performed spacing. Do not rewrite as regular triplet eighths.",
        "engraving": "Exact tuplets stay exact; this fixture is not an exact tuplet.",
    },
    "mixed_families_after_bar": {
        "onset": "Four quarters, six triplet eighths, four more quarters.",
        "release": "Keep both families. Last triplet must not steal the returning quarter.",
        "engraving": "Measure integrity and onsets stay put across the family change.",
    },
    "near_barline_short_release": {
        "onset": "Three quarters, then a short attack on the last eighth of the bar.",
        "release": "Short note plus remaining rest through the barline.",
        "engraving": "Leftover < sixteenth to the bar is still a rest when the attack is short.",
    },
    "independent_voices_mixed_release": {
        "onset": "Held bass plus a short inner C3 and four short treble attacks.",
        "release": "Bass lasts the bar. Treble keeps rests. Voices stay independent.",
        "engraving": "Do not clip the hold or fill moving notes from the other voice.",
    },
    "long_monophonic_phrase": {
        "onset": "Forty bars of C-major scale quarters.",
        "release": "Written quarters. Used for multi-page export, not duration tuning.",
        "engraving": "One voice, intact measures, raw MIDI preserved.",
    },
}
