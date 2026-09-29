"""Real-job review registration, discovery, and validation (manifest-based)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.musical_baseline.package import build_package, report_reviews
from evaluation.musical_baseline.real_samples import (
    CASE_MANIFEST_NAME,
    REAL_BINDING_FIELDS,
    REAL_SAMPLES_DIRNAME,
    RealImportConflict,
    discover_real_case_dirs,
    import_real_job_bundle,
    list_registered_real_cases,
    validate_and_summarize_real_cases,
    validate_real_case_dir,
)
from evaluation.musical_baseline.reviews import (
    FINGERPRINT_NAME,
    REVIEW_JSON_NAME,
    load_review,
)


_TEMP_LABEL = "TEMP_TEST_DATA_NOT_A_REAL_JOB"


def _minimal_musicxml(body_note: str = "C") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN"'
        ' "http://www.musicxml.org/dtds/partwise.dtd">'
        '<score-partwise version="3.1">'
        '<part-list><score-part id="P1"><part-name>Music</part-name></score-part></part-list>'
        '<part id="P1"><measure number="1">'
        "<attributes><divisions>1</divisions>"
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f"<note><pitch><step>{body_note}</step><octave>4</octave></pitch>"
        "<duration>1</duration><type>quarter</type></note>"
        "</measure></part></score-partwise>"
    )


def _write_temp_bundle(bundle: Path, *, with_corrected: bool = True) -> Path:
    """Clearly labeled temporary test data — not a real NotaScore job."""
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "README.txt").write_text(
        f"{_TEMP_LABEL}\nSynthetic fixture for unit tests only.\n",
        encoding="utf-8",
    )
    (bundle / "original.musicxml").write_text(_minimal_musicxml("C"), encoding="utf-8")
    (bundle / "original.score.mid").write_bytes(b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x00\x60")
    if with_corrected:
        (bundle / "corrected.musicxml").write_text(
            _minimal_musicxml("D"), encoding="utf-8"
        )
        (bundle / "corrected.score.mid").write_bytes(
            b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x00\x61"
        )
    (bundle / "note_index.json").write_text(
        json.dumps(
            {
                "matched_by": "source_note_id",
                "label": _TEMP_LABEL,
                "notes": [{"source_note_id": "temp-n0", "pitch": 60}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (bundle / "corrections.json").write_text(
        json.dumps(
            {
                "label": _TEMP_LABEL,
                "operations": [{"source_note_id": "temp-n0", "velocity": 100}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle


def test_import_registers_manifest_and_hashes_original_corrected(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle")
    result = import_real_job_bundle(
        bundle,
        package_dir=package,
        job_id="TEMP001",
        example_id="real-temp-001",
        engine_commit=None,
        algorithm_version=None,
        permitted_use=None,
        title=f"{_TEMP_LABEL} demo",
    )
    assert result["example_id"] == "real-temp-001"
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-001"
    assert (case_dir / "original.musicxml").is_file()
    assert (case_dir / "corrected.musicxml").is_file()
    assert (case_dir / CASE_MANIFEST_NAME).is_file()
    manifest = json.loads((case_dir / CASE_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["case_kind"] == "real_job"
    assert manifest["comparison_model"] == "original_versus_corrected"
    assert manifest["not_algorithm_v1_v2"] is True
    assert manifest["engine"]["status"] == "unknown"
    assert manifest["permitted_use"]["status"] == "unknown"
    assert manifest["audio"]["status"] == "missing"
    assert manifest["source_note_ids"]["status"] == "present"
    fp = json.loads((case_dir / FINGERPRINT_NAME).read_text(encoding="utf-8"))
    assert fp["original_musicxml_sha256"]
    assert fp["corrected_musicxml_sha256"]
    assert fp["original_musicxml_sha256"] != fp["corrected_musicxml_sha256"]
    assert fp["not_algorithm_v1_v2"] is True
    assert "v1_musicxml_sha256" not in fp
    registered = list_registered_real_cases(package)
    assert any(r["example_id"] == "real-temp-001" for r in registered)


def test_report_reviews_discovers_real_cases_separately_from_synthetic(tmp_path: Path):
    package = tmp_path / "pkg"
    # Build synthetic package in isolation (no real cases yet).
    synth = build_package(package, render=False)
    assert synth["candidate_count"] == 15
    assert synth["p1_complete"] is False
    before_complete = synth["musician_reviewed_complete"]

    bundle = _write_temp_bundle(tmp_path / "bundle2")
    import_real_job_bundle(
        bundle,
        package_dir=package,
        job_id="TEMP002",
        example_id="real-temp-002",
        title=_TEMP_LABEL,
    )
    report = report_reviews(package)
    assert report["candidate_count"] == 15
    assert report["musician_reviewed_complete"] == before_complete
    assert report["p1_complete"] is False
    real = report["real_samples"]
    assert real["count"] == 1
    assert real["cases"][0]["example_id"] == "real-temp-002"
    assert real["cases"][0]["comparison_model"] == "original_versus_corrected"
    # Empty scaffold: not review_complete.
    assert real["musician_reviewed_complete"] == 0


def test_missing_engine_audio_and_refs_stay_explicit(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle3", with_corrected=False)
    # No engine.json, no audio, no permitted_use.
    result = import_real_job_bundle(
        bundle,
        package_dir=package,
        job_id="TEMP003",
        example_id="real-temp-003",
    )
    cm = result["case_manifest"]
    assert cm["engine"]["status"] == "unknown"
    assert cm["audio"]["status"] == "missing"
    assert cm["reference_labels"]["status"] == "missing"
    assert cm["permitted_use"]["status"] == "unknown"
    assert cm["artifacts"]["corrected_musicxml"] is None


def test_artifact_drift_marks_real_review_stale(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle4")
    import_real_job_bundle(
        bundle,
        package_dir=package,
        job_id="TEMP004",
        example_id="real-temp-004",
        engine_commit="deadbeef",
        algorithm_version="performance-score-1",
    )
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-004"
    # Complete a clearly synthetic temporary review against current fingerprint.
    fp = json.loads((case_dir / FINGERPRINT_NAME).read_text(encoding="utf-8"))
    review = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    review["attribution"] = {
        "reviewer": "Temp Test Reviewer (fixture only)",
        "role": "pytest",
        "reviewed_at": "2026-09-29",
        "contact": None,
    }
    review["artifact_binding"] = {k: fp.get(k) for k in fp if k.endswith("sha256") or k in {
        "comparison_model", "case_kind", "settings_digest"
    }}
    # Ensure all REAL binding fields present.
    review["artifact_binding"] = {k: fp.get(k) for k in REAL_BINDING_FIELDS}
    review["dimensions"]["musical_interpretation_accuracy"] = {
        "status": "pass",
        "versions": {"original": "pass", "corrected": "needs_work"},
        "score": 4,
        "notes": _TEMP_LABEL,
    }
    review["dimensions"]["human_correction_effort"] = {
        "status": "needs_work",
        "versions": {"original": None, "corrected": None},
        "score": 3,
        "notes": "estimated 8 minutes",
    }
    review["correction_time"] = {"minutes": 8, "kind": "estimated"}
    (case_dir / REVIEW_JSON_NAME).write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )
    ok = validate_real_case_dir(case_dir)
    assert ok.review_complete is True
    assert ok.binding_stale is False

    # Drift the original MusicXML bytes.
    (case_dir / "original.musicxml").write_text(
        _minimal_musicxml("E"), encoding="utf-8"
    )
    stale = validate_real_case_dir(case_dir)
    assert stale.binding_stale or stale.artifacts_stale
    assert stale.review_complete is False
    # Human review file preserved on disk.
    loaded = load_review(case_dir)
    assert loaded.data["attribution"]["reviewer"] == "Temp Test Reviewer (fixture only)"


def test_reimport_changed_original_with_human_input_does_not_overwrite(
    tmp_path: Path,
):
    """Regression: human attribution must not bypass artifact overwrite protection."""
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle_ow")
    import_real_job_bundle(
        bundle,
        package_dir=package,
        job_id="TEMP-OW",
        example_id="real-temp-ow",
    )
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-ow"
    original_bytes = (case_dir / "original.musicxml").read_bytes()
    review = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    review["attribution"]["reviewer"] = "Temp Human"
    review["attribution"]["reviewed_at"] = "2026-09-29"
    (case_dir / REVIEW_JSON_NAME).write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )

    (bundle / "original.musicxml").write_text(_minimal_musicxml("G"), encoding="utf-8")
    with pytest.raises(RealImportConflict):
        import_real_job_bundle(
            bundle,
            package_dir=package,
            job_id="TEMP-OW",
            example_id="real-temp-ow",
            force=False,
        )
    assert (case_dir / "original.musicxml").read_bytes() == original_bytes
    kept = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    assert kept["attribution"]["reviewer"] == "Temp Human"


def test_identical_reimport_is_idempotent(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle_id")
    first = import_real_job_bundle(
        bundle, package_dir=package, job_id="TEMP-ID", example_id="real-temp-id"
    )
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-id"
    original_bytes = (case_dir / "original.musicxml").read_bytes()
    mtime = (case_dir / "original.musicxml").stat().st_mtime_ns
    second = import_real_job_bundle(
        bundle, package_dir=package, job_id="TEMP-ID", example_id="real-temp-id"
    )
    assert second["import_action"] == "idempotent"
    assert second["example_id"] == first["example_id"]
    assert (case_dir / "original.musicxml").read_bytes() == original_bytes
    assert (case_dir / "original.musicxml").stat().st_mtime_ns == mtime


def test_changed_original_force_publishes_revision_preserving_old(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle_rev")
    import_real_job_bundle(
        bundle, package_dir=package, job_id="TEMP-REV", example_id="real-temp-rev"
    )
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-rev"
    old_bytes = (case_dir / "original.musicxml").read_bytes()
    old_fp = json.loads((case_dir / FINGERPRINT_NAME).read_text(encoding="utf-8"))
    review = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    review["attribution"] = {
        "reviewer": "Temp Human",
        "role": "pytest",
        "reviewed_at": "2026-09-29",
        "contact": None,
    }
    review["artifact_binding"] = {k: old_fp.get(k) for k in REAL_BINDING_FIELDS}
    review["dimensions"]["musical_interpretation_accuracy"] = {
        "status": "pass",
        "versions": {"original": "pass", "corrected": "pass"},
        "score": 4,
        "notes": _TEMP_LABEL,
    }
    review["dimensions"]["human_correction_effort"] = {
        "status": "needs_work",
        "versions": {"original": None, "corrected": None},
        "score": 3,
        "notes": "estimated",
    }
    (case_dir / REVIEW_JSON_NAME).write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )
    assert validate_real_case_dir(case_dir).review_complete is True

    (bundle / "original.musicxml").write_text(_minimal_musicxml("F"), encoding="utf-8")
    # Also omit corrected so the new revision must not leak old corrected files.
    (bundle / "corrected.musicxml").unlink()
    (bundle / "corrected.score.mid").unlink()

    result = import_real_job_bundle(
        bundle,
        package_dir=package,
        job_id="TEMP-REV",
        example_id="real-temp-rev",
        force=True,
    )
    assert result["import_action"] == "revision"
    assert result["example_id"] == "real-temp-rev-r2"
    assert result["supersedes"] == "real-temp-rev"

    # Old case untouched and still validates against old bytes.
    assert (case_dir / "original.musicxml").read_bytes() == old_bytes
    assert (case_dir / "corrected.musicxml").is_file()
    old_val = validate_real_case_dir(case_dir)
    assert old_val.review_complete is True
    assert old_val.binding_stale is False

    new_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-rev-r2"
    assert (new_dir / "original.musicxml").read_bytes() != old_bytes
    assert not (new_dir / "corrected.musicxml").is_file()
    new_manifest = json.loads((new_dir / CASE_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert new_manifest["artifacts"]["corrected_musicxml"] is None
    assert new_manifest["supersedes"] == "real-temp-rev"


def test_changed_original_without_force_rejected_even_without_human(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle_nf")
    import_real_job_bundle(
        bundle, package_dir=package, job_id="TEMP-NF", example_id="real-temp-nf"
    )
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-nf"
    original_bytes = (case_dir / "original.musicxml").read_bytes()
    (bundle / "original.musicxml").write_text(_minimal_musicxml("A"), encoding="utf-8")
    with pytest.raises(RealImportConflict):
        import_real_job_bundle(
            bundle,
            package_dir=package,
            job_id="TEMP-NF",
            example_id="real-temp-nf",
            force=False,
        )
    assert (case_dir / "original.musicxml").read_bytes() == original_bytes


def test_failed_import_leaves_previous_case_and_manifest_intact(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle_fail")
    import_real_job_bundle(
        bundle, package_dir=package, job_id="TEMP-FAIL", example_id="real-temp-fail"
    )
    before = json.loads(
        (package / REAL_SAMPLES_DIRNAME / "manifest.json").read_text(encoding="utf-8")
    )
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-fail"
    original_bytes = (case_dir / "original.musicxml").read_bytes()

    # Incomplete bundle (no original) must fail before publishing a revision.
    bad = tmp_path / "bad_bundle"
    bad.mkdir()
    (bad / "README.txt").write_text(_TEMP_LABEL, encoding="utf-8")
    (bundle / "original.musicxml").write_text(_minimal_musicxml("B"), encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        import_real_job_bundle(
            bad,
            package_dir=package,
            job_id="TEMP-FAIL",
            example_id="real-temp-fail",
            force=True,
        )
    after = json.loads(
        (package / REAL_SAMPLES_DIRNAME / "manifest.json").read_text(encoding="utf-8")
    )
    assert after == before
    assert (case_dir / "original.musicxml").read_bytes() == original_bytes
    assert not (package / REAL_SAMPLES_DIRNAME / "real-temp-fail-r2").exists()


def test_partial_and_malformed_reviews_still_block_overwrite(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle_mal")
    import_real_job_bundle(
        bundle, package_dir=package, job_id="TEMP-MAL", example_id="real-temp-mal"
    )
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-mal"
    original_bytes = (case_dir / "original.musicxml").read_bytes()

    # Partial human notes count as human input.
    review = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    review["dimensions"]["musical_interpretation_accuracy"]["notes"] = "partial note"
    (case_dir / REVIEW_JSON_NAME).write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )
    (bundle / "original.musicxml").write_text(_minimal_musicxml("B"), encoding="utf-8")
    with pytest.raises(RealImportConflict):
        import_real_job_bundle(
            bundle,
            package_dir=package,
            job_id="TEMP-MAL",
            example_id="real-temp-mal",
        )
    assert (case_dir / "original.musicxml").read_bytes() == original_bytes

    # Malformed review must also not allow silent overwrite.
    (case_dir / REVIEW_JSON_NAME).write_text("{not-json", encoding="utf-8")
    with pytest.raises(RealImportConflict):
        import_real_job_bundle(
            bundle,
            package_dir=package,
            job_id="TEMP-MAL",
            example_id="real-temp-mal",
        )
    assert (case_dir / "original.musicxml").read_bytes() == original_bytes


def test_report_only_detects_stale_after_manual_drift(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle_stale")
    import_real_job_bundle(
        bundle, package_dir=package, job_id="TEMP-ST", example_id="real-temp-st"
    )
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-st"
    fp = json.loads((case_dir / FINGERPRINT_NAME).read_text(encoding="utf-8"))
    review = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    review["attribution"] = {
        "reviewer": "Temp Human",
        "role": "pytest",
        "reviewed_at": "2026-09-29",
        "contact": None,
    }
    review["artifact_binding"] = {k: fp.get(k) for k in REAL_BINDING_FIELDS}
    review["dimensions"]["musical_interpretation_accuracy"] = {
        "status": "pass",
        "versions": {"original": "pass", "corrected": "pass"},
        "score": 4,
        "notes": _TEMP_LABEL,
    }
    review["dimensions"]["human_correction_effort"] = {
        "status": "pass",
        "versions": {"original": None, "corrected": None},
        "score": 4,
        "notes": "actual 3",
    }
    review["correction_time"] = {"minutes": 3, "kind": "actual"}
    (case_dir / REVIEW_JSON_NAME).write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )
    (case_dir / "original.musicxml").write_text(_minimal_musicxml("E"), encoding="utf-8")
    summary = validate_and_summarize_real_cases(package)
    assert summary["stale_count"] >= 1
    assert summary["cases"][0]["review"]["review_complete"] is False


def test_reimport_preserves_human_review(tmp_path: Path):
    """Identical force re-import stays idempotent and keeps human review.json."""
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle5")
    import_real_job_bundle(
        bundle,
        package_dir=package,
        job_id="TEMP005",
        example_id="real-temp-005",
    )
    case_dir = package / REAL_SAMPLES_DIRNAME / "real-temp-005"
    review = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    review["attribution"]["reviewer"] = "Temp Human"
    review["attribution"]["reviewed_at"] = "2026-09-29"
    review["dimensions"]["musical_interpretation_accuracy"]["notes"] = "keep me"
    (case_dir / REVIEW_JSON_NAME).write_text(
        json.dumps(review, indent=2) + "\n", encoding="utf-8"
    )
    result = import_real_job_bundle(
        bundle,
        package_dir=package,
        job_id="TEMP005",
        example_id="real-temp-005",
        force=True,
    )
    assert result["import_action"] == "idempotent"
    kept = json.loads((case_dir / REVIEW_JSON_NAME).read_text(encoding="utf-8"))
    assert kept["attribution"]["reviewer"] == "Temp Human"
    assert "keep me" in kept["dimensions"]["musical_interpretation_accuracy"]["notes"]


def test_discovery_lists_registered_cases(tmp_path: Path):
    package = tmp_path / "pkg"
    package.mkdir()
    bundle = _write_temp_bundle(tmp_path / "bundle6")
    import_real_job_bundle(
        bundle,
        package_dir=package,
        job_id="TEMP006",
        example_id="real-temp-006",
    )
    dirs = discover_real_case_dirs(package)
    assert [d.name for d in dirs] == ["real-temp-006"]
    summary = validate_and_summarize_real_cases(package)
    assert summary["count"] == 1
