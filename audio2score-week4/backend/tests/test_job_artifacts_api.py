"""Artifact listing and download without breaking existing result routes."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from urllib.parse import quote

import pretty_midi
import pytest

import database as db
import main as app_main
from engine.artifacts import ArtifactKind, ArtifactManifest, ArtifactRef
from engine.sidecars import sanitize_artifact_filename


class MemoryStorage:
    """In-memory remote backend. No filesystem, no real Supabase account."""

    backend = "memory"

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = dict(objects or {})

    def result_sidecar_key(self, result_storage_key, filename):
        return Path(filename).name

    def result_exists(self, key):
        return key in self.objects

    def read_result_bytes(self, result_storage_key):
        if result_storage_key not in self.objects:
            raise FileNotFoundError(result_storage_key)
        return self.objects[result_storage_key]

    def read_result_text(self, result_storage_key):
        return self.read_result_bytes(result_storage_key).decode("utf-8")

    def get_result_signed_url(self, result_storage_key, expires_in=3600):
        return None


def _write_midi(path: Path, pitch: int = 60) -> bytes:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=0.0, end=0.5))
    midi.instruments.append(inst)
    midi.write(str(path))
    return path.read_bytes()


def _midi_bytes(pitch: int = 60) -> bytes:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        return _write_midi(Path(tmp) / "n.mid", pitch=pitch)


def _complete_job(job_id: str, source: Path, result: Path) -> None:
    now = db.utcnow()
    db.create_job(
        {
            "id": job_id,
            "status": "completed",
            "filename": "clip.wav",
            "content_type": "audio/wav",
            "size_bytes": source.stat().st_size if source.exists() else 4,
            "storage_key": str(source),
            "result_storage_key": str(result),
            "progress": 100,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "mode": "polyphonic",
        }
    )


def _write_manifest(path: Path, job_id: str, artifacts: list[dict]) -> None:
    refs = []
    for row in artifacts:
        refs.append(
            ArtifactRef(
                kind=ArtifactKind(row["kind"]),
                path=row.get("path") or row["filename"],
                content_type=row.get("content_type") or "",
                stem_id=row.get("stem_id") or "",
                instrument=row.get("instrument") or "",
                sha256=row.get("sha256"),
                bytes=row.get("bytes"),
                artifact_id=row.get("id") or "",
                storage_key=row["filename"],
                source_stage=row.get("source_stage") or "",
                source_model=row.get("source_model") or "",
            )
        )
    ArtifactManifest(job_id=job_id, artifacts=refs).write_json(path)


def test_sanitize_artifact_filename_rejects_traversal():
    job_id = "job1"
    assert sanitize_artifact_filename(job_id, "job1.fused.mid") == "job1.fused.mid"
    assert sanitize_artifact_filename(job_id, "../other-job.raw.mid") is None
    assert sanitize_artifact_filename(job_id, "/tmp/job1.raw.mid") is None
    assert sanitize_artifact_filename(job_id, "..%2Fother-job.raw.mid") is None
    assert sanitize_artifact_filename(job_id, "other-job.raw.mid") is None
    assert sanitize_artifact_filename(job_id, "job1.raw.mid/../../secret") is None
    assert sanitize_artifact_filename(job_id, "job1_norm.wav") == "job1_norm.wav"


def test_job_artifacts_list_and_download(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    db.init_db()
    job_id = f"arts-{uuid.uuid4().hex}"
    source = tmp_path / f"{job_id}.wav"
    source.write_bytes(b"RIFF-ART")
    result = tmp_path / f"{job_id}.musicxml"
    result.write_text("<score-partwise/>", encoding="utf-8")
    raw = tmp_path / f"{job_id}.raw.mid"
    raw_bytes = _write_midi(raw, pitch=60)
    fused = tmp_path / f"{job_id}.fused.mid"
    fused_bytes = _write_midi(fused, pitch=64)
    score = tmp_path / f"{job_id}.score.mid"
    score_bytes = _write_midi(score, pitch=67)
    stem = tmp_path / f"{job_id}.stem.piano.wav"
    stem.write_bytes(b"PIANO")
    _write_manifest(
        tmp_path / f"{job_id}.manifest.json",
        job_id,
        [
            {
                "kind": ArtifactKind.MUSICXML.value,
                "filename": f"{job_id}.musicxml",
                "content_type": "application/vnd.recordare.musicxml+xml",
                "source_stage": "EXPORT",
            },
            {
                "kind": ArtifactKind.RAW_MIDI.value,
                "filename": f"{job_id}.raw.mid",
                "content_type": "audio/midi",
                "source_stage": "TRANSCRIBE_GLOBAL",
            },
            {
                "kind": ArtifactKind.PERFORMANCE_MIDI.value,
                "filename": f"{job_id}.fused.mid",
                "content_type": "audio/midi",
                "source_stage": "RECONCILE",
            },
            {
                "kind": ArtifactKind.SCORE_MIDI.value,
                "filename": f"{job_id}.score.mid",
                "content_type": "audio/midi",
                "source_stage": "EXPORT",
            },
            {
                "kind": ArtifactKind.STEM_AUDIO.value,
                "filename": f"{job_id}.stem.piano.wav",
                "content_type": "audio/wav",
                "stem_id": "piano",
                "instrument": "piano",
                "source_stage": "SEPARATE",
            },
        ],
    )
    _complete_job(job_id, source, result)
    with TestClient(app_main.app) as client:
        listed = client.get(f"/jobs/{job_id}/artifacts")
        assert listed.status_code == 200
        payload = listed.json()
        names = {row["name"] for row in payload["artifacts"]}
        assert f"{job_id}.raw.mid" in names
        assert f"{job_id}.fused.mid" in names
        assert f"{job_id}.stem.piano.wav" in names
        assert f"{job_id}.manifest.json" in names
        by_name = {row["filename"]: row for row in payload["artifacts"]}
        assert by_name[f"{job_id}.raw.mid"]["kind"] == ArtifactKind.RAW_MIDI.value
        assert "path" not in by_name[f"{job_id}.raw.mid"] or not str(
            by_name[f"{job_id}.raw.mid"].get("path") or ""
        ).startswith("/")
        midi = client.get(f"/jobs/{job_id}/result?format=midi")
        assert midi.status_code == 200
        assert midi.content == raw_bytes
        fused_dl = client.get(f"/jobs/{job_id}/result?format=fused_midi")
        assert fused_dl.status_code == 200
        assert fused_dl.content == fused_bytes
        assert fused_dl.content != raw_bytes
        score_dl = client.get(f"/jobs/{job_id}/result?format=midi_score")
        assert score_dl.status_code == 200
        assert score_dl.content == score_bytes
        assert score_dl.content != raw_bytes
        file_dl = client.get(f"/jobs/{job_id}/artifacts/{job_id}.stem.piano.wav")
        assert file_dl.status_code == 200
        assert file_dl.content == b"PIANO"
        xml = client.get(f"/jobs/{job_id}/result?format=musicxml")
        assert xml.status_code == 200
        assert b"score-partwise" in xml.content


def test_legacy_job_without_manifest_still_lists(tmp_path):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    db.init_db()
    job_id = f"legacy-{uuid.uuid4().hex}"
    source = tmp_path / f"{job_id}.wav"
    source.write_bytes(b"RIFF")
    result = tmp_path / f"{job_id}.musicxml"
    result.write_text("<score-partwise/>", encoding="utf-8")
    raw = tmp_path / f"{job_id}.raw.mid"
    _write_midi(raw)
    _complete_job(job_id, source, result)
    with TestClient(app_main.app) as client:
        listed = client.get(f"/jobs/{job_id}/artifacts")
        assert listed.status_code == 200
        names = {row["name"] for row in listed.json()["artifacts"]}
        assert f"{job_id}.raw.mid" in names
        assert f"{job_id}.musicxml" in names
        midi = client.get(f"/jobs/{job_id}/result?format=midi")
        assert midi.status_code == 200
        assert midi.content == raw.read_bytes()


def test_remote_artifact_list_and_download_without_local_files(tmp_path, monkeypatch):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    db.init_db()
    job_id = "job1"
    source = tmp_path / "unused.wav"
    source.write_bytes(b"RIFF")
    raw_bytes = _midi_bytes(60)
    fused_bytes = _midi_bytes(64)
    score_bytes = _midi_bytes(67)
    musicxml = b"<score-partwise/>"
    stem_bytes = b"PIANO-REMOTE"
    manifest = ArtifactManifest(
        job_id=job_id,
        artifacts=[
            ArtifactRef(
                kind=ArtifactKind.MUSICXML,
                path=f"{job_id}.musicxml",
                content_type="application/vnd.recordare.musicxml+xml",
                storage_key=f"{job_id}.musicxml",
                source_stage="EXPORT",
            ),
            ArtifactRef(
                kind=ArtifactKind.RAW_MIDI,
                path=f"{job_id}.raw.mid",
                content_type="audio/midi",
                storage_key=f"{job_id}.raw.mid",
                source_stage="TRANSCRIBE_GLOBAL",
            ),
            ArtifactRef(
                kind=ArtifactKind.PERFORMANCE_MIDI,
                path=f"{job_id}.fused.mid",
                content_type="audio/midi",
                storage_key=f"{job_id}.fused.mid",
                source_stage="RECONCILE",
            ),
            ArtifactRef(
                kind=ArtifactKind.SCORE_MIDI,
                path=f"{job_id}.score.mid",
                content_type="audio/midi",
                storage_key=f"{job_id}.score.mid",
                source_stage="EXPORT",
            ),
            ArtifactRef(
                kind=ArtifactKind.STEM_AUDIO,
                path=f"{job_id}.stem.piano.wav",
                content_type="audio/wav",
                stem_id="piano",
                instrument="piano",
                storage_key=f"{job_id}.stem.piano.wav",
                source_stage="SEPARATE",
            ),
        ],
    )
    remote = MemoryStorage(
        {
            f"{job_id}.musicxml": musicxml,
            f"{job_id}.manifest.json": json.dumps(manifest.to_dict()).encode(),
            f"{job_id}.raw.mid": raw_bytes,
            f"{job_id}.fused.mid": fused_bytes,
            f"{job_id}.score.mid": score_bytes,
            f"{job_id}.stem.piano.wav": stem_bytes,
        }
    )
    for name in remote.objects:
        assert not (tmp_path / name).exists()

    monkeypatch.setattr(app_main.storage_service, "get_storage", lambda: remote)
    now = db.utcnow()
    db.create_job(
        {
            "id": job_id,
            "status": "completed",
            "filename": "clip.wav",
            "content_type": "audio/wav",
            "size_bytes": 4,
            "storage_key": "remote-audio",
            "result_storage_key": f"{job_id}.musicxml",
            "progress": 100,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "mode": "polyphonic",
        }
    )
    with TestClient(app_main.app) as client:
        listed = client.get(f"/jobs/{job_id}/artifacts")
        assert listed.status_code == 200
        names = {row["filename"] for row in listed.json()["artifacts"]}
        assert f"{job_id}.musicxml" in names
        assert f"{job_id}.manifest.json" in names
        assert f"{job_id}.raw.mid" in names
        assert f"{job_id}.fused.mid" in names
        assert f"{job_id}.stem.piano.wav" in names
        by_name = {row["filename"]: row for row in listed.json()["artifacts"]}
        assert by_name[f"{job_id}.fused.mid"]["kind"] == ArtifactKind.PERFORMANCE_MIDI.value
        assert "/" not in (by_name[f"{job_id}.raw.mid"].get("storage_key") or "")

        fused_dl = client.get(f"/jobs/{job_id}/artifacts/{job_id}.fused.mid")
        assert fused_dl.status_code == 200
        assert fused_dl.content == fused_bytes

        stem_dl = client.get(f"/jobs/{job_id}/artifacts/{job_id}.stem.piano.wav")
        assert stem_dl.status_code == 200
        assert stem_dl.content == stem_bytes

        missing = client.get(f"/jobs/{job_id}/artifacts/{job_id}.ghost.mid")
        assert missing.status_code == 404

        traversal = client.get(f"/jobs/{job_id}/artifacts/../other-job.raw.mid")
        assert traversal.status_code in {404, 422}
        encoded = client.get(
            f"/jobs/{job_id}/artifacts/{quote('../other-job.raw.mid', safe='')}"
        )
        assert encoded.status_code == 404
        other = client.get(f"/jobs/{job_id}/artifacts/other-job.raw.mid")
        assert other.status_code == 404

        xml = client.get(f"/jobs/{job_id}/result?format=musicxml")
        assert xml.status_code == 200
        assert xml.content == musicxml
        midi = client.get(f"/jobs/{job_id}/result?format=midi")
        assert midi.status_code == 200
        assert midi.content == raw_bytes
        assert midi.content != fused_bytes
        score = client.get(f"/jobs/{job_id}/result?format=midi_score")
        assert score.status_code == 200
        assert score.content == score_bytes
        fused_fmt = client.get(f"/jobs/{job_id}/result?format=fused_midi")
        assert fused_fmt.status_code == 200
        assert fused_fmt.content == fused_bytes
