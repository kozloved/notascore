"""HTTP integration for Readable v3 + automatic swing. Requires the FastAPI stack."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from evaluation.swing_fixtures import SWING_FIXTURES
from mir.notation_settings import (
    ALGORITHM_VERSION_CURRENT,
    ALGORITHM_VERSION_READABLE_V2,
)
from tests.helpers.transcription import fail_if_transcribe
from tests.test_notation_correctness import _prepare_http_job
from tests.test_notation_http_stability import _note, _save_notes
from tests.test_notation_revision_safety import _job_row, isolated_db

pytestmark = pytest.mark.app


def test_first_editor_open_publishes_swing_context_without_settings_post(
    isolated_db, monkeypatch
):
    """E. Function-level HTTP, not a browser session. First GET /edits matches the score."""
    fail_if_transcribe(monkeypatch)
    import database as db
    import main as app_main
    from mir.pipeline import UnderstandingPipeline

    job_id = f"swing-open-{uuid.uuid4().hex[:12]}"
    source = isolated_db / f"{job_id}.mid"
    SWING_FIXTURES["swing_2_to_1"](source)
    original = source.read_bytes()
    UnderstandingPipeline().transcribe_midi(source, job_id)
    out_dir = isolated_db / f"bp_{job_id}"
    xml_path = out_dir / f"{job_id}.musicxml"
    edits_path = out_dir / f"{job_id}.edits.json"
    assert xml_path.is_file()
    assert edits_path.is_file()
    (isolated_db / f"{job_id}.raw.mid").write_bytes(original)
    db.create_job(_job_row(job_id, result_storage_key=str(xml_path), edit_revision=0))

    with TestClient(app_main.app) as client:
        settings = client.get(f"/jobs/{job_id}/notation-settings")
        assert settings.status_code == 200
        body = settings.json()
        assert body["algorithm_version"] == "performance-score-3"
        assert body["notation_settings"]["rhythmic_feel"] == "auto"
        assert body["detected_interpretation"]["rhythmic_feel"] == "swing_eighths"
        loaded = client.get(f"/scores/{job_id}/edits")
        assert loaded.status_code == 200
        notes = loaded.json()["notes"]
        assert any(note.get("performed_start_beat") is not None for note in notes)
        assert any(note.get("stream_key") for note in notes)
        starts = sorted({round(float(n["start"]), 4) for n in notes})
        assert starts[:4] == [0.0, 0.5, 1.0, 1.5]
        xml = client.get(f"/jobs/{job_id}/result?format=musicxml")
        assert xml.status_code == 200
        assert "Swing" in xml.text
        raw = client.get(f"/jobs/{job_id}/result?format=midi")
        assert raw.content == original


def test_articulation_edit_survives_regen_without_locking_swing_timing(
    isolated_db, monkeypatch
):
    """F. Articulation correction persists without locking unrelated timing."""
    fail_if_transcribe(monkeypatch)
    import database as db
    import main as app_main
    from mir.pipeline import UnderstandingPipeline

    job_id = f"swing-art-{uuid.uuid4().hex[:12]}"
    source = isolated_db / f"{job_id}.mid"
    SWING_FIXTURES["swing_2_to_1"](source)
    original = source.read_bytes()
    UnderstandingPipeline().transcribe_midi(source, job_id)
    xml_path = isolated_db / f"bp_{job_id}" / f"{job_id}.musicxml"
    (isolated_db / f"{job_id}.raw.mid").write_bytes(original)
    db.create_job(_job_row(job_id, result_storage_key=str(xml_path), edit_revision=0))
    with TestClient(app_main.app) as client:
        loaded = client.get(f"/scores/{job_id}/edits")
        notes = [dict(row) for row in loaded.json()["notes"]]
        target = notes[0]
        sid = target.get("source_note_id") or target["id"]
        original_start = float(target["start"])
        original_duration = float(target["duration"])
        target["articulation"] = "staccato"
        target["articulation_source"] = "user_edit"
        saved = _save_notes(client, job_id, loaded.json(), notes)
        assert saved.status_code == 200, saved.text
        marked = _note(saved.json(), sid)
        assert marked.get("articulation") == "staccato"
        assert marked.get("articulation_source") == "user_edit"
        assert not marked.get("score_timing_locked")
        assert float(marked["start"]) == pytest.approx(original_start, abs=1e-3)
        assert float(marked["duration"]) == pytest.approx(original_duration, abs=1e-3)
        regen = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"revision": saved.json()["revision"]},
        )
        assert regen.status_code == 200
        assert regen.json()["transcribed"] is False
        after = client.get(f"/scores/{job_id}/edits")
        row = _note(after.json(), sid)
        assert row.get("articulation") == "staccato"
        assert row.get("articulation_source") == "user_edit"
        assert float(row["start"]) == pytest.approx(original_start, abs=1e-3)
        assert (isolated_db / f"{job_id}.raw.mid").read_bytes() == original


def test_saved_v1_and_v2_do_not_silently_upgrade_to_v3(isolated_db, monkeypatch):
    """G. Opening a legacy Readable score keeps its engine until explicit upgrade."""
    fail_if_transcribe(monkeypatch)
    import main as app_main

    job_id = f"legacy-{uuid.uuid4().hex[:12]}"
    _xml_path, original = _prepare_http_job(isolated_db, job_id)
    with TestClient(app_main.app) as client:
        listed = client.get(f"/jobs/{job_id}/notation-settings")
        assert listed.json()["algorithm_version"] == "performance-score-3"
        v1 = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={
                "interpretation": "readable",
                "algorithm_version": ALGORITHM_VERSION_CURRENT,
                "revision": 0,
            },
        )
        assert v1.status_code == 200
        assert v1.json()["algorithm_version"] == "performance-score-1"
        opened = client.get(f"/jobs/{job_id}/notation-settings")
        assert opened.json()["algorithm_version"] == "performance-score-1"
        same = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "readable", "revision": v1.json()["edit_revision"]},
        )
        assert same.json()["algorithm_version"] == "performance-score-1"
        v2 = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={
                "interpretation": "readable",
                "algorithm_version": ALGORITHM_VERSION_READABLE_V2,
                "revision": same.json()["edit_revision"],
            },
        )
        assert v2.json()["algorithm_version"] == "performance-score-2"
        upgrade = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={
                "interpretation": "readable",
                "apply_current_readable": True,
                "revision": v2.json()["edit_revision"],
            },
        )
        assert upgrade.json()["algorithm_version"] == "performance-score-3"
        assert upgrade.json()["transcribed"] is False
        raw = client.get(f"/jobs/{job_id}/result?format=midi")
        assert raw.content == original
