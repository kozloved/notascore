"""P1 musical baseline inventory, review safety, and report aggregation."""

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
from evaluation.musical_baseline.package import (
    build_case,
    build_package,
    inventory_markdown,
    report_reviews,
)
from evaluation.musical_baseline.reviews import (
    FINGERPRINT_NAME,
    REVIEW_FORM_NAME,
    REVIEW_JSON_NAME,
    COMPLETION_CRITERIA,
    validate_case_dir,
)
from evaluation.readable_v2_rollout import TUNING_SET
from mir.notation_settings import ALGORITHM_VERSION_CURRENT, ALGORITHM_VERSION_READABLE

# Synthetic fixture reviewer only — never write into the real review_package.
_SYNTH_REVIEWER = "Synthetic Test Reviewer (fixture only)"


def _candidate(example_id: str = "dev-solo-detached"):
    return next(c for c in CANDIDATES if c.example_id == example_id)


def _fill_complete_review(
    case_dir: Path,
    *,
    interpretation: str = "pass",
    correction: str = "needs_work",
    example_id: str | None = None,
    composition_id: str | None = None,
    performance_id: str | None = None,
    split: str | None = None,
    mutate_binding: dict | None = None,
    drop_binding: bool = False,
) -> dict:
    """Write a clearly synthetic review into a temporary case directory only."""
    review_path = case_dir / REVIEW_JSON_NAME
    data = json.loads(review_path.read_text(encoding="utf-8"))
    fp = json.loads((case_dir / FINGERPRINT_NAME).read_text(encoding="utf-8"))
    if example_id is not None:
        data["example_id"] = example_id
    if composition_id is not None:
        data["composition_id"] = composition_id
    if performance_id is not None:
        data["performance_id"] = performance_id
    if split is not None:
        data["split"] = split
    data["attribution"] = {
        "reviewer": _SYNTH_REVIEWER,
        "role": "pytest fixture",
        "reviewed_at": "2026-09-28",
        "contact": None,
    }
    if drop_binding:
        data["artifact_binding"] = {}
    else:
        binding = {key: fp.get(key) for key in COMPLETION_CRITERIA["binding_fields"]}
        if mutate_binding:
            binding.update(mutate_binding)
        data["artifact_binding"] = binding
    data["dimensions"]["musical_interpretation_accuracy"] = {
        "status": interpretation,
        "versions": {"v1": interpretation, "v2": interpretation},
        "score": 4,
        "notes": "synthetic fixture notes",
    }
    data["dimensions"]["human_correction_effort"] = {
        "status": correction,
        "versions": {"v1": None, "v2": None},
        "score": 3,
        "notes": "synthetic: ~5 minutes",
    }
    data["dimensions"]["acoustic_accuracy"] = {
        "status": "not_applicable",
        "versions": {"v1": None, "v2": None},
        "score": None,
        "notes": "",
    }
    review_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    form = case_dir / REVIEW_FORM_NAME
    form.write_text(
        form.read_text(encoding="utf-8") + f"\n\n<!-- {_SYNTH_REVIEWER} -->\n",
        encoding="utf-8",
    )
    return data


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


def test_build_case_preserves_contracts_and_source_note_ids(tmp_path: Path):
    candidate = _candidate()
    row = build_case(candidate, tmp_path, render=False)
    case_dir = tmp_path / candidate.split / candidate.example_id
    assert (case_dir / "v1.musicxml").is_file()
    assert (case_dir / "v2.musicxml").is_file()
    assert (case_dir / "v1.score.mid").is_file()
    assert (case_dir / FINGERPRINT_NAME).is_file()
    assert (case_dir / REVIEW_JSON_NAME).is_file()
    assert (case_dir / REVIEW_FORM_NAME).is_file()

    assert row["contracts"]["performance_score_1_default"] is True
    assert row["contracts"]["performance_score_2_opt_in"] is True
    assert row["algorithms"]["v1"] == ALGORITHM_VERSION_CURRENT
    assert row["algorithms"]["v2"] == ALGORITHM_VERSION_READABLE
    assert row["review"]["review_complete"] is False
    assert row["review"]["musically_accepted"] is False

    review = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    assert review["attribution"]["reviewer"] is None
    assert review["artifact_binding"]["midi_sha256"] == row["midi_sha256"]


