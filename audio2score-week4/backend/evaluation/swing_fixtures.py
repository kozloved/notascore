"""Deterministic MIDI fixtures for style-aware rhythmic interpretation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pretty_midi


def _write(path: Path, notes, *, tempo=120, meter=(4, 4)):
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    midi.time_signature_changes.append(
        pretty_midi.TimeSignature(meter[0], meter[1], 0.0)
    )
    piano = pretty_midi.Instrument(0, name="Piano")
    for pitch, start, end, velocity in notes:
        piano.notes.append(
            pretty_midi.Note(velocity=velocity, pitch=pitch, start=start, end=end)
        )
    midi.instruments.append(piano)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _q(beats, tempo=120.0) -> float:
    return float(beats) * (60.0 / float(tempo))


def fixture_straight_eighths_jitter(path: Path) -> str:
    notes = []
    for i in range(16):
        start = _q(i * 0.5) + (0.008 if i % 2 else -0.006)
        notes.append((72, start, start + _q(0.42), 80))
    return _write(path, notes)


def fixture_swing_2_to_1(path: Path) -> str:
    notes = []
    for beat in range(8):
        down = _q(beat)
        off = _q(beat + 2.0 / 3.0)
        notes.append((72, down, off - 0.01, 84))
        notes.append((74, off, _q(beat + 1.0) - 0.01, 78))
    return _write(path, notes)


def fixture_swing_3_to_2(path: Path) -> str:
    notes = []
    off_frac = 1.5 / 2.5
    for beat in range(8):
        down = _q(beat)
        off = _q(beat + off_frac)
        notes.append((71, down, off - 0.01, 82))
        notes.append((74, off, _q(beat + 1.0) - 0.01, 76))
    return _write(path, notes)


def fixture_triplets_inside_swing(path: Path) -> str:
    notes = []
    for beat in range(4):
        down = _q(beat)
        off = _q(beat + 2.0 / 3.0)
        notes.append((72, down, off - 0.01, 84))
        notes.append((74, off, _q(beat + 1.0) - 0.01, 78))
    for i in range(3):
        start = _q(4.0 + i / 3.0)
        notes.append((76 + i, start, start + _q(0.28), 86))
    for beat in range(5, 8):
        down = _q(beat)
        off = _q(beat + 2.0 / 3.0)
        notes.append((72, down, off - 0.01, 84))
        notes.append((74, off, _q(beat + 1.0) - 0.01, 78))
    return _write(path, notes)


def fixture_dotted_rhythms(path: Path) -> str:
    notes = []
    for beat in range(8):
        down = _q(beat)
        sixteenth = _q(beat + 0.75)
        notes.append((67, down, sixteenth - 0.01, 80))
        notes.append((69, sixteenth, _q(beat + 1.0) - 0.01, 76))
    return _write(path, notes)


def fixture_rubato_no_swing(path: Path) -> str:
    notes = []
    t = 0.0
    for i in range(8):
        notes.append((60 + i, t, t + 0.42, 80))
        t += 0.48 + i * 0.035
    return _write(path, notes)


def fixture_compound_6_8(path: Path) -> str:
    notes = []
    # 90 BPM: eighth = 1/3 s. Equal compound subdivisions, not swing.
    tempo = 90
    for i in range(12):
        start = _q(i * 0.5, tempo)
        notes.append((64 + (i % 3), start, start + _q(0.42, tempo), 80))
    return _write(path, notes, tempo=90, meter=(6, 8))


def fixture_straight_to_swing(path: Path) -> str:
    notes = []
    for i in range(8):
        start = _q(i * 0.5)
        notes.append((72, start, start + _q(0.42), 80))
    for beat in range(4, 8):
        down = _q(beat)
        off = _q(beat + 2.0 / 3.0)
        notes.append((76, down, off - 0.01, 84))
        notes.append((77, off, _q(beat + 1.0) - 0.01, 78))
    return _write(path, notes)


def fixture_sparse_swing(path: Path) -> str:
    notes = [(72, _q(i), _q(i) + _q(0.85), 80) for i in range(8)]
    notes.append((74, _q(2.0 + 2.0 / 3.0), _q(3.0) - 0.01, 76))
    return _write(path, notes)


def fixture_swing_sixteenths(path: Path) -> str:
    notes = []
    off_frac = 2.0 / 3.0 * 0.5
    for i in range(16):
        start = _q(i * 0.5)
        off = _q(i * 0.5 + off_frac)
        notes.append((72, start, off - 0.005, 84))
        notes.append((74, off, _q((i + 1) * 0.5) - 0.005, 78))
    return _write(path, notes)


def fixture_dotted_inside_swing(path: Path) -> str:
    notes = []
    for beat in range(4):
        down = _q(beat)
        off = _q(beat + 2.0 / 3.0)
        notes.append((72, down, off - 0.01, 84))
        notes.append((74, off, _q(beat + 1.0) - 0.01, 78))
    notes.append((67, _q(4.0), _q(4.75) - 0.01, 80))
    notes.append((69, _q(4.75), _q(5.0) - 0.01, 76))
    for beat in range(5, 8):
        down = _q(beat)
        off = _q(beat + 2.0 / 3.0)
        notes.append((72, down, off - 0.01, 84))
        notes.append((74, off, _q(beat + 1.0) - 0.01, 78))
    return _write(path, notes)


def fixture_polyphony_chords_ties(path: Path) -> str:
    notes = []
    for beat in range(8):
        down = _q(beat)
        off = _q(beat + 2.0 / 3.0)
        for pitch in (60, 64, 67):
            notes.append((pitch, down, off - 0.01, 70))
            notes.append((pitch + 12, off, _q(beat + 1.0) - 0.01, 82))
    notes.append((48, 0.0, _q(6.2), 64))
    return _write(path, notes)


SWING_FIXTURES = {
    "straight_eighths_jitter": fixture_straight_eighths_jitter,
    "swing_2_to_1": fixture_swing_2_to_1,
    "swing_3_to_2": fixture_swing_3_to_2,
    "triplets_inside_swing": fixture_triplets_inside_swing,
    "dotted_rhythms": fixture_dotted_rhythms,
    "rubato_no_swing": fixture_rubato_no_swing,
    "compound_6_8": fixture_compound_6_8,
    "straight_to_swing": fixture_straight_to_swing,
    "sparse_swing": fixture_sparse_swing,
    "polyphony_chords_ties": fixture_polyphony_chords_ties,
    "swing_sixteenths": fixture_swing_sixteenths,
    "dotted_inside_swing": fixture_dotted_inside_swing,
}
