"""Real-world evaluation harness: manifests, skip-missing-audio, observational reports."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.realworld.evaluate import evaluate_realworld_case
from benchmark.realworld.report import (
    build_realworld_report,
    render_metrics_markdown,
    render_musician_review,
    write_realworld_reports,
)
from benchmark.realworld.schema import load_manifest
from benchmark.realworld.smoke import prepare_smoke, smoke_manifest_payload
from mir.types import Hand, MusicalEvent, NoteEvent


def test_smoke_manifest_has_three_cases_and_no_absolute_audio():
    payload = smoke_manifest_payload()
    assert len(payload["cases"]) == 3
    ids = {c["id"] for c in payload["cases"]}
    assert ids == {
        "smoke_solo_quarters",
        "smoke_compound_6_8",
        "smoke_waltz_3_4",
    }
    for row in payload["cases"]:
        assert not Path(row["audio"]).is_absolute()
        assert "copyright" not in json.dumps(row).lower()


def test_load_committed_smoke_manifest(tmp_path):
    manifest = (
        Path(__file__).resolve().parents[1]
        / "benchmark"
        / "realworld"
        / "manifests"
        / "smoke.json"
    )
    cases, meta = load_manifest(manifest, local_root=tmp_path)
    assert len(cases) == 3
    assert cases[0].audio_missing() is True
    assert "smoke.json" in meta["manifest_path"]


def test_missing_audio_is_skipped_not_failed(tmp_path):
    manifest = tmp_path / "empty.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {
                        "id": "missing_clip",
                        "audio": "nope.wav",
                        "instrumentation": "piano",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cases, _ = load_manifest(manifest, local_root=tmp_path)
    row = evaluate_realworld_case(cases[0], work_root=tmp_path / "work")
    assert row.status == "skipped"
    assert "not found" in (row.skip_reason or "")


def test_report_includes_musician_prompts(tmp_path):
    report = build_realworld_report(
        cases=[
            {
                "id": "demo",
                "title": "Demo",
                "status": "ran",
                "instrumentation": "piano",
                "notes": "room mic",
                "meter": {"predicted": "4/4", "expected": "4/4"},
                "tempo_bpm": 120.0,
                "transcription": {
                    "precision": 0.5,
                    "recall": 0.5,
                    "f1": 0.5,
                    "predicted_count": 4,
                    "reference_count": 4,
                },
                "score_midi": {"f1": None},
                "hands": {"assignments": {"left": 1, "right": 3}, "versus_reference": {}},
                "notation": {
                    "plan_success": True,
                    "fallback_used": False,
                    "measure_count": 2,
                    "xml_valid": True,
                },
                "artifacts": {
                    "audio": "/tmp/a.wav",
                    "musicxml": "/tmp/a.musicxml",
                    "raw_midi": "/tmp/a.raw.mid",
                    "score_midi": "/tmp/a.score.mid",
                },
                "meter_decision": {"reason": "estimator_winner", "confidence": 0.7, "was_hint_overridden": False},
            }
        ],
        repo=Path(__file__).resolve().parents[2],
        manifest_meta={"description": "unit"},
    )
    metrics = render_metrics_markdown(report)
    review = render_musician_review(report)
    assert "Do not tune the production algorithm" in metrics
    assert "Does the written meter" in review
    assert "demo" in metrics
    paths = write_realworld_reports(report, tmp_path / "out")
    assert paths["review"].is_file()


def test_hand_metrics_seconds_match_labeled_reference():
    from benchmark.realworld.evaluate import _hand_metrics_seconds

    predicted = [
        MusicalEvent(
            pitch=60,
            start_beat=0.0,
            duration_beats=1.0,
            hand=Hand.LEFT,
            start_time_sec=0.0,
        ),
        MusicalEvent(
            pitch=72,
            start_beat=0.0,
            duration_beats=1.0,
            hand=Hand.RIGHT,
            start_time_sec=0.0,
        ),
    ]
    reference = [
        NoteEvent(pitch=60, start_time=0.01, end_time=0.5, hand=Hand.LEFT),
        NoteEvent(pitch=72, start_time=0.02, end_time=0.5, hand=Hand.RIGHT),
    ]
    scores = _hand_metrics_seconds(predicted, reference)
    assert scores["accuracy"] == 1.0
    assert scores["total"] == 2


def test_prepare_smoke_and_run_observational_eval(tmp_path):
    """Framework proof: generated smoke audio is evaluated, not gated."""
    manifest_path = prepare_smoke(tmp_path)
    cases, _ = load_manifest(manifest_path, local_root=tmp_path)
    assert all(not c.audio_missing() for c in cases)
    from mir.pipeline import UnderstandingPipeline

    pipeline = UnderstandingPipeline(mode="fast")
    rows = [
        evaluate_realworld_case(c, work_root=tmp_path / "work", pipeline=pipeline).to_dict()
        for c in cases
    ]
    assert len(rows) == 3
    assert all(r["status"] == "ran" for r in rows)
    for row in rows:
        assert row["meter"].get("predicted")
        assert row["tempo_bpm"]
        assert row["notation"]["plan_success"] is True
        assert row["notation"]["fallback_used"] is False
        assert row["artifacts"]["musicxml"]
        assert row["artifacts"]["raw_midi"]
        assert row["artifacts"]["score_midi"]
        assert row["transcription"]["f1"] is not None
        assert row["hands"]["assignments"]
    report = build_realworld_report(
        cases=rows,
        repo=Path(__file__).resolve().parents[2],
        manifest_meta={"description": "smoke"},
    )
    review = render_musician_review(report)
    assert "Musician review sheet" in review
    assert "There is no target score per piece" in review
