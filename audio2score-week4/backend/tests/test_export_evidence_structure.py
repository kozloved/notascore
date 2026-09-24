"""Export evidence compares engraving structure, not meter alone."""

from __future__ import annotations

from evaluation.notation_correctness_evidence import (
    ARTICULATION_CHANGE_KINDS,
    _pdf_record,
    _visual_record,
    compare_engraving,
    engraving_structure,
    inspect_xml,
    musicxml_members,
    parse_pdf_page_count,
)
from evaluation.notation_fixtures import fixture_68, fixture_mixed_release_chord, fixture_mixed_tuplets
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


def test_mixed_chord_mre_has_per_member_marks():
    from pathlib import Path

    xml = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "osmd_mixed_chord_mre.musicxml"
    ).read_text(encoding="utf-8")
    inspected = inspect_xml(xml)
    assert inspected["mixed_chord_marks"] is True
    assert inspected["marked_notes"] == 2


MINIMAL_ONE_PAGE_PDF = (
    b"%PDF-1.1\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


def _mixed_chord_mre() -> str:
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "osmd_mixed_chord_mre.musicxml"
    ).read_text(encoding="utf-8")


def _swap_mixed_chord_marks(xml: str) -> str:
    """Swap staccato/tenuto between the E4 and G4 chord members."""
    return (
        xml.replace(
            "<notations><articulations><staccato/></articulations></notations>",
            "<notations><articulations><__SWAP_TENUTO__/></articulations></notations>",
            1,
        )
        .replace(
            "<notations><articulations><tenuto/></articulations></notations>",
            "<notations><articulations><staccato/></articulations></notations>",
            1,
        )
        .replace("__SWAP_TENUTO__", "tenuto")
    )


def test_swapped_chord_articulation_ownership_fails_notation_compare():
    original = _mixed_chord_mre()
    swapped = _swap_mixed_chord_marks(original)
    orig_members = musicxml_members(original)
    swapped_members = musicxml_members(swapped)
    assert [(row["pitch"], row["articulations"]) for row in orig_members] == [
        (64, ("staccato",)),
        (67, ("tenuto",)),
    ]
    assert [(row["pitch"], row["articulations"]) for row in swapped_members] == [
        (64, ("tenuto",)),
        (67, ("staccato",)),
    ]
    comparison = compare_engraving(original, swapped, kind="notation")
    assert comparison["comparison"] == "unchanged_engraving"
    assert comparison["structure_equal"] is False
    assert comparison["pass"] is False
    assert comparison["meter_equal"] is True
    assert comparison["meter_only_insufficient"] is True


def test_velocity_edit_on_mixed_chord_still_passes_notation_compare(tmp_path):
    path = tmp_path / "chord.mid"
    fixture_mixed_release_chord(path)
    original = path.read_bytes()
    ingested = ingest_midi(path)
    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    by_pitch = {int(n["pitch"]): n for n in auto.editor_model["notes"]}
    sid = by_pitch[64].get("source_note_id") or by_pitch[64]["id"]
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": sid, "velocity": 108}],
    )
    assert path.read_bytes() == original
    comparison = compare_engraving(auto.musicxml, edited.musicxml, kind="notation")
    assert comparison["pass"] is True
    assert comparison["structure_equal"] is True
    assert musicxml_members(auto.musicxml)
    assert musicxml_members(auto.musicxml) == musicxml_members(edited.musicxml)


def test_malformed_pdf_is_not_export_success(tmp_path):
    path = tmp_path / "fake.pdf"
    path.write_text('{"pages": 2}\nthis is not a PDF\n', encoding="utf-8")
    record = _pdf_record(
        {"returncode": 0, "pdf": True, "stdout": '{"pages": 2}\n'},
        path,
        expected_pages=2,
    )
    parsed = parse_pdf_page_count(path.read_bytes())
    assert parsed["ok"] is False
    assert record["export_completed"] is True
    assert record["pdf_parsed"] is False
    assert record["page_count_verified"] is False
    assert record["visual_review_completed"] is False
    assert record["status"] == "failed"
    assert record["counts_as_success"] is False
    assert record["all_pages_checked"] is False


def test_pdf_page_count_mismatch_fails(tmp_path):
    path = tmp_path / "one.pdf"
    path.write_bytes(MINIMAL_ONE_PAGE_PDF)
    parsed = parse_pdf_page_count(path.read_bytes())
    assert parsed == {"ok": True, "pages": 1, "reason": None}
    record = _pdf_record(
        {"returncode": 0, "pdf": True, "stdout": '{"pages": 2}\n'},
        path,
        expected_pages=2,
    )
    assert record["export_completed"] is True
    assert record["pdf_parsed"] is True
    assert record["parsed_pages"] == 1
    assert record["expected_pages"] == 2
    assert record["page_count_verified"] is False
    assert record["visual_review_completed"] is False
    assert record["status"] == "failed"
    assert record["counts_as_success"] is False
    assert record["all_pages_checked"] is False


def test_parsed_pdf_matching_osmd_pages_passes_without_visual_review(tmp_path):
    path = tmp_path / "one.pdf"
    path.write_bytes(MINIMAL_ONE_PAGE_PDF)
    record = _pdf_record(
        {"returncode": 0, "pdf": True, "stdout": '{"pages": 1}\n'},
        path,
        expected_pages=1,
    )
    assert record["status"] == "passed"
    assert record["page_count_verified"] is True
    assert record["visual_review_completed"] is False
    assert record["pages_rendered"] is False


def test_screenshots_do_not_complete_visual_review(tmp_path):
    out = tmp_path / "automatic_osmd"
    out.mkdir()
    (out / "osmd-page-1.svg").write_text("<svg/>", encoding="utf-8")
    record = _visual_record(
        {"returncode": 0, "html": True, "png": True, "svg": True},
        out,
    )
    assert record["pages_rendered"] is True
    assert record["visual_review_completed"] is False
    assert record["counts_as_success"] is False
    assert record["status"] != "passed"


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
