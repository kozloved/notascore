"""Correctness gates for selection, edits, identity, and production equivalence."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pretty_midi
import pytest
from fastapi import HTTPException

from mir.interpretation_context import InterpretationContext, InterpretationContextError
from mir.midi_ingest import ingest_midi
from mir.notation_regen import (
    NotationEditConflict,
    apply_note_edits,
    recompute_notation,
)
from mir.notation_settings import NotationSettings
from mir.performance import PerformanceSnapshot
from timing.tempo_map import MusicalTimeMap

from tests.test_notation_revision_safety import (
    _fail_if_transcribe,
    _job_row,
    _midi_bytes,
    _musical_inventory,
    isolated_db,
)


def _g_major_midi(path: Path, *, tempo=90.0):
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    midi.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0.0))
    midi.key_signature_changes.append(pretty_midi.KeySignature(key_number=7, time=0.0))
    piano = pretty_midi.Instrument(program=0, name="Piano")
    beat = 60.0 / tempo
    pitches = [67, 71, 74, 79, 67, 71, 74, 78, 79, 74]
    for i, pitch in enumerate(pitches):
        start = i * beat
        piano.notes.append(
            pretty_midi.Note(velocity=82, pitch=pitch, start=start, end=start + beat * 0.85)
        )
    bass = [43, 50, 47, 43]
    for i, pitch in enumerate(bass):
        start = i * beat * 2
        piano.notes.append(
            pretty_midi.Note(velocity=68, pitch=pitch, start=start, end=start + beat * 1.8)
        )
    piano.control_changes.append(pretty_midi.ControlChange(number=64, value=100, time=0.0))
    piano.control_changes.append(pretty_midi.ControlChange(number=64, value=0, time=beat * 6))
    midi.instruments.append(piano)
    path.write_bytes(b"")
    midi.write(str(path))
    return path.read_bytes()


def _semantics(decisions):
    return [
        (
            row.get("note_id"),
            round(float(row["quantized_start"]), 4),
            round(float(row.get("written_duration", row.get("quantized_duration", 0))), 4),
            row.get("hand"),
            int(row.get("printed_voice", row.get("voice") or 0)),
        )
        for row in decisions
    ]


def _context_for(notes, **overrides):
    ids = [n.note_id for n in notes]
    payload = dict(
        time_map=MusicalTimeMap.from_bpm(90.0, duration_sec=8.0),
        selected_meter="4/4",
        key_name="G",
        display_bpm=90.0,
        accepted_source_note_ids=tuple(ids),
        has_recorded_selection=True,
        midi_sha256=None,
        source_backend="midi",
    )
    payload.update(overrides)
    return InterpretationContext(**payload)


def test_partial_unknown_and_fully_unresolved_selection_fail(tmp_path, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    midi_bytes = _midi_bytes([(60, 0.0, 0.5), (64, 0.5, 1.0), (67, 1.0, 1.5)], tempo=90)
    ingested = ingest_midi(_write_bytes(tmp_path / "sel.mid", midi_bytes))
    notes = ingested.notes
    known = notes[0].note_id
    context = _context_for(
        notes,
        midi_sha256=ingested.performance.midi_sha256,
        accepted_source_note_ids=(known, "missing-note"),
    )
    with pytest.raises(InterpretationContextError, match="unknown accepted"):
        recompute_notation(
            midi_bytes=midi_bytes,
            settings=NotationSettings(),
            performance=ingested.performance,
            context=context,
        )
    empty = _context_for(
        notes,
        midi_sha256=ingested.performance.midi_sha256,
        accepted_source_note_ids=("ghost-a", "ghost-b"),
    )
    with pytest.raises(InterpretationContextError, match="unknown accepted"):
        recompute_notation(
            midi_bytes=midi_bytes,
            settings=NotationSettings(),
            performance=ingested.performance,
            context=empty,
        )
    recorded_empty = _context_for(
        notes,
        midi_sha256=ingested.performance.midi_sha256,
        accepted_source_note_ids=(),
        excluded_source_note_ids=(),
        has_recorded_selection=True,
    )
    with pytest.raises(InterpretationContextError, match="empty note selection"):
        recompute_notation(
            midi_bytes=midi_bytes,
            settings=NotationSettings(),
            performance=ingested.performance,
            context=recorded_empty,
        )
    legacy = _context_for(
        notes,
        midi_sha256=ingested.performance.midi_sha256,
        accepted_source_note_ids=(),
        has_recorded_selection=False,
    )
    kept = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=legacy,
    )
    assert kept.source_note_count == 3
    excluded = _context_for(
        notes,
        midi_sha256=ingested.performance.midi_sha256,
        accepted_source_note_ids=(known,),
        excluded_source_note_ids=(known,),
    )
    with pytest.raises(InterpretationContextError, match="both kept and excluded"):
        recompute_notation(
            midi_bytes=midi_bytes,
            settings=NotationSettings(),
            performance=ingested.performance,
            context=excluded,
        )


def _write_bytes(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_unknown_correction_ids_are_rejected(tmp_path, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    midi_bytes = _midi_bytes([(60, 0.0, 0.5)], tempo=90)
    ingested = ingest_midi(_write_bytes(tmp_path / "edit.mid", midi_bytes))
    context = _context_for(ingested.notes, midi_sha256=ingested.performance.midi_sha256)
    with pytest.raises(NotationEditConflict):
        recompute_notation(
            midi_bytes=midi_bytes,
            settings=NotationSettings(),
            performance=ingested.performance,
            context=context,
            corrections=[{"source_note_id": "no-such-note", "pitch": 62}],
        )
    events = ingested.performance.to_notes()
    from mir.cmr_builder import notes_to_events

    mapped = notes_to_events(list(events), context.time_map, source_backend="midi")
    with pytest.raises(NotationEditConflict):
        apply_note_edits(
            mapped,
            [{"source_note_id": "ghost", "pitch": 61}],
            ingested.performance,
        )


def _prepare_http_job(tmp_path, job_id: str):
    import database as db
    from mir.performance_cli import convert

    source = tmp_path / f"{job_id}.mid"
    source.write_bytes(_midi_bytes([(60, 0.0, 0.4), (64, 0.5, 0.9), (67, 1.0, 1.4)], tempo=90))
    original = source.read_bytes()
    xml_path = tmp_path / f"{job_id}.musicxml"
    convert(source, xml_path)
    (tmp_path / f"{job_id}.raw.mid").write_bytes(original)
    db.create_job(_job_row(job_id, result_storage_key=str(xml_path), edit_revision=0))
    return xml_path, original


def _pointer(job_id: str):
    import database as db

    job = db.get_job(job_id)
    return job["edit_revision"], job.get("edited_result_storage_key")


def test_malformed_and_missing_correction_sidecars_leave_pointer(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    import main as app_main

    job_id = f"side-{uuid.uuid4().hex[:12]}"
    xml_path, original = _prepare_http_job(isolated_db, job_id)
    canonical = xml_path.read_text(encoding="utf-8")
    posted = app_main.job_notation_settings_post(
        job_id,
        app_main.NotationSettingsIn(interpretation="literal", revision=0),
        authorization=None,
    )
    assert posted["has_edits"] is False
    rev, key = _pointer(job_id)
    assert rev == 1 and key
    bundle = Path(key).parent
    (bundle / f"{job_id}.corrections.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        app_main.job_notation_settings_post(
            job_id,
            app_main.NotationSettingsIn(display_grid="sixteenth", revision=1),
            authorization=None,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "edit_conflict"
    assert _pointer(job_id) == (rev, key)
    assert Path(xml_path).read_text(encoding="utf-8")
    (bundle / f"{job_id}.corrections.json").unlink()
    with pytest.raises(HTTPException) as exc:
        app_main.job_notation_settings_post(
            job_id,
            app_main.NotationSettingsIn(display_grid="eighth", revision=1),
            authorization=None,
        )
    assert exc.value.status_code == 409
    assert "missing" in exc.value.detail["message"].lower()
    assert _pointer(job_id) == (rev, key)
    (bundle / f"{job_id}.corrections.json").write_text(
        json.dumps({"operations": ["invalid", {"pitch": 70}]}),
        encoding="utf-8",
    )
    stored_corrections = (bundle / f"{job_id}.corrections.json").read_text(encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        app_main.job_notation_settings_post(
            job_id,
            app_main.NotationSettingsIn(interpretation="literal", revision=1),
            authorization=None,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "edit_conflict"
    assert _pointer(job_id) == (rev, key)
    assert (bundle / f"{job_id}.corrections.json").read_text(encoding="utf-8") == stored_corrections
    (bundle / f"{job_id}.corrections.json").write_text(
        json.dumps({"operations": [{"source_note_id": "ghost", "pitch": 80}]}),
        encoding="utf-8",
    )
    with pytest.raises(HTTPException) as exc:
        app_main.job_notation_settings_post(
            job_id,
            app_main.NotationSettingsIn(interpretation="literal", revision=1),
            authorization=None,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] in {"edit_conflict", "invalid_selection"}
    assert _pointer(job_id) == (rev, key)
    assert (isolated_db / f"{job_id}.raw.mid").read_bytes() == original
    assert xml_path.read_text(encoding="utf-8") == canonical


def test_identity_digest_covers_layout_pedal_playback_and_round_trip():
    time_map = MusicalTimeMap.from_bpm(90.0, duration_sec=4.0)
    base = InterpretationContext(
        time_map=time_map,
        selected_meter="4/4",
        key_name="G",
        display_bpm=90.0,
        playback_tempo=({"beat": 0.0, "bpm": 90.0},),
        pedal_events=((0.0, 100), (2.0, 0)),
        layout_decisions=({"note_id": "n0", "hand": "right", "quantized_start": 0.75},),
        source_backend="midi",
        has_recorded_selection=True,
        accepted_source_note_ids=("n0",),
    )
    same = InterpretationContext.from_dict(json.loads(json.dumps(base.to_dict(), sort_keys=True)))
    assert same.identity_digest() == base.identity_digest()
    assert same.to_dict()["identity_digest"] == same.identity_digest()
    layout = InterpretationContext.from_dict(
        {**base.to_dict(), "layout_decisions": [{"note_id": "n0", "hand": "left"}]}
    )
    pedal = InterpretationContext.from_dict(
        {**base.to_dict(), "pedal_events": [[0.0, 64], [2.0, 0]]}
    )
    tempo = InterpretationContext.from_dict(
        {**base.to_dict(), "playback_tempo": [{"beat": 0.0, "bpm": 72.0}]}
    )
    assert layout.identity_digest() != base.identity_digest()
    assert pedal.identity_digest() != base.identity_digest()
    assert tempo.identity_digest() != base.identity_digest()


def test_production_noop_regen_matches_exported_score(tmp_path, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    from mir.pipeline import UnderstandingPipeline

    job_id = "prod-eq"
    source = tmp_path / f"{job_id}.mid"
    _g_major_midi(source, tempo=90.0)
    pipe = UnderstandingPipeline(backend_name="midi")
    pipe.notation_settings = NotationSettings.from_dict(
        {"pickup_beats": 1.0, "meter": "4/4"}
    )
    xml = pipe.transcribe_midi(source, job_id)
    out = tmp_path / f"bp_{job_id}"
    context_path = out / f"{job_id}.interpretation_context.json"
    assert context_path.is_file()
    context = InterpretationContext.read_json(context_path)
    assert context.key_name.lower().startswith("g")
    assert context.display_bpm == pytest.approx(90.0, abs=0.6)
    assert context.pickup_beats == pytest.approx(1.0)
    assert context.pedal_events
    assert context.instrument == "piano"
    assert context.time_map_includes_score_offset is False
    raw = (out / f"{job_id}.raw.mid").read_bytes()
    snap = PerformanceSnapshot.read_json(out / f"{job_id}.performance.json")
    settings_path = out / f"{job_id}.notation_settings.json"
    stored_digest = json.loads(settings_path.read_text())["interpretation_context_digest"]
    assert stored_digest == context.identity_digest()
    first = recompute_notation(
        midi_bytes=raw,
        settings=NotationSettings(),
        performance=snap,
        context=context,
    )
    second = recompute_notation(
        midi_bytes=raw,
        settings=NotationSettings(),
        performance=snap,
        context=first.context,
    )
    prod_notes, prod_meters, prod_keys, _tempi = _musical_inventory(xml)
    regen_notes, regen_meters, regen_keys, _ = _musical_inventory(first.musicxml)
    again_notes, again_meters, again_keys, _ = _musical_inventory(second.musicxml)
    assert prod_notes == regen_notes == again_notes
    assert prod_meters[0] == regen_meters[0] == again_meters[0] == "4/4"
    assert any("G" in key or "g" in key.lower() for key in prod_keys + regen_keys)
    assert prod_keys == regen_keys == again_keys
    assert _semantics(first.decisions) == _semantics(second.decisions)
    starts = [row[1] for row in _semantics(first.decisions)]
    assert min(starts) >= 2.9
    assert first.context.score_beat_offset == pytest.approx(
        context.score_beat_offset or 3.0, abs=0.05
    )
    assert first.transcribed is False and first.fallback is None
    assert first.context.identity_digest() == first.context.to_dict()["identity_digest"]


def test_correction_reset_sequence_keeps_one_published_revision(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    import database as db
    import main as app_main
    from score_edits import loads_edits

    job_id = f"seq-{uuid.uuid4().hex[:12]}"
    _prepare_http_job(isolated_db, job_id)
    first = app_main.job_notation_settings_post(
        job_id,
        app_main.NotationSettingsIn(interpretation="literal", revision=0),
        authorization=None,
    )
    assert first["has_edits"] is False
    rev1, key1 = _pointer(job_id)
    assert rev1 == 1 and key1
    job = db.get_job(job_id)
    model = app_main._load_edit_model(job)
    settings = json.loads(Path(key1).with_name(f"{job_id}.notation_settings.json").read_text())
    assert settings["interpretation_context_digest"]
    context = json.loads(
        Path(key1).with_name(f"{job_id}.interpretation_context.json").read_text()
    )
    assert context["identity_digest"] == settings["interpretation_context_digest"]
    corrections = json.loads(Path(key1).with_name(f"{job_id}.corrections.json").read_text())
    assert corrections.get("operations") == []
    notes = [dict(row) for row in model["notes"]]
    target = next(row for row in notes if row.get("source_note_id") or row.get("id"))
    original_pitch = int(target["pitch"])
    target["pitch"] = original_pitch + 2
    if target.get("track") == 0:
        target["track"] = 1
    else:
        target["track"] = 0
    saved = app_main.score_edits_put(
        job_id,
        app_main.ScoreEditsIn(
            revision=1,
            notes=notes,
            tempo_bpm=model["tempo_bpm"],
            time_signature=model["time_signature"],
            tempo_curve=model.get("tempo_curve"),
        ),
        authorization=None,
    )
    assert saved["has_edits"] is True
    rev2, key2 = _pointer(job_id)
    assert rev2 == saved["revision"] == 2
    second = app_main.job_notation_settings_post(
        job_id,
        app_main.NotationSettingsIn(display_grid="sixteenth", revision=2),
        authorization=None,
    )
    assert second["has_edits"] is True
    rev3, key3 = _pointer(job_id)
    edited = loads_edits(Path(key3).with_name(f"{job_id}.edits.json").read_text())
    kept = next(
        row
        for row in edited["notes"]
        if row.get("source_note_id") == target.get("source_note_id") or row["id"] == target["id"]
    )
    assert int(kept["pitch"]) == original_pitch + 2
    reset_interp = app_main.job_notation_settings_post(
        job_id,
        app_main.NotationSettingsIn(reset=True, revision=3),
        authorization=None,
    )
    assert reset_interp["has_edits"] is True
    rev4, key4 = _pointer(job_id)
    after_reset = loads_edits(Path(key4).with_name(f"{job_id}.edits.json").read_text())
    kept_after = next(
        row
        for row in after_reset["notes"]
        if row.get("source_note_id") == target.get("source_note_id") or row["id"] == target["id"]
    )
    assert int(kept_after["pitch"]) == original_pitch + 2
    settings_after = json.loads(
        Path(key4).with_name(f"{job_id}.notation_settings.json").read_text()
    )
    assert settings_after["notation_settings"]["interpretation"] != "not-a-mode"
    reset_notes = app_main.score_edits_reset(
        job_id,
        app_main.ScoreResetIn(revision=4),
        authorization=None,
    )
    assert reset_notes["has_edits"] is False
    rev5, key5 = _pointer(job_id)
    assert rev5 == reset_notes["revision"]
    still = json.loads(Path(key5).with_name(f"{job_id}.notation_settings.json").read_text())
    assert still["notation_settings"]["display_grid"] == settings_after["notation_settings"]["display_grid"]
    assert still["notation_settings"]["interpretation"] == settings_after["notation_settings"]["interpretation"]
    cleared = json.loads(Path(key5).with_name(f"{job_id}.corrections.json").read_text())
    assert cleared.get("operations") == []
    listed = app_main.job_notation_settings_get(job_id, authorization=None)
    assert listed["has_edits"] is False
    xml_now = Path(key5).read_text(encoding="utf-8")
    assert "score-partwise" in xml_now.lower()
    assert [rev1, rev2, rev3, rev4, rev5] == [1, 2, 3, 4, 5]
    assert len({key1, key2, key3, key4, key5}) == 5


def test_repeated_identical_settings_do_not_drift(tmp_path, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    midi_bytes = _midi_bytes(
        [(67, 0.0, 0.4), (71, 0.5, 0.9), (74, 1.0, 1.4), (79, 1.5, 1.9)],
        tempo=90,
    )
    ingested = ingest_midi(_write_bytes(tmp_path / "drift.mid", midi_bytes))
    context = _context_for(
        ingested.notes,
        midi_sha256=ingested.performance.midi_sha256,
        display_bpm=90.0,
        playback_tempo=({"beat": 0.0, "bpm": 90.0},),
        pedal_events=((0.0, 80), (2.0, 0)),
    )
    settings = NotationSettings.from_dict({"interpretation": "literal"})
    first = recompute_notation(
        midi_bytes=midi_bytes,
        settings=settings,
        performance=ingested.performance,
        context=context,
    )
    second = recompute_notation(
        midi_bytes=midi_bytes,
        settings=settings,
        performance=ingested.performance,
        context=first.context,
    )
    third = recompute_notation(
        midi_bytes=midi_bytes,
        settings=settings,
        performance=ingested.performance,
        context=second.context,
    )
    assert _semantics(first.decisions) == _semantics(second.decisions) == _semantics(third.decisions)
    a, *_ = _musical_inventory(first.musicxml)
    b, *_ = _musical_inventory(second.musicxml)
    c, *_ = _musical_inventory(third.musicxml)
    assert a == b == c
