"""Human-reviewed fixtures: acoustic vs readability vs export stay separate."""

from __future__ import annotations

from evaluation.human_review import evaluate_case
from evaluation.human_reviewed.fixtures import CASES, prepare_human_reviewed


def test_prepare_writes_required_families(tmp_path):
    written = prepare_human_reviewed(tmp_path)
    ids = {path.name for path in written}
    assert ids == {spec["id"] for spec in CASES}
    for path in written:
        assert (path / "input.mid").is_file()
        assert (path / "reference.mid").is_file()
        assert (path / "case.yaml").is_file()


def test_tracks_are_independent(tmp_path):
    prepare_human_reviewed(tmp_path)
    reports = {
        case.name: evaluate_case(case, tmp_path / "out" / case.name)
        for case in tmp_path.iterdir()
        if case.is_dir() and (case / "case.yaml").exists()
    }
    assert set(reports) >= {"rubato", "ornaments", "pedal", "repeated_notes", "meter_changes"}
    for case_id, report in reports.items():
        tracks = report["tracks"]
        assert set(tracks) == {"acoustic", "readability", "export"}
        assert "passed" in tracks["acoustic"]
        assert tracks["readability"].get("human_rating_required") is True
        assert tracks["export"]["mechanical"] is True
        assert report.get("score_is_hypothesis") is True
        assert report.get("note_count_is_not_readability") is True
        # A single collapsed score would mix these. Keep them distinct.
        assert tracks["acoustic"]["track"] != tracks["readability"]["track"]
        if case_id == "meter_changes":
            # Changing meter is still a product gap; export may fail while
            # acoustic identity of the MIDI fixture still evaluates.
            assert tracks["acoustic"]["status"] in {"passed", "failed"}
            assert tracks["export"]["status"] in {"passed", "failed"}
        if case_id == "repeated_notes":
            assert tracks["acoustic"]["metrics"]["predicted_count"] >= 4
            assert tracks["acoustic"]["metrics"]["reference_count"] == 4
