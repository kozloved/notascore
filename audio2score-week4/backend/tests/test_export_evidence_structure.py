"""Export evidence compares engraving structure, not meter alone."""

from __future__ import annotations

from evaluation.notation_correctness_evidence import (
    ARTICULATION_CHANGE_KINDS,
    _pdf_record,
    _visual_record,
    compare_engraving,
    engraving_structure,
    inspect_xml,
)
from evaluation.notation_fixtures import fixture_68, fixture_mixed_tuplets
from mir.midi_ingest import ingest_midi
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings
from tests.test_shared_engraving import _context_for


def test_velocity_edit_keeps_full_engraving_structure(tmp_path):
    path = tmp_path / "mixed.mid"
    fixture_mixed_tuplets(path)
    original = path.read_bytes()
    ingested = ingest_midi(path)
    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    sid = auto.editor_model["notes"][0].get("source_note_id") or auto.editor_model["notes"][0]["id"]
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": sid, "velocity": 108}],
    )
    assert path.read_bytes() == original
    comparison = compare_engraving(auto.musicxml, edited.musicxml, kind="notation")
    assert comparison["comparison"] == "unchanged_engraving"
    assert comparison["structure_equal"] is True
    assert comparison["pass"] is True
    assert comparison["meter_equal"] is True
    assert comparison["meter_only_insufficient"] is False
    auto_struct = engraving_structure(auto.musicxml)
    edited_struct = engraving_structure(edited.musicxml)
    assert auto_struct["time_signatures"]
    assert auto_struct == edited_struct


def test_articulation_edit_is_classified_separately(tmp_path):
    path = tmp_path / "mixed.mid"
    fixture_mixed_tuplets(path)
    original = path.read_bytes()
    ingested = ingest_midi(path)
    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    sid = auto.editor_model["notes"][0].get("source_note_id") or auto.editor_model["notes"][0]["id"]
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": sid, "articulation": "tenuto"}],
    )
    assert path.read_bytes() == original
    comparison = compare_engraving(auto.musicxml, edited.musicxml, kind="marked_note")
    assert "marked_note" in ARTICULATION_CHANGE_KINDS
    assert comparison["comparison"] == "articulation_change"
    assert comparison["structure_equal"] is False
    assert comparison["structure_equal_ignoring_articulations"] is True
    assert comparison["pass"] is True


def test_skipped_screenshot_is_not_visual_success(tmp_path):
    out = tmp_path / "automatic_osmd"
    out.mkdir()
    record = _visual_record(
        {"returncode": 0, "html": True, "png": False, "svg": False},
        out,
    )
    assert record["status"] == "skipped"
    assert record["counts_as_success"] is False
    assert record["pages_checked"] == 0


def test_pdf_skip_is_not_export_success(tmp_path):
    record = _pdf_record({"skipped": True}, tmp_path / "missing.pdf")
    assert record["status"] == "skipped"
    assert record["counts_as_success"] is False
    assert record["all_pages_checked"] is False


def test_meter_6_8_structure_keeps_compound_signature(tmp_path):
    path = tmp_path / "meter.mid"
    fixture_68(path)
    original = path.read_bytes()
    ingested = ingest_midi(path)
    result = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested, selected_meter="6/8", display_bpm=90.0),
    )
    assert path.read_bytes() == original
    inspected = inspect_xml(result.musicxml)
    structure = engraving_structure(result.musicxml)
    assert "6/8" in inspected["shape"]["time_signatures"]
    assert "6/8" in structure["time_signatures"]
    assert "4/4" not in structure["time_signatures"]
