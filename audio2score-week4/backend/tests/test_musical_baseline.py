"""P1 musical baseline inventory, splits, and review package."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.musical_baseline.catalog import (
    CANDIDATES,
    REQUIRED_FAMILIES,
    REVIEW_DIMENSIONS,
    asset_inventory,
    candidates,
    family_coverage,
    split_leakage,
)
from evaluation.musical_baseline.package import build_case, build_package, inventory_markdown
from evaluation.readable_v2_rollout import TUNING_SET
from mir.notation_settings import ALGORITHM_VERSION_CURRENT, ALGORITHM_VERSION_READABLE


def test_candidate_set_covers_required_families_without_split_leakage():
    assert 10 <= len(CANDIDATES) <= 15
    assert split_leakage() == []
    coverage = family_coverage()
    assert coverage["complete"] is True
    for family in REQUIRED_FAMILIES:
        assert coverage["covered"][family], family
    held_out_sources = {c.source_id for c in candidates(split="held_out")}
    assert held_out_sources.isdisjoint(TUNING_SET)


def test_inventory_marks_gaps_and_does_not_claim_reviews():
    inv = asset_inventory()
    assert inv["p1_complete"] is False
    assert inv["candidate_counts"]["musician_reviewed"] == 0
    assert inv["splits_disjoint"] is True
    gap_ids = {g["id"] for g in inv["gaps"]}
    assert "paired_corpus_recordings" in gap_ids
    assert "acoustic_accuracy_labels" in gap_ids
    assert "correction_effort_labels" in gap_ids
    md = inventory_markdown(inv)
    assert "musician-reviewed" in md.lower() or "Musician-reviewed" in md
    assert "P1 complete: `False`" in md


def test_dimensions_stay_separate_and_unreviewed_by_default():
    for candidate in CANDIDATES:
        assert candidate.musician_reviewed is False
        assert set(REVIEW_DIMENSIONS) == {
            "acoustic_accuracy",
            "musical_interpretation_accuracy",
            "export_integrity",
            "human_correction_effort",
        }
        if not candidate.audio_available:
            assert candidate.acoustic_labels_available is False


def test_build_case_preserves_contracts_and_source_note_ids(tmp_path: Path):
    candidate = next(c for c in CANDIDATES if c.example_id == "dev-solo-detached")
    row = build_case(candidate, tmp_path, render=False)
    case_dir = tmp_path / candidate.split / candidate.example_id
    assert (case_dir / "v1.musicxml").is_file()
    assert (case_dir / "v2.musicxml").is_file()
    assert (case_dir / "v1.score.mid").is_file()
    assert (case_dir / "note_index.json").is_file()
    assert (case_dir / "REVIEW_FORM.md").is_file()
    assert (case_dir / "review.json").is_file()
    assert (case_dir / "phrases" / "v1_phrase.musicxml").is_file()

    assert row["contracts"]["performance_score_1_default"] is True
    assert row["contracts"]["performance_score_2_opt_in"] is True
    assert row["contracts"]["original_midi_preserved"] is True
    assert row["algorithms"]["v1"] == ALGORITHM_VERSION_CURRENT
    assert row["algorithms"]["v2"] == ALGORITHM_VERSION_READABLE
    assert row["source_midi_unchanged"] is True

    notes = json.loads((case_dir / "note_index.json").read_text(encoding="utf-8"))["notes"]
    assert notes
    assert all(n.get("source_note_id") for n in notes)

    dims = row["dimensions"]
    assert dims["acoustic_accuracy"]["status"] == "not_applicable"
    assert dims["musical_interpretation_accuracy"]["status"] == "unreviewed"
    assert dims["human_correction_effort"]["status"] == "unreviewed"
    assert dims["export_integrity"]["status"] in {"passed", "failed"}
    assert dims["export_integrity"]["score"] is None
    assert dims["musical_interpretation_accuracy"]["score"] is None

    review = json.loads((case_dir / "review.json").read_text(encoding="utf-8"))
    assert review["attribution"]["reviewer"] is None
    assert review["musician_reviewed"] is False

    form = (case_dir / "REVIEW_FORM.md").read_text(encoding="utf-8")
    assert "source_note_id" in form
    assert "human_correction_effort" in form
    assert "Attribution" in form

    ctx = row["score_context"]
    assert ctx["staff_count"] >= 1
    assert ctx["clefs"] or ctx["meters"] is not None


def test_build_package_reports_incomplete_without_human_reviews(tmp_path: Path):
    # Package a small subset by temporarily building two cases through build_package
    # would use all candidates; instead verify full package on tmp and flags.
    report = build_package(tmp_path / "pkg", render=False)
    assert report["candidate_count"] == len([c for c in CANDIDATES if c.package_eligible])
    assert report["p1_complete"] is False
    assert report["musician_reviewed_complete"] == 0
    assert report["splits_disjoint"] is True
    assert (tmp_path / "pkg" / "package_report.md").is_file()
    assert (tmp_path / "pkg" / "inventory.json").is_file()
    assert (tmp_path / "pkg" / "REVIEW_INSTRUCTIONS.md").is_file()
    md = (tmp_path / "pkg" / "package_report.md").read_text(encoding="utf-8")
    assert "P1 complete: **False**" in md
    assert "dev-solo-detached" in md
    assert "hold-meter-6-8" in md


def test_held_out_and_development_compositions_are_disjoint():
    dev = {c.composition_id for c in candidates(split="development")}
    hold = {c.composition_id for c in candidates(split="held_out")}
    assert dev.isdisjoint(hold)
    assert len(dev) == len(candidates(split="development"))
    assert len(hold) == len(candidates(split="held_out"))
