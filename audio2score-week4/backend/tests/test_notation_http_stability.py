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
from score_edits import extract_from_musicxml


def _client():
    import main as app_main

    return TestClient(app_main.app)


def _bundle_json(key: str, job_id: str, filename: str):
    return json.loads(Path(key).with_name(f"{job_id}.{filename}").read_text(encoding="utf-8"))


def _ops(key: str, job_id: str):
    payload = _bundle_json(key, job_id, "corrections.json")
    return payload.get("operations") or []


def _uncorrected(key: str, job_id: str):
    payload = _bundle_json(key, job_id, "corrections.json")
    return payload.get("uncorrected") or {}


def _note(model, sid):
    return next(row for row in model["notes"] if (row.get("source_note_id") or row["id"]) == sid)


def _assert_artifacts_agree(client, job_id, editor, *, sid, pitch=None, track=None, start=None, duration=None, velocity=None):
    xml = client.get(f"/jobs/{job_id}/result?format=musicxml")
    midi = client.get(f"/jobs/{job_id}/result?format=midi_score")
    assert xml.status_code == 200 and "score-partwise" in xml.text.lower()
    assert midi.status_code == 200 and midi.content[:4] == b"MThd"
    parsed = extract_from_musicxml(xml.text)
    editor_row = _note(editor, sid)
    xml_row = next(
        (
            row
            for row in parsed["notes"]
            if row.get("source_note_id") == sid
            or (
                int(row["pitch"]) == int(editor_row["pitch"])
                and int(row["track"]) == int(editor_row["track"])
            )
        ),
        None,
    )
    assert xml_row is not None, f"MusicXML missing source note {sid}"
    if pitch is not None:
        assert int(editor_row["pitch"]) == pitch
        assert int(xml_row["pitch"]) == pitch
    if track is not None:
        assert int(editor_row["track"]) == track
        assert int(xml_row["track"]) == track
    if start is not None:
        assert float(editor_row["start"]) == pytest.approx(start, abs=1e-3)
        assert float(xml_row["start"]) == pytest.approx(start, abs=0.26)
    if duration is not None:
        assert float(editor_row["duration"]) == pytest.approx(duration, abs=1e-3)
        assert float(xml_row["duration"]) == pytest.approx(duration, abs=0.26)
    if velocity is not None:
        assert int(editor_row["velocity"]) == velocity
        assert int(xml_row["velocity"]) == velocity
        import io

        score = pretty_midi.PrettyMIDI(io.BytesIO(midi.content))
        velocities = [note.velocity for inst in score.instruments for note in inst.notes]
        assert velocity in velocities


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


def _regen_twice(client, job_id, revision, *, extra=None):
    payload = {"display_grid": "sixteenth", "revision": revision}
    if extra:
        payload.update(extra)
    first = client.post(f"/jobs/{job_id}/notation-settings", json=payload)
    assert first.status_code == 200, first.text
    second = client.post(
        f"/jobs/{job_id}/notation-settings",
        json={"display_grid": "sixteenth", "revision": first.json()["edit_revision"]},
    )
    assert second.status_code == 200, second.text
    return second


