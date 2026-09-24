"""Attack articulations stay on the original note and keep source ownership."""

from __future__ import annotations

from xml.etree import ElementTree as ET

import pytest

from mir.notation_regen import NotationEditConflict, recompute_notation
from mir.notation_settings import ALGORITHM_VERSION_CURRENT, NotationSettings
from tests.test_shared_engraving import _context_for, _sid, _write_midi


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _midi_from_step(step: str, octave: int, alter: str | None = None) -> int:
    steps = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    midi = 12 * (int(octave) + 1) + steps[step]
    if alter:
        midi += int(float(alter))
    return midi


def musicxml_note_marks(xml_text: str):
    root = ET.fromstring(xml_text)
    rows = []
    measure_number = 0
    for el in root.iter():
        name = _local(el.tag)
        if name == "measure":
            measure_number = int(el.get("number") or measure_number + 1)
        if name != "note":
            continue
        if el.find(".//{*}rest") is not None:
            continue
        pitch = el.find(".//{*}pitch")
        if pitch is None:
            continue
        step = pitch.find("{*}step")
        octave = pitch.find("{*}octave")
        alter = pitch.find("{*}alter")
        if step is None or octave is None:
            continue
        arts = tuple(
            sorted(
                _local(child.tag)
                for arts in el.findall(".//{*}articulations")
                for child in list(arts)
            )
        )
        ties = tuple(
            t.get("type")
            for t in el.findall("{*}tie")
            if t.get("type")
        )
        rows.append(
            {
                "measure": measure_number,
                "pitch": _midi_from_step(
                    step.text or "",
                    int(octave.text or 0),
                    alter.text if alter is not None else None,
                ),
                "articulations": arts,
                "tie": ties[-1] if ties else None,
                "ties": ties,
                "attack": "stop" not in ties,
                "chord": el.find("{*}chord") is not None,
            }
        )
    return rows


def _recompute(tmp_path, notes, corrections=None, settings=None, name="case.mid"):
    midi_bytes = _write_midi(tmp_path / name, notes)
    from mir.midi_ingest import ingest_midi

    ingested = ingest_midi(tmp_path / name)
    context = _context_for(ingested)
    return recompute_notation(
        midi_bytes=midi_bytes,
        settings=settings or NotationSettings(),
        performance=ingested.performance,
        context=context,
        corrections=corrections,
    ), midi_bytes, ingested


def test_tenuto_three_bar_tie_marks_only_the_attack(tmp_path):
    result, midi_bytes, ingested = _recompute(
        tmp_path,
        [(72, 0.0, 5.9, 80)],
        name="tenuto-tie.mid",
    )
    sid = _sid(result, 72, 0.0)
    marked, _, _ = _recompute(
        tmp_path,
        [(72, 0.0, 5.9, 80)],
        corrections=[{"source_note_id": sid, "articulation": "tenuto"}],
        name="tenuto-tie.mid",
    )
    assert hashlib_unchanged(ingested.performance.midi_sha256, midi_bytes)
    assert next(n for n in marked.editor_model["notes"] if n["source_note_id"] == sid)[
        "articulation"
    ] == "tenuto"
    rows = [row for row in musicxml_note_marks(marked.musicxml) if row["pitch"] == 72]
    assert len(rows) >= 3
    attacks = [row for row in rows if row["attack"]]
    continues = [row for row in rows if not row["attack"]]
    assert attacks and continues
    assert all("tenuto" in row["articulations"] for row in attacks)
    assert all("tenuto" not in row["articulations"] for row in continues)
    assert all("staccato" not in row["articulations"] for row in rows)


def test_staccato_within_measure_split_marks_only_the_attack(tmp_path):
    # 2.5 beats spells as a half tied to an eighth inside one bar.
    result, midi_bytes, ingested = _recompute(
        tmp_path,
        [(76, 0.0, 1.25, 84)],
        name="staccato-split.mid",
    )
    sid = _sid(result, 76, 0.0)
    marked, _, _ = _recompute(
        tmp_path,
        [(76, 0.0, 1.25, 84)],
        corrections=[{"source_note_id": sid, "articulation": "staccato"}],
        name="staccato-split.mid",
    )
    assert hashlib_unchanged(ingested.performance.midi_sha256, midi_bytes)
    rows = [row for row in musicxml_note_marks(marked.musicxml) if row["pitch"] == 76]
    assert len(rows) >= 2
    attacks = [row for row in rows if row["attack"]]
    continues = [row for row in rows if not row["attack"]]
    assert attacks and continues
    assert all("staccato" in row["articulations"] for row in attacks)
    assert all("staccato" not in row["articulations"] for row in continues)


def test_mixed_chord_keeps_both_marks_through_velocity_export(tmp_path):
    notes = [(72, 0.0, 0.5, 80), (76, 0.0, 0.5, 80)]
    auto, midi_bytes, ingested = _recompute(tmp_path, notes, name="chord.mid")
    c5 = _sid(auto, 72, 0.0)
    e5 = _sid(auto, 76, 0.0)
    marked, _, _ = _recompute(
        tmp_path,
        notes,
        corrections=[
            {"source_note_id": c5, "articulation": "staccato"},
            {"source_note_id": e5, "articulation": "tenuto"},
        ],
        name="chord.mid",
    )
    by_id = {n["source_note_id"]: n for n in marked.editor_model["notes"]}
    assert by_id[c5]["articulation"] == "staccato"
    assert by_id[e5]["articulation"] == "tenuto"
    louder, _, _ = _recompute(
        tmp_path,
        notes,
        corrections=[
            {"source_note_id": c5, "articulation": "staccato"},
            {"source_note_id": e5, "articulation": "tenuto", "velocity": 110},
        ],
        name="chord.mid",
    )
    assert hashlib_unchanged(ingested.performance.midi_sha256, midi_bytes)
    louder_notes = {n["source_note_id"]: n for n in louder.editor_model["notes"]}
    assert louder_notes[c5]["articulation"] == "staccato"
    assert louder_notes[e5]["articulation"] == "tenuto"
    assert int(louder_notes[e5]["velocity"]) == 110
    rows = musicxml_note_marks(louder.musicxml)
    c_row = next(row for row in rows if row["pitch"] == 72)
    e_row = next(row for row in rows if row["pitch"] == 76)
    assert c_row["articulations"] == ("staccato",)
    assert e_row["articulations"] == ("tenuto",)
    assert "Tenuto" not in "".join(c_row["articulations"])
    assert c_row["attack"] and e_row["attack"]


def test_unspellable_mixed_ownership_is_an_explicit_conflict():
    from mir.models import PlannedNote
    from notation_engine.writer import NotationWriter

    writer = NotationWriter()
    el = PlannedNote(
        pitches=[72, 76],
        start_q=0,
        duration_q=1,
        voice=0,
        event_ids=["c5"],
        articulations=["staccato", "tenuto"],
    )
    with pytest.raises(ValueError, match="source-note articulation ownership|cannot be expressed"):
        writer._element_to_m21(el)


def test_default_settings_stay_on_current_algorithm():
    settings = NotationSettings()
    assert settings.algorithm_version == ALGORITHM_VERSION_CURRENT
    assert settings.uses_improved_readable() is False
    readable = NotationSettings.from_dict({"interpretation": "readable"})
    assert readable.algorithm_version == ALGORITHM_VERSION_CURRENT
    assert NotationSettings.readable_opt_in().algorithm_version == "performance-score-2"


def hashlib_unchanged(digest, midi_bytes):
    import hashlib

    assert hashlib.sha256(midi_bytes).hexdigest() == digest
    return True
