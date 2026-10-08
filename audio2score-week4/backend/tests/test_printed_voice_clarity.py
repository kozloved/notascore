"""Printed two-voice staves must stay readable, not stacked as one chord."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from evaluation.notation_correctness_evidence import _build
from evaluation.readable_v2_cases import READABLE_V2_CASES
from mir.notation_settings import NotationSettings


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _notes(xml: str):
    root = ET.fromstring(xml)
    rows = []
    for el in root.iter():
        if _local(el.tag) != "note":
            continue
        if el.find("{*}rest") is not None:
            continue
        step = el.find("{*}pitch/{*}step")
        octave = el.find("{*}pitch/{*}octave")
        alter = el.find("{*}pitch/{*}alter")
        voice = el.find("{*}voice")
        stem = el.find("{*}stem")
        typ = el.find("{*}type")
        chord = el.find("{*}chord") is not None
        rows.append(
            {
                "step": None if step is None else step.text,
                "octave": None if octave is None else octave.text,
                "alter": None if alter is None else alter.text,
                "voice": None if voice is None else voice.text,
                "stem": None if stem is None else stem.text,
                "type": None if typ is None else typ.text,
                "chord": chord,
            }
        )
    return rows


def test_inner_hold_keeps_opposite_stems_from_the_moving_line(tmp_path):
    source = tmp_path / "hold.mid"
    READABLE_V2_CASES["G_held_voice_same_staff"](source)
    original = source.read_bytes()
    result, _ = _build(source, NotationSettings(), meter="4/4", tempo=120.0)
    assert source.read_bytes() == original
    notes = _notes(result.musicxml)
    held = [row for row in notes if row["step"] == "G" and row["octave"] == "4"]
    moving = [row for row in notes if row["type"] == "quarter"]
    assert [row["type"] for row in held] == ["half", "half"]
    assert len(moving) == 4
    assert {row["stem"] for row in held} == {"down"}
    assert {row["stem"] for row in moving} == {"up"}
    assert held[0]["voice"] != moving[0]["voice"]
    pitches = sorted(
        int(n["pitch"])
        for n in result.editor_model["notes"]
    )
    assert pitches == [67, 76, 77, 78, 79]
    written = next(n for n in result.editor_model["notes"] if int(n["pitch"]) == 67)
    assert round(float(written["duration"]), 4) == 4.0


def test_hold_under_chords_keeps_the_inner_voice_distinct(tmp_path):
    source = tmp_path / "dyads.mid"
    READABLE_V2_CASES["hold_under_mixed_release_chords"](source)
    original = source.read_bytes()
    result, _ = _build(source, NotationSettings(), meter="4/4", tempo=120.0)
    assert source.read_bytes() == original
    notes = _notes(result.musicxml)
    held = [row for row in notes if row["step"] == "G" and row["octave"] == "4"]
    moving = [
        row
        for row in notes
        if not (row["step"] == "G" and row["octave"] == "4") and not row["chord"]
    ]
    assert [row["type"] for row in held] == ["half", "half"]
    assert {row["stem"] for row in held} == {"down"}
    assert {row["stem"] for row in moving} == {"up"}
    written = sorted(
        (round(float(n["start"]), 4), int(n["pitch"]), round(float(n["duration"]), 4))
        for n in result.editor_model["notes"]
    )
    assert (0.0, 67, 4.0) in written
    assert all(dur == 1.0 for start, pitch, dur in written if pitch != 67)


def test_hold_under_staccato_dyads_prints_tied_halves_not_a_stacked_whole(tmp_path):
    source = tmp_path / "staccato-hold.mid"
    READABLE_V2_CASES["hold_under_strongly_detached"](source)
    original = source.read_bytes()
    result, _ = _build(source, NotationSettings(), meter="4/4", tempo=120.0)
    assert source.read_bytes() == original
    notes = _notes(result.musicxml)
    held = [row for row in notes if row["step"] == "G" and row["octave"] == "4"]
    moving = [
        row
        for row in notes
        if row["step"] == "C" and not row["chord"]
    ]
    assert [row["type"] for row in held] == ["half", "half", "half", "half"]
    assert {row["stem"] for row in held} == {"down"}
    assert {row["stem"] for row in moving} == {"up"}
    assert held[0]["voice"] != moving[0]["voice"]
    written = next(n for n in result.editor_model["notes"] if int(n["pitch"]) == 67)
    assert round(float(written["duration"]), 4) == 8.0
    assert written.get("articulation") in (None, "")


def test_single_voice_whole_chord_stays_a_whole_note(tmp_path):
    source = tmp_path / "whole-chord.mid"
    READABLE_V2_CASES["early_release_chord_to_bar"](source)
    result, _ = _build(source, NotationSettings(), meter="4/4", tempo=120.0)
    notes = _notes(result.musicxml)
    types = {row["type"] for row in notes}
    assert types == {"whole"}
    assert all(row["stem"] is None for row in notes)


def test_single_voice_detached_line_does_not_force_stems(tmp_path):
    source = tmp_path / "line.mid"
    READABLE_V2_CASES["mixed_release_quarters"](source)
    result, _ = _build(source, NotationSettings(), meter="4/4", tempo=120.0)
    notes = _notes(result.musicxml)
    treble = [row for row in notes if row["octave"] == "5" or row["step"] in {"C", "D", "E"}]
    assert treble
    assert all(row["stem"] is None for row in treble)


def test_overlapping_unisons_take_opposite_stems(tmp_path):
    source = tmp_path / "unison.mid"
    READABLE_V2_CASES["F_overlapping_unisons"](source)
    original = source.read_bytes()
    result, _ = _build(source, NotationSettings(), meter="4/4", tempo=120.0)
    assert source.read_bytes() == original
    notes = _notes(result.musicxml)
    treble = [row for row in notes if row["step"] == "G" and row["octave"] == "4"]
    assert len(treble) == 2
    assert {row["stem"] for row in treble} == {"up", "down"}
    assert treble[0]["voice"] != treble[1]["voice"]
    durations = sorted(round(float(n["duration"]), 4) for n in result.editor_model["notes"])
    assert durations == [2.0, 2.0]