def test_http_staff_voice_return_after_double_regen_and_reset(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"base-{uuid.uuid4().hex[:12]}"
    xml_path, original = _prepare_hands_job(isolated_db, job_id)
    with _client() as client:
        posted = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "literal", "revision": 0},
        )
        assert posted.status_code == 200, posted.text
        loaded = client.get(f"/scores/{job_id}/edits").json()
        notes = [dict(row) for row in loaded["notes"]]
        target = next(row for row in notes if int(row["track"]) == 0)
        sid = target.get("source_note_id") or target["id"]
        other = next(row for row in notes if (row.get("source_note_id") or row["id"]) != sid)
        other_sid = other.get("source_note_id") or other["id"]
        uncorrected_track = int(target["track"])
        uncorrected_voice = int(target["voice"] or 0)
        uncorrected_pitch = int(target["pitch"])
        other_pitch = int(other["pitch"])
        target["track"] = 1
        target["voice"] = uncorrected_voice + 1
        other["pitch"] = other_pitch + 2
        saved = _save_notes(client, job_id, loaded, notes)
        assert saved.status_code == 200, saved.text
        after_two = _regen_twice(client, job_id, saved.json()["revision"])
        assert after_two.json()["has_edits"] is True
        _, key = _pointer(job_id)
        context = _bundle_json(key, job_id, "interpretation_context.json")
        stored_unc = _uncorrected(key, job_id)
        assert stored_unc[sid]["track"] == uncorrected_track
        assert stored_unc[sid]["voice"] == uncorrected_voice
        layout_row = next(row for row in context["layout_decisions"] if row.get("note_id") == sid)
        assert layout_row.get("voice_provenance") != "user_edit"
        assert layout_row.get("hand") != "left"
        edited = client.get(f"/scores/{job_id}/edits").json()
        kept = _note(edited, sid)
        assert int(kept["track"]) == 1
        assert int(kept["voice"]) == uncorrected_voice + 1
        _assert_artifacts_agree(client, job_id, edited, sid=sid, track=1, pitch=uncorrected_pitch)
        other_row = _note(edited, other_sid)
        assert int(other_row["pitch"]) == other_pitch + 2
        reset = client.post(
            f"/scores/{job_id}/edits/reset",
            json={"revision": edited["revision"]},
        )
        assert reset.status_code == 200, reset.text
        restored = _note(reset.json(), sid)
        assert int(restored["track"]) == uncorrected_track
        assert int(restored["voice"]) == uncorrected_voice
        assert int(restored["pitch"]) == uncorrected_pitch
        assert reset.json()["has_edits"] is False
        listed = client.get(f"/jobs/{job_id}/notation-settings")
        assert listed.json()["notation_settings"]["interpretation"] == "literal"
        assert listed.json()["notation_settings"]["display_grid"] == "sixteenth"
        _assert_artifacts_agree(
            client, job_id, reset.json(), sid=sid, track=uncorrected_track, pitch=uncorrected_pitch
        )
        _, key_reset = _pointer(job_id)
        reset_unc = _uncorrected(key_reset, job_id)
        assert reset_unc[sid]["track"] == uncorrected_track
        assert reset_unc[sid]["voice"] == uncorrected_voice
        assert reset_unc[sid]["track"] != 1
        assert (isolated_db / f"{job_id}.raw.mid").read_bytes() == original
        assert xml_path.read_bytes()