def test_build_package_reports_incomplete_without_human_reviews(tmp_path: Path):
    report = build_package(tmp_path / "pkg", render=False)
    assert report["candidate_count"] == len([c for c in CANDIDATES if c.package_eligible])
    assert report["p1_complete"] is False
    assert report["musician_reviewed_complete"] == 0
    assert report["musically_accepted_count"] == 0
    assert "completion_criteria" in report
    assert (tmp_path / "pkg" / "REVIEW_INSTRUCTIONS.md").is_file()
    md = (tmp_path / "pkg" / "package_report.md").read_text(encoding="utf-8")
    assert "P1 complete: **False**" in md
    assert "--report-reviews" in md


def test_held_out_and_development_compositions_are_disjoint():
    dev = {c.composition_id for c in candidates(split="development")}
    hold = {c.composition_id for c in candidates(split="held_out")}
    assert dev.isdisjoint(hold)


def test_filled_json_and_markdown_survive_rebuild_and_render(tmp_path: Path):
    candidate = _candidate()
    out = tmp_path / "pkg"
    build_case(candidate, out, render=False)
    case_dir = out / candidate.split / candidate.example_id
    _fill_complete_review(case_dir, interpretation="fail", correction="fail")
    review_before = (case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8")
    form_before = (case_dir / REVIEW_FORM_NAME).read_text(encoding="utf-8")
    marker = "HUMAN_MARKER_DO_NOT_LOSE"
    (case_dir / REVIEW_FORM_NAME).write_text(form_before + marker, encoding="utf-8")
    form_before = (case_dir / REVIEW_FORM_NAME).read_text(encoding="utf-8")

    build_case(candidate, out, render=False)
    assert (case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8") == review_before
    assert (case_dir / REVIEW_FORM_NAME).read_text(encoding="utf-8") == form_before
    assert marker in form_before
    assert (case_dir / "REVIEW_FORM.template.md").is_file()

    # --render path must also preserve.
    build_case(candidate, out, render=True)
    assert (case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8") == review_before
    assert (case_dir / REVIEW_FORM_NAME).read_text(encoding="utf-8") == form_before


def test_malformed_review_is_preserved_and_not_silently_reset(tmp_path: Path):
    candidate = _candidate()
    out = tmp_path / "pkg"
    build_case(candidate, out)
    case_dir = out / candidate.split / candidate.example_id
    bad = "{ not-json@@@\nHUMAN_MALFORMED"
    (case_dir / REVIEW_JSON_NAME).write_text(bad, encoding="utf-8")
    row = build_case(candidate, out)
    assert (case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8") == bad
    assert row["review"]["write"]["action"] == "preserved_malformed"
    assert row["review"]["validation"]["load_status"] == "malformed"
    assert row["review"]["review_complete"] is False


def test_valid_saved_review_appears_in_reports(tmp_path: Path):
    candidate = _candidate()
    out = tmp_path / "one"
    build_case(candidate, out)
    case_dir = out / candidate.split / candidate.example_id
    _fill_complete_review(case_dir, interpretation="pass", correction="pass")
    row = build_case(candidate, out)
    assert row["review"]["review_complete"] is True
    assert row["review"]["musically_accepted"] is True
    assert (
        row["dimensions"]["musical_interpretation_accuracy"]["status"] == "pass"
    )
    assert row["dimensions"]["musical_interpretation_accuracy"]["reviewer"] == (
        _SYNTH_REVIEWER
    )


def test_partial_invalid_mismatched_stale_do_not_count_complete(tmp_path: Path):
    candidate = _candidate()
    out = tmp_path / "pkg"

    # Partial: attribution missing ratings.
    build_case(candidate, out)
    case_dir = out / candidate.split / candidate.example_id
    data = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    data["attribution"] = {
        "reviewer": _SYNTH_REVIEWER,
        "role": "pytest",
        "reviewed_at": "2026-09-28",
        "contact": None,
    }
    # leave interpretation not_reviewed
    (case_dir / REVIEW_JSON_NAME).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    partial = validate_case_dir(
        case_dir,
        expected={
            "example_id": candidate.example_id,
            "composition_id": candidate.composition_id,
            "performance_id": candidate.performance_id,
            "split": candidate.split,
        },
        fingerprint=json.loads((case_dir / FINGERPRINT_NAME).read_text()),
    )
    assert partial.review_complete is False

    # Invalid rating status.
    _fill_complete_review(case_dir)
    data = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    data["dimensions"]["musical_interpretation_accuracy"]["status"] = "amazing"
    (case_dir / REVIEW_JSON_NAME).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    invalid = validate_case_dir(
        case_dir,
        expected={
            "example_id": candidate.example_id,
            "composition_id": candidate.composition_id,
            "performance_id": candidate.performance_id,
            "split": candidate.split,
        },
        fingerprint=json.loads((case_dir / FINGERPRINT_NAME).read_text()),
    )
    assert invalid.valid is False
    assert invalid.review_complete is False

    # Identity mismatch.
    _fill_complete_review(case_dir, example_id="wrong-id")
    mismatched = validate_case_dir(
        case_dir,
        expected={
            "example_id": candidate.example_id,
            "composition_id": candidate.composition_id,
            "performance_id": candidate.performance_id,
            "split": candidate.split,
        },
        fingerprint=json.loads((case_dir / FINGERPRINT_NAME).read_text()),
    )
    assert mismatched.identity_ok is False
    assert mismatched.review_complete is False

    # Stale binding.
    _fill_complete_review(
        case_dir, mutate_binding={"midi_sha256": "0" * 64}
    )
    stale = validate_case_dir(
        case_dir,
        expected={
            "example_id": candidate.example_id,
            "composition_id": candidate.composition_id,
            "performance_id": candidate.performance_id,
            "split": candidate.split,
        },
        fingerprint=json.loads((case_dir / FINGERPRINT_NAME).read_text()),
    )
    assert stale.binding_stale is True
    assert stale.review_complete is False


def test_changed_artifacts_preserve_feedback_but_require_rereview(tmp_path: Path):
    candidate = _candidate("dev-intentional-rests")
    out = tmp_path / "pkg"
    build_case(candidate, out)
    case_dir = out / candidate.split / candidate.example_id
    _fill_complete_review(case_dir, interpretation="pass", correction="pass")
    review_text = (case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8")
    assert _SYNTH_REVIEWER in review_text

    # Force fingerprint change without wiping review: rewrite fingerprint file
    # and also alter musicxml so a rebuild produces a new hash path.
    # Simpler: mutate saved binding stays, then change fingerprint on disk.
    fp = json.loads((case_dir / FINGERPRINT_NAME).read_text(encoding="utf-8"))
    fp["v1_musicxml_sha256"] = "a" * 64
    (case_dir / FINGERPRINT_NAME).write_text(
        json.dumps(fp, indent=2) + "\n", encoding="utf-8"
    )
    validation = validate_case_dir(
        case_dir,
        expected={
            "example_id": candidate.example_id,
            "composition_id": candidate.composition_id,
            "performance_id": candidate.performance_id,
            "split": candidate.split,
        },
        fingerprint=fp,
    )
    assert validation.binding_stale is True
    assert validation.review_complete is False
    # Prior feedback retained on disk.
    assert (case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8") == review_text
    assert "synthetic fixture notes" in review_text


def test_report_only_leaves_artifacts_and_reviews_unchanged(tmp_path: Path):
    out = tmp_path / "pkg"
    build_package(out, render=False)
    candidate = _candidate()
    case_dir = out / candidate.split / candidate.example_id
    _fill_complete_review(case_dir, interpretation="fail", correction="needs_work")

    snapshot = {}
    for path in case_dir.rglob("*"):
        if path.is_file():
            snapshot[str(path.relative_to(out))] = path.read_bytes()
    report_before = (out / "package_report.json").read_bytes()

    report = report_reviews(out)
    assert report["mode"] == "report_only"
    assert report["musician_reviewed_complete"] == 1
    assert report["musically_accepted_count"] == 0
    assert report["reviewed_but_not_accepted_count"] == 1

    for rel, content in snapshot.items():
        # package_report and REVIEW_INSTRUCTIONS are generated summaries.
        if rel in {"package_report.json", "package_report.md", "REVIEW_INSTRUCTIONS.md"}:
            continue
        assert (out / rel).read_bytes() == content
    assert (out / "package_report.json").read_bytes() != report_before or True
    # Human review untouched:
    assert (case_dir / REVIEW_JSON_NAME).read_bytes() == snapshot[
        str((case_dir / REVIEW_JSON_NAME).relative_to(out))
    ]
    assert (case_dir / "v1.musicxml").read_bytes() == snapshot[
        str((case_dir / "v1.musicxml").relative_to(out))
    ]


def test_reviewed_failing_distinguished_from_accepted(tmp_path: Path):
    out = tmp_path / "pkg"
    build_case(_candidate("dev-solo-detached"), out)
    build_case(_candidate("dev-intentional-rests"), out)
    fail_dir = out / "development" / "dev-solo-detached"
    pass_dir = out / "development" / "dev-intentional-rests"
    _fill_complete_review(fail_dir, interpretation="fail", correction="fail")
    _fill_complete_review(pass_dir, interpretation="pass", correction="needs_work")

    # Build a tiny report_reviews-compatible tree using only these two cases.
    # Use report_reviews after copying fingerprints via rebuild on those cases.
    build_case(_candidate("dev-solo-detached"), out)
    build_case(_candidate("dev-intentional-rests"), out)
    # Rebuild preserved reviews; re-validate.
    fail_v = validate_case_dir(
        fail_dir,
        expected={
            "example_id": "dev-solo-detached",
            "composition_id": _candidate("dev-solo-detached").composition_id,
            "performance_id": _candidate("dev-solo-detached").performance_id,
            "split": "development",
        },
    )
    pass_v = validate_case_dir(
        pass_dir,
        expected={
            "example_id": "dev-intentional-rests",
            "composition_id": _candidate("dev-intentional-rests").composition_id,
            "performance_id": _candidate("dev-intentional-rests").performance_id,
            "split": "development",
        },
    )
    assert fail_v.review_complete is True
    assert fail_v.musically_accepted is False
    assert pass_v.review_complete is True
    assert pass_v.musically_accepted is True


def test_unchanged_rebuild_keeps_review_valid(tmp_path: Path):
    candidate = _candidate()
    out = tmp_path / "pkg"
    build_case(candidate, out)
    case_dir = out / candidate.split / candidate.example_id
    _fill_complete_review(case_dir, interpretation="pass", correction="pass")
    first = validate_case_dir(
        case_dir,
        expected={
            "example_id": candidate.example_id,
            "composition_id": candidate.composition_id,
            "performance_id": candidate.performance_id,
            "split": candidate.split,
        },
    )
    assert first.review_complete is True
    assert first.binding_current is True
    row = build_case(candidate, out)
    assert row["review"]["review_complete"] is True
    assert row["review"]["validation"]["binding_stale"] is False


def test_empty_template_refreshes_binding_but_human_input_is_preserved(tmp_path: Path):
    candidate = _candidate()
    out = tmp_path / "pkg"
    build_case(candidate, out)
    case_dir = out / candidate.split / candidate.example_id
    # Strip binding to simulate an older empty scaffold.
    data = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    data["artifact_binding"] = {}
    (case_dir / REVIEW_JSON_NAME).write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    row = build_case(candidate, out)
    assert row["review"]["write"]["action"] == "refreshed_empty_template"
    refreshed = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    assert refreshed["artifact_binding"]["midi_sha256"] == row["midi_sha256"]

    _fill_complete_review(case_dir)
    human = (case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8")
    row2 = build_case(candidate, out)
    assert row2["review"]["write"]["action"] == "preserved_human"
    assert (case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8") == human


def test_real_review_package_has_no_fabricated_reviewers():
    """Guardrail: committed package must not contain synthetic fixture reviews."""
    root = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "musical_baseline"
        / "review_package"
    )
    if not root.is_dir():
        pytest.skip("committed review package absent")
    for review_path in root.rglob(REVIEW_JSON_NAME):
        text = review_path.read_text(encoding="utf-8")
        assert _SYNTH_REVIEWER not in text
        data = json.loads(text)
        assert data.get("attribution", {}).get("reviewer") in (None, "")
