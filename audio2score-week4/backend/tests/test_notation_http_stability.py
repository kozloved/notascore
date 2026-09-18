"""HTTP tests for correction merge, pickup clearing, identity, and revision publication."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pretty_midi
import pytest
from fastapi.testclient import TestClient

from tests.test_notation_correctness import _pointer, _prepare_http_job
from tests.test_notation_revision_safety import _fail_if_transcribe, isolated_db


def _client():
    import main as app_main

    return TestClient(app_main.app)


def _bundle_json(key: str, job_id: str, filename: str):
    return json.loads(Path(key).with_name(f"{job_id}.{filename}").read_text(encoding="utf-8"))


def _ops(key: str, job_id: str):
    payload = _bundle_json(key, job_id, "corrections.json")
    return payload.get("operations") or []


def _prepare_hands_job(tmp_path, job_id: str):
    import database as db
    from mir.performance_cli import convert
    from tests.test_notation_revision_safety import _job_row

    midi = pretty_midi.PrettyMIDI(initial_tempo=90)
    piano = pretty_midi.Instrument(program=0, name="Piano")
    beat = 60.0 / 90.0
    piano.notes.append(pretty_midi.Note(velocity=70, pitch=40, start=0.0, end=beat * 3.5))
    piano.notes.append(pretty_midi.Note(velocity=82, pitch=72, start=0.0, end=beat * 0.8))
    piano.notes.append(pretty_midi.Note(velocity=82, pitch=76, start=beat, end=beat * 1.8))
    midi.instruments.append(piano)
    source = tmp_path / f"{job_id}.mid"
    midi.write(str(source))
    original = source.read_bytes()
    xml_path = tmp_path / f"{job_id}.musicxml"
    convert(source, xml_path)
    (tmp_path / f"{job_id}.raw.mid").write_bytes(original)
    db.create_job(_job_row(job_id, result_storage_key=str(xml_path), edit_revision=0))
    return xml_path, original


def _save_notes(client, job_id, loaded, notes):
    return client.put(
        f"/scores/{job_id}/edits",
        json={
            "revision": loaded["revision"],
            "notes": notes,
            "tempo_bpm": loaded["tempo_bpm"],
            "time_signature": loaded["time_signature"],
            "tempo_curve": loaded.get("tempo_curve"),
        },
    )


def test_http_noop_save_of_inferred_hands_creates_no_corrections(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"noop-{uuid.uuid4().hex[:12]}"
    _prepare_hands_job(isolated_db, job_id)
    with _client() as client:
        posted = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "literal", "revision": 0},
        )
        assert posted.status_code == 200, posted.text
        assert posted.json()["transcribed"] is False
        loaded = client.get(f"/scores/{job_id}/edits")
        assert loaded.status_code == 200
        body = loaded.json()
        tracks = {row["source_note_id"] or row["id"]: int(row["track"]) for row in body["notes"]}
        assert 0 in tracks.values() and 1 in tracks.values()
        saved = _save_notes(client, job_id, body, body["notes"])
        assert saved.status_code == 200, saved.text
        assert saved.json()["has_edits"] is False
        rev, key = _pointer(job_id)
        assert _ops(key, job_id) == []
        assert saved.json()["revision"] == rev
        settings = _bundle_json(key, job_id, "notation_settings.json")
        manifest = _bundle_json(key, job_id, "revision.json")
        assert settings.get("identity_role") == "baseline_input"
        assert settings.get("describes_published_score") is False
        assert manifest.get("kind") == "note_edits"
        assert manifest.get("describes_published_score") is False


def test_http_voice_then_pitch_then_notation_keeps_voice(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"voice-{uuid.uuid4().hex[:12]}"
    _prepare_hands_job(isolated_db, job_id)
    with _client() as client:
        client.post(f"/jobs/{job_id}/notation-settings", json={"interpretation": "literal", "revision": 0})
        loaded = client.get(f"/scores/{job_id}/edits").json()
        notes = [dict(row) for row in loaded["notes"]]
        target = next(row for row in notes if int(row["pitch"]) >= 72)
        original_voice = int(target["voice"] or 0)
        target["voice"] = original_voice + 1 if original_voice < 3 else 0
        wanted_voice = int(target["voice"])
        sid = target.get("source_note_id") or target["id"]
        saved = _save_notes(client, job_id, loaded, notes)
        assert saved.status_code == 200, saved.text
        _, key1 = _pointer(job_id)
        assert any(op.get("voice") == wanted_voice and op["source_note_id"] == sid for op in _ops(key1, job_id))
        loaded2 = saved.json()
        notes2 = [dict(row) for row in loaded2["notes"]]
        other = next(row for row in notes2 if (row.get("source_note_id") or row["id"]) != sid)
        original_pitch = int(other["pitch"])
        other["pitch"] = original_pitch + 1
        saved2 = _save_notes(client, job_id, loaded2, notes2)
        assert saved2.status_code == 200, saved2.text
        _, key2 = _pointer(job_id)
        ops2 = _ops(key2, job_id)
        assert any(op.get("voice") == wanted_voice and op["source_note_id"] == sid for op in ops2)
        assert any(op.get("pitch") == original_pitch + 1 for op in ops2)
        regen = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"display_grid": "sixteenth", "revision": saved2.json()["revision"]},
        )
        assert regen.status_code == 200, regen.text
        assert regen.json()["has_edits"] is True
        _, key3 = _pointer(job_id)
        ops3 = _ops(key3, job_id)
        assert any(op.get("voice") == wanted_voice and op["source_note_id"] == sid for op in ops3)
        edited = _bundle_json(key3, job_id, "edits.json")
        kept = next(row for row in edited["notes"] if (row.get("source_note_id") or row["id"]) == sid)
        assert int(kept["voice"]) == wanted_voice
        pitched = next(
            row
            for row in edited["notes"]
            if (row.get("source_note_id") or row["id"]) == (other.get("source_note_id") or other["id"])
        )
        assert int(pitched["pitch"]) == original_pitch + 1


def test_http_staff_correction_survives_repeated_saves_and_reset_notes(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"staff-{uuid.uuid4().hex[:12]}"
    _prepare_hands_job(isolated_db, job_id)
    with _client() as client:
        first = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "literal", "meter": "4/4", "revision": 0},
        )
        assert first.status_code == 200, first.text
        loaded = client.get(f"/scores/{job_id}/edits").json()
        notes = [dict(row) for row in loaded["notes"]]
        target = next(row for row in notes if int(row["track"]) == 0)
        sid = target.get("source_note_id") or target["id"]
        uncorrected_track = int(target["track"])
        uncorrected_voice = int(target["voice"] or 0)
        uncorrected_pitch = int(target["pitch"])
        target["track"] = 1
        target["voice"] = uncorrected_voice + 1
        saved = _save_notes(client, job_id, loaded, notes)
        assert saved.status_code == 200, saved.text
        again = _save_notes(client, job_id, saved.json(), saved.json()["notes"])
        assert again.status_code == 200, again.text
        _, key = _pointer(job_id)
        ops = _ops(key, job_id)
        staff_op = next(op for op in ops if op["source_note_id"] == sid)
        assert staff_op.get("track") == 1
        assert staff_op.get("voice") == uncorrected_voice + 1
        reverted = [dict(row) for row in again.json()["notes"]]
        row = next(item for item in reverted if (item.get("source_note_id") or item["id"]) == sid)
        row["track"] = uncorrected_track
        after_track = _save_notes(client, job_id, again.json(), reverted)
        assert after_track.status_code == 200, after_track.text
        _, key2 = _pointer(job_id)
        ops2 = next(op for op in _ops(key2, job_id) if op["source_note_id"] == sid)
        assert "track" not in ops2
        assert ops2.get("voice") == uncorrected_voice + 1
        row2_notes = [dict(item) for item in after_track.json()["notes"]]
        for item in row2_notes:
            if (item.get("source_note_id") or item["id"]) == sid:
                item["voice"] = uncorrected_voice
        after_voice = _save_notes(client, job_id, after_track.json(), row2_notes)
        assert after_voice.status_code == 200, after_voice.text
        _, key3 = _pointer(job_id)
        remaining = [op for op in _ops(key3, job_id) if op["source_note_id"] == sid]
        assert remaining == []
        pitched_notes = [dict(row) for row in after_voice.json()["notes"]]
        pitched = next(item for item in pitched_notes if (item.get("source_note_id") or item["id"]) == sid)
        pitched["pitch"] = uncorrected_pitch + 2
        pitched["track"] = 1
        pitched["voice"] = uncorrected_voice + 1
        saved_all = _save_notes(client, job_id, after_voice.json(), pitched_notes)
        assert saved_all.status_code == 200
        reset = client.post(
            f"/scores/{job_id}/edits/reset",
            json={"revision": saved_all.json()["revision"]},
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["has_edits"] is False
        restored = next(
            row
            for row in reset.json()["notes"]
            if (row.get("source_note_id") or row["id"]) == sid
        )
        assert int(restored["pitch"]) == uncorrected_pitch
        assert int(restored["track"]) == uncorrected_track
        assert int(restored["voice"]) == uncorrected_voice
        listed = client.get(f"/jobs/{job_id}/notation-settings")
        assert listed.status_code == 200
        assert listed.json()["notation_settings"]["interpretation"] == "literal"
        assert listed.json()["has_edits"] is False


def test_http_pickup_clear_grid_and_reset_keep_note_corrections(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"pick-{uuid.uuid4().hex[:12]}"
    xml_path, original = _prepare_http_job(isolated_db, job_id)
    with _client() as client:
        set_pickup = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"pickup_beats": 1.0, "meter": "4/4", "revision": 0},
        )
        assert set_pickup.status_code == 200, set_pickup.text
        assert set_pickup.json()["notation_settings"]["pickup_beats"] == pytest.approx(1.0)
        _, key1 = _pointer(job_id)
        context1 = _bundle_json(key1, job_id, "interpretation_context.json")
        decisions1 = _bundle_json(key1, job_id, "notation_decisions.json")
        starts1 = [float(row["quantized_start"]) for row in decisions1["quantization_decisions"]]
        assert min(starts1) >= 2.5
        assert context1["pickup_beats"] == pytest.approx(1.0)
        clear = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"pickup_beats": None, "revision": set_pickup.json()["edit_revision"]},
        )
        assert clear.status_code == 200, clear.text
        assert clear.json()["notation_settings"]["pickup_beats"] is None
        _, key2 = _pointer(job_id)
        context2 = _bundle_json(key2, job_id, "interpretation_context.json")
        decisions2 = _bundle_json(key2, job_id, "notation_decisions.json")
        starts2 = [float(row["quantized_start"]) for row in decisions2["quantization_decisions"]]
        assert context2.get("pickup_beats") in (None, 0, 0.0)
        assert min(starts2) < min(starts1) - 1.0
        grid = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"display_grid": "sixteenth", "revision": clear.json()["edit_revision"]},
        )
        assert grid.status_code == 200, grid.text
        assert grid.json()["notation_settings"]["pickup_beats"] is None
        assert grid.json()["notation_settings"]["display_grid"] == "sixteenth"
        meter = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"meter": "3/4", "interpretation": "literal", "revision": grid.json()["edit_revision"]},
        )
        assert meter.status_code == 200, meter.text
        grid_only = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"display_grid": "eighth", "revision": meter.json()["edit_revision"]},
        )
        assert grid_only.status_code == 200, grid_only.text
        body = grid_only.json()
        assert body["notation_settings"]["meter"] == "3/4"
        assert body["notation_settings"]["interpretation"] == "literal"
        assert body["notation_settings"]["display_grid"] == "eighth"
        downbeat = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"first_downbeat_beat": 1.0, "revision": body["edit_revision"]},
        )
        assert downbeat.status_code == 200, downbeat.text
        assert downbeat.json()["notation_settings"]["first_downbeat_beat"] == pytest.approx(1.0)
        loaded = client.get(f"/scores/{job_id}/edits").json()
        notes = [dict(row) for row in loaded["notes"]]
        notes[0]["pitch"] = int(notes[0]["pitch"]) + 3
        saved = _save_notes(client, job_id, loaded, notes)
        assert saved.status_code == 200, saved.text
        reset = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"reset": True, "revision": saved.json()["revision"]},
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["has_edits"] is True
        _, key_reset = _pointer(job_id)
        kept = _bundle_json(key_reset, job_id, "edits.json")
        assert any(int(row["pitch"]) == int(notes[0]["pitch"]) for row in kept["notes"])
        settings = _bundle_json(key_reset, job_id, "notation_settings.json")
        assert settings["notation_settings"]["pickup_beats"] is None
        raw = (isolated_db / f"{job_id}.raw.mid").read_bytes()
        assert raw == original
        assert xml_path.read_bytes()


def test_http_identity_stable_over_notation_note_notation(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"id-{uuid.uuid4().hex[:12]}"
    _prepare_http_job(isolated_db, job_id)
    with _client() as client:
        first = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "literal", "revision": 0},
        )
        assert first.status_code == 200, first.text
        _, key1 = _pointer(job_id)
        settings1 = _bundle_json(key1, job_id, "notation_settings.json")
        context1 = _bundle_json(key1, job_id, "interpretation_context.json")
        assert settings1["identity_role"] == "regenerated_output"
        assert settings1["output_identity"] == context1["identity_digest"]
        assert settings1["input_identity"]
        assert settings1["notation_cache_key"] == first.json()["notation_cache_key"]
        loaded = client.get(f"/scores/{job_id}/edits").json()
        notes = [dict(row) for row in loaded["notes"]]
        notes[0]["pitch"] = int(notes[0]["pitch"]) + 2
        saved = _save_notes(client, job_id, loaded, notes)
        assert saved.status_code == 200, saved.text
        _, key2 = _pointer(job_id)
        settings2 = _bundle_json(key2, job_id, "notation_settings.json")
        context2 = _bundle_json(key2, job_id, "interpretation_context.json")
        edits2 = _bundle_json(key2, job_id, "edits.json")
        assert settings2["identity_role"] == "baseline_input"
        assert settings2.get("describes_published_score") is False
        assert context2["identity_digest"] == context1["identity_digest"]
        assert int(edits2["notes"][0]["pitch"]) == int(notes[0]["pitch"])
        second = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "literal", "revision": saved.json()["revision"]},
        )
        assert second.status_code == 200, second.text
        third = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "literal", "revision": second.json()["edit_revision"]},
        )
        assert third.status_code == 200, third.text
        _, key3 = _pointer(job_id)
        _, key4 = _pointer(job_id)
        xml3 = Path(key3).read_text(encoding="utf-8")
        settings3 = _bundle_json(key3, job_id, "notation_settings.json")
        context3 = _bundle_json(key3, job_id, "interpretation_context.json")
        ops3 = _ops(key3, job_id)
        assert settings3["identity_role"] == "regenerated_output"
        assert settings3["output_identity"] == context3["identity_digest"]
        assert any(op.get("pitch") == int(notes[0]["pitch"]) for op in ops3)
        assert "score-partwise" in xml3.lower()
        midi = client.get(f"/jobs/{job_id}/result?format=midi_score")
        xml = client.get(f"/jobs/{job_id}/result?format=musicxml")
        settings = client.get(f"/jobs/{job_id}/result?format=notation_settings")
        assert midi.status_code == 200 and midi.content[:4] == b"MThd"
        assert xml.status_code == 200 and "score-partwise" in xml.text.lower()
        assert settings.status_code == 200
        assert second.json()["midi_sha256"] == third.json()["midi_sha256"]
        stale = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "literal", "revision": 0},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "stale_revision"


def test_http_malformed_corrections_are_edit_conflict(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"bad-{uuid.uuid4().hex[:12]}"
    xml_path, original = _prepare_http_job(isolated_db, job_id)
    canonical = xml_path.read_text(encoding="utf-8")
    with _client() as client:
        posted = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "literal", "revision": 0},
        )
        assert posted.status_code == 200, posted.text
        rev, key = _pointer(job_id)
        (Path(key).parent / f"{job_id}.corrections.json").write_text(
            json.dumps({"operations": ["invalid", {"pitch": 70}]}),
            encoding="utf-8",
        )
        failed = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"display_grid": "sixteenth", "revision": rev},
        )
        assert failed.status_code == 409, failed.text
        assert failed.json()["detail"]["code"] == "edit_conflict"
        assert _pointer(job_id) == (rev, key)
        assert xml_path.read_text(encoding="utf-8") == canonical
        assert (isolated_db / f"{job_id}.raw.mid").read_bytes() == original
        listed = client.get(f"/jobs/{job_id}/notation-settings")
        assert listed.status_code == 200
        musicxml = client.get(f"/jobs/{job_id}/result?format=musicxml")
        assert musicxml.status_code == 200