def test_http_manual_revert_after_double_regen_restores_staff_voice(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"revt-{uuid.uuid4().hex[:12]}"
    _prepare_hands_job(isolated_db, job_id)
    with _client() as client:
        client.post(f"/jobs/{job_id}/notation-settings", json={"interpretation": "literal", "revision": 0})
        loaded = client.get(f"/scores/{job_id}/edits").json()
        notes = [dict(row) for row in loaded["notes"]]
        target = next(row for row in notes if int(row["track"]) == 0)
        sid = target.get("source_note_id") or target["id"]
        other = next(row for row in notes if (row.get("source_note_id") or row["id"]) != sid)
        other_sid = other.get("source_note_id") or other["id"]
        uncorrected_track = int(target["track"])
        uncorrected_voice = int(target["voice"] or 0)
        other_pitch = int(other["pitch"])
        target["track"] = 1
        target["voice"] = uncorrected_voice + 1
        other["pitch"] = other_pitch + 1
        saved = _save_notes(client, job_id, loaded, notes)
        _regen_twice(client, job_id, saved.json()["revision"])
        edited = client.get(f"/scores/{job_id}/edits").json()
        assert int(_note(edited, sid)["track"]) == 1
        assert int(_note(edited, sid)["voice"]) == uncorrected_voice + 1
        reverted = [dict(row) for row in edited["notes"]]
        row = next(item for item in reverted if (item.get("source_note_id") or item["id"]) == sid)
        row["track"] = uncorrected_track
        row["voice"] = uncorrected_voice
        saved_revert = _save_notes(client, job_id, edited, reverted)
        assert saved_revert.status_code == 200, saved_revert.text
        restored = _note(saved_revert.json(), sid)
        assert int(restored["track"]) == uncorrected_track
        assert int(restored["voice"]) == uncorrected_voice
        assert int(_note(saved_revert.json(), other_sid)["pitch"]) == other_pitch + 1
        _, key = _pointer(job_id)
        remaining = [op for op in _ops(key, job_id) if op.get("source_note_id") == sid]
        assert remaining == []
        assert any(op.get("pitch") == other_pitch + 1 for op in _ops(key, job_id))
        assert saved_revert.json()["has_edits"] is True
        _assert_artifacts_agree(
            client, job_id, saved_revert.json(), sid=sid, track=uncorrected_track
        )


def test_http_timing_velocity_add_delete_survive_grid_readability_and_reset(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"time-{uuid.uuid4().hex[:12]}"
    _xml_path, original = _prepare_hands_job(isolated_db, job_id)
    with _client() as client:
        client.post(f"/jobs/{job_id}/notation-settings", json={"interpretation": "literal", "revision": 0})
        loaded = client.get(f"/scores/{job_id}/edits").json()
        notes = [dict(row) for row in loaded["notes"]]
        timed = notes[0]
        timed_sid = timed.get("source_note_id") or timed["id"]
        vel = next(row for row in notes if (row.get("source_note_id") or row["id"]) != timed_sid)
        vel_sid = vel.get("source_note_id") or vel["id"]
        uncorrected_start = float(timed["start"])
        uncorrected_duration = float(timed["duration"])
        uncorrected_velocity = int(vel["velocity"])
        original_ids = {row.get("source_note_id") or row["id"] for row in notes}
        deleted = notes[-1]
        deleted_sid = deleted.get("source_note_id") or deleted["id"]
        timed["start"] = uncorrected_start + 1.0
        timed["duration"] = max(0.5, uncorrected_duration * 2)
        vel["velocity"] = min(127, uncorrected_velocity + 17)
        kept = [row for row in notes if (row.get("source_note_id") or row["id"]) != deleted_sid]
        kept.append(
            {
                "id": "n-a0",
                "source_note_id": None,
                "pitch": 69,
                "start": 3.0,
                "duration": 1.0,
                "velocity": 88,
                "track": 0,
                "voice": 0,
            }
        )
        saved = _save_notes(client, job_id, loaded, kept)
        assert saved.status_code == 200, saved.text
        assert saved.json()["has_edits"] is True
        _, key1 = _pointer(job_id)
        ops1 = _ops(key1, job_id)
        assert any(op.get("source_note_id") == timed_sid and "start" in op for op in ops1)
        assert any(
            op.get("source_note_id") == vel_sid and op.get("velocity") == min(127, uncorrected_velocity + 17)
            for op in ops1
        )
        assert any(op.get("exclude") and op.get("source_note_id") == deleted_sid for op in ops1)
        assert any(op.get("insert") and op.get("id") == "n-a0" for op in ops1)
        reloaded = client.get(f"/scores/{job_id}/edits").json()
        assert float(_note(reloaded, timed_sid)["start"]) == pytest.approx(uncorrected_start + 1.0)
        assert int(_note(reloaded, vel_sid)["velocity"]) == min(127, uncorrected_velocity + 17)
        assert all((row.get("source_note_id") or row["id"]) != deleted_sid for row in reloaded["notes"])
        assert any(row["id"] == "n-a0" and int(row["pitch"]) == 69 for row in reloaded["notes"])
        grid = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"display_grid": "sixteenth", "revision": reloaded["revision"]},
        )
        assert grid.status_code == 200, grid.text
        readable = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={
                "interpretation": "readable",
                "algorithm_version": "performance-score-1",
                "revision": grid.json()["edit_revision"],
            },
        )
        assert readable.status_code == 200, readable.text
        after = client.get(f"/scores/{job_id}/edits").json()
        assert float(_note(after, timed_sid)["start"]) == pytest.approx(uncorrected_start + 1.0, abs=1e-3)
        assert float(_note(after, timed_sid)["duration"]) == pytest.approx(
            max(0.5, uncorrected_duration * 2), abs=1e-3
        )
        assert int(_note(after, vel_sid)["velocity"]) == min(127, uncorrected_velocity + 17)
        assert all((row.get("source_note_id") or row["id"]) != deleted_sid for row in after["notes"])
        inserted = next(row for row in after["notes"] if row["id"] == "n-a0")
        assert int(inserted["pitch"]) == 69
        _assert_artifacts_agree(
            client,
            job_id,
            after,
            sid=timed_sid,
            start=uncorrected_start + 1.0,
            duration=max(0.5, uncorrected_duration * 2),
        )
        _assert_artifacts_agree(
            client,
            job_id,
            after,
            sid=vel_sid,
            velocity=min(127, uncorrected_velocity + 17),
        )
        reloaded_again = client.get(f"/scores/{job_id}/edits").json()
        reset = client.post(
            f"/scores/{job_id}/edits/reset",
            json={"revision": reloaded_again["revision"]},
        )
        assert reset.status_code == 200, reset.text
        restored_ids = {row.get("source_note_id") or row["id"] for row in reset.json()["notes"]}
        assert deleted_sid in restored_ids
        assert "n-a0" not in {row["id"] for row in reset.json()["notes"]}
        assert float(_note(reset.json(), timed_sid)["start"]) == pytest.approx(uncorrected_start, abs=0.26)
        assert int(_note(reset.json(), vel_sid)["velocity"]) == uncorrected_velocity
        assert reset.json()["has_edits"] is False
        listed = client.get(f"/jobs/{job_id}/notation-settings")
        assert listed.json()["notation_settings"]["display_grid"] == "sixteenth"
        assert listed.json()["notation_settings"]["interpretation"] == "readable"
        assert (isolated_db / f"{job_id}.raw.mid").read_bytes() == original
        raw = client.get(f"/jobs/{job_id}/result?format=midi")
        assert raw.status_code == 200
        assert raw.content == original
        assert original_ids <= restored_ids


