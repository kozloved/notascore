"""Small MIDI fixtures for performance-to-score interpretation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pretty_midi


def _write(path: Path, notes, *, tempo=120, meter=(4, 4), pedal=None, tempos=None):
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    if meter:
        midi.time_signature_changes.append(
            pretty_midi.TimeSignature(meter[0], meter[1], 0.0)
        )
    if tempos:
        midi._tick_scales = []
        for time_sec, bpm in tempos:
            seconds_per_tick = 60.0 / (float(bpm) * midi.resolution)
            midi._tick_scales.append((midi.time_to_tick(time_sec), seconds_per_tick))
        midi._update_tick_to_time(0)
    piano = pretty_midi.Instrument(0, name="Piano")
    for pitch, start, end, velocity in notes:
        piano.notes.append(
            pretty_midi.Note(velocity=velocity, pitch=pitch, start=start, end=end)
        )
    if pedal:
        for time_sec, value in pedal:
            piano.control_changes.append(
                pretty_midi.ControlChange(number=64, value=value, time=time_sec)
            )
    midi.instruments.append(piano)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_humanized_quarters(path: Path) -> str:
    # 120 BPM: quarter = 0.5s. Small late attacks and short release gaps.
    notes = []
    for i in range(8):
        start = i * 0.5 + 0.012
        notes.append((72, start, start + 0.465, 80))
    return _write(path, notes)


def fixture_short_rests_and_repeats(path: Path) -> str:
    notes = []
    # Two sixteenths, a short rest, two sixteenths, repeated attacks.
    starts = [0.0, 0.125, 0.375, 0.5, 0.625, 0.75, 0.875]
    for i, start in enumerate(starts):
        notes.append((76, start, start + 0.10, 82))
    return _write(path, notes)


def fixture_melody_over_bass(path: Path) -> str:
    notes = [(48, 0.0, 3.9, 70), (50, 0.0, 3.9, 68)]
    for i in range(8):
        notes.append((72 + (i % 3), i * 0.5 + 0.02, i * 0.5 + 0.42, 88))
    return _write(path, notes, pedal=[(0.0, 127), (3.6, 0)])


def fixture_syncopation(path: Path) -> str:
    # Off-beat quarters crossing beats and a sustain over the barline.
    notes = [
        (72, 0.25, 0.75, 80),
        (74, 0.75, 1.25, 80),
        (76, 1.25, 1.75, 80),
        (77, 1.75, 2.5, 80),
        (79, 2.5, 4.4, 78),
    ]
    return _write(path, notes)


def fixture_34(path: Path) -> str:
    notes = [(72 + i, i * 0.5, i * 0.5 + 0.45, 80) for i in range(6)]
    return _write(path, notes, meter=(3, 4))


def fixture_68(path: Path) -> str:
    # 90 BPM: quarter = 2/3s, dotted quarter (compound beat) = 1.0s.
    notes = [
        (60, 0.0, 1.0, 78),
        (64, 1.0, 2.0, 78),
        (67, 2.0, 3.0, 80),
        (72, 3.0, 4.0, 82),
    ]
    return _write(path, notes, meter=(6, 8), tempo=90)


def fixture_mixed_tuplets(path: Path) -> str:
    notes = [(60, i * 0.5, i * 0.5 + 0.45, 76) for i in range(4)]
    for i in range(6):
        start = 2.0 + i * (1.0 / 3.0) / 2  # wait, 120bpm quarter=0.5s, triplet eighth = 1/6s
        start = 2.0 + i * (0.5 / 3.0)
        notes.append((72 + i % 3, start, start + 0.14, 84))
    return _write(path, notes)


def fixture_rubato_pickup(path: Path) -> str:
    # Pickup eighth then quarters, with a slowing tempo map.
    notes = [(71, 0.0, 0.22, 80)]
    t = 0.25
    for i in range(6):
        notes.append((72 + i % 4, t, t + 0.42, 82))
        t += 0.55 + i * 0.03
    return _write(path, notes, tempos=[(0.0, 120), (1.5, 100), (3.0, 88)])


def fixture_unison_and_crossing(path: Path) -> str:
    notes = [
        (48, 0.0, 2.0, 70),
        (60, 0.0, 0.5, 80),
        (64, 0.5, 1.0, 82),
        (43, 1.0, 1.5, 74),
        (76, 1.0, 1.5, 86),
        (55, 1.5, 2.0, 80),
        (79, 1.5, 2.0, 84),
    ]
    # Independent overlapping unisons at the same pitch, distinct attacks.
    notes.append((67, 0.25, 1.1, 77))
    notes.append((67, 0.5, 1.25, 81))
    return _write(path, notes)


FIXTURES = {
    "humanized_quarters": fixture_humanized_quarters,
    "short_rests_repeats": fixture_short_rests_and_repeats,
    "melody_over_bass": fixture_melody_over_bass,
    "syncopation": fixture_syncopation,
    "meter_3_4": fixture_34,
    "meter_6_8": fixture_68,
    "mixed_tuplets": fixture_mixed_tuplets,
    "rubato_pickup": fixture_rubato_pickup,
    "unison_crossing": fixture_unison_and_crossing,
}