def test_http_articulation_round_trip_velocity_regen_and_reset(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    job_id = f"marks-{uuid.uuid4().hex[:12]}"
    xml_path, original = _prepare_http_job(isolated_db, job_id)
    with _client() as client:
        posted = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "readable", "revision": 0},
        )
        assert posted.status_code == 200, posted.text
        loaded = client.get(f"/scores/{job_id}/edits")
        assert loaded.status_code == 200
        body = loaded.json()
        notes = [dict(row) for row in body["notes"]]
        target = notes[0]
        sid = target.get("source_note_id") or target["id"]
        settings_before = client.get(f"/jobs/{job_id}/notation-settings").json()["notation_settings"]
        target["articulation"] = "staccato"
        saved = _save_notes(client, job_id, body, notes)
        assert saved.status_code == 200, saved.text
        assert _note(saved.json(), sid).get("articulation") == "staccato"
        _, key1 = _pointer(job_id)
        assert any(op.get("articulation") == "staccato" and op["source_note_id"] == sid for op in _ops(key1, job_id))

        loaded2 = saved.json()
        notes2 = [dict(row) for row in loaded2["notes"]]
        other = next(row for row in notes2 if (row.get("source_note_id") or row["id"]) != sid)
        other_sid = other.get("source_note_id") or other["id"]
        other["velocity"] = 110
        saved2 = _save_notes(client, job_id, loaded2, notes2)
        assert saved2.status_code == 200, saved2.text
        assert _note(saved2.json(), sid).get("articulation") == "staccato"
        assert int(_note(saved2.json(), other_sid)["velocity"]) == 110

        reloaded = client.get(f"/scores/{job_id}/edits")
        assert reloaded.status_code == 200
        assert _note(reloaded.json(), sid).get("articulation") == "staccato"

        regen = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"display_grid": "sixteenth", "revision": saved2.json()["revision"]},
        )
        assert regen.status_code == 200, regen.text
        after_regen = client.get(f"/scores/{job_id}/edits")
        assert after_regen.status_code == 200
        assert _note(after_regen.json(), sid).get("articulation") == "staccato"
        listed = client.get(f"/jobs/{job_id}/notation-settings")
        assert listed.json()["notation_settings"]["display_grid"] == "sixteenth"
        assert listed.json()["notation_settings"]["interpretation"] == "readable"

        reset = client.post(
            f"/scores/{job_id}/edits/reset",
            json={"revision": after_regen.json()["revision"]},
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["has_edits"] is False
        assert not _note(reset.json(), sid).get("articulation")
        listed_reset = client.get(f"/jobs/{job_id}/notation-settings")
        assert listed_reset.json()["notation_settings"]["display_grid"] == "sixteenth"
        assert listed_reset.json()["notation_settings"]["interpretation"] == settings_before["interpretation"]
        assert (isolated_db / f"{job_id}.raw.mid").read_bytes() == original
        raw = client.get(f"/jobs/{job_id}/result?format=midi")
        assert raw.status_code == 200
        assert raw.content == original
