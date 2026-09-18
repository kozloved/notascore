"""Correction merge semantics, sidecar validation, and uncorrected baselines."""

from __future__ import annotations

import json

import pytest

from mir.notation_regen import (
    NotationEditConflict,
    extract_corrections,
    normalize_corrections,
    parse_corrections_sidecar,
)
from mir.performance import PerformanceSnapshot, SourceNote


def _snapshot(notes):
    rows = tuple(
        SourceNote(
            note_id=note_id,
            pitch=pitch,
            start_sec=0.0,
            end_sec=0.4,
            velocity=80,
            confidence=1.0,
            instrument="piano",
            hand_hint=hint,
        )
        for note_id, pitch, hint in notes
    )
    return PerformanceSnapshot("midi", rows, midi_sha256="abc")


def _model(rows):
    notes = []
    for item in rows:
        notes.append(
            {
                "id": item[0],
                "source_note_id": item[0],
                "pitch": item[1],
                "track": item[2],
                "voice": item[3],
                "start": 0.0,
                "duration": 1.0,
                "velocity": 80,
            }
        )
    return {"notes": notes, "tempo_bpm": 90, "time_signature": "4/4"}


def _legacy_extract(submitted, *, snapshot, baseline=None):
    """PR #68 extract_corrections: diffs vs hand_hint and the current overlay."""
    original = {n.note_id: n for n in snapshot.notes}
    previous = {}
    for row in (baseline or {}).get("notes") or []:
        sid = str(row.get("source_note_id") or row.get("id") or "")
        if sid:
            previous[sid] = row
    ops = []
    for row in submitted["notes"]:
        sid = str(row.get("source_note_id") or row.get("id") or "")
        orig = original.get(sid)
        op = {"source_note_id": sid}
        if orig is None:
            continue
        if row.get("pitch") is not None and int(row["pitch"]) != int(orig.pitch):
            op["pitch"] = int(row["pitch"])
        expected_track = 1 if str(orig.hand_hint or "") == "left" else 0
        if row.get("track") is not None and int(row["track"]) != expected_track:
            op["track"] = int(row["track"])
        prev = previous.get(sid)
        if (
            row.get("voice") is not None
            and prev is not None
            and int(row["voice"]) != int(prev.get("voice") or 0)
        ):
            op["voice"] = int(row["voice"])
        if len(op) > 1:
            ops.append(op)
    return ops


def test_noop_inferred_left_hand_is_not_a_user_correction():
    snapshot = _snapshot([("n-lh", 48, "unknown"), ("n-rh", 72, "unknown")])
    displayed = _model([("n-lh", 48, 1, 0), ("n-rh", 72, 0, 0)])
    buggy = _legacy_extract(displayed, snapshot=snapshot, baseline=displayed)
    assert buggy == [{"source_note_id": "n-lh", "track": 1}]
    ops = extract_corrections(
        displayed,
        snapshot=snapshot,
        displayed=displayed,
        uncorrected={"n-lh": {"pitch": 48, "track": 1, "voice": 0}, "n-rh": {"pitch": 72, "track": 0, "voice": 0}},
        existing=[],
    )
    assert ops == []


def test_voice_correction_survives_later_pitch_save():
    snapshot = _snapshot([("n1", 60, "unknown")])
    uncorrected = {"n1": {"pitch": 60, "track": 0, "voice": 0}}
    after_voice = _model([("n1", 60, 0, 2)])
    voice_ops = extract_corrections(
        after_voice,
        snapshot=snapshot,
        displayed=_model([("n1", 60, 0, 0)]),
        uncorrected=uncorrected,
        existing=[],
    )
    assert voice_ops == [{"source_note_id": "n1", "voice": 2}]
    pitched = _model([("n1", 62, 0, 2)])
    buggy = _legacy_extract(pitched, snapshot=snapshot, baseline=after_voice)
    assert buggy == [{"source_note_id": "n1", "pitch": 62}]
    merged = extract_corrections(
        pitched,
        snapshot=snapshot,
        displayed=after_voice,
        uncorrected=uncorrected,
        existing=voice_ops,
    )
    assert len(merged) == 1
    assert merged[0]["source_note_id"] == "n1"
    assert merged[0]["pitch"] == 62
    assert merged[0]["voice"] == 2


def test_staff_correction_survives_repeated_saves():
    snapshot = _snapshot([("n1", 67, "unknown")])
    uncorrected = {"n1": {"pitch": 67, "track": 0, "voice": 0}}
    moved = _model([("n1", 67, 1, 0)])
    first = extract_corrections(
        moved,
        snapshot=snapshot,
        displayed=_model([("n1", 67, 0, 0)]),
        uncorrected=uncorrected,
        existing=[],
    )
    assert first == [{"source_note_id": "n1", "track": 1}]
    again = extract_corrections(
        moved,
        snapshot=snapshot,
        displayed=moved,
        uncorrected=uncorrected,
        existing=first,
    )
    assert again == [{"source_note_id": "n1", "track": 1}]


def test_reverting_pitch_staff_voice_removes_only_that_field():
    snapshot = _snapshot([("n1", 60, "unknown")])
    uncorrected = {"n1": {"pitch": 60, "track": 0, "voice": 1}}
    displayed = _model([("n1", 64, 1, 2)])
    existing = [{"source_note_id": "n1", "pitch": 64, "track": 1, "voice": 2}]
    restored_pitch = extract_corrections(
        _model([("n1", 60, 1, 2)]),
        snapshot=snapshot,
        displayed=displayed,
        uncorrected=uncorrected,
        existing=existing,
    )
    assert restored_pitch == [{"source_note_id": "n1", "track": 1, "voice": 2}]
    restored_staff = extract_corrections(
        _model([("n1", 64, 0, 2)]),
        snapshot=snapshot,
        displayed=displayed,
        uncorrected=uncorrected,
        existing=existing,
    )
    assert restored_staff == [{"source_note_id": "n1", "pitch": 64, "voice": 2}]
    restored_voice = extract_corrections(
        _model([("n1", 64, 1, 1)]),
        snapshot=snapshot,
        displayed=displayed,
        uncorrected=uncorrected,
        existing=existing,
    )
    assert restored_voice == [{"source_note_id": "n1", "pitch": 64, "track": 1}]


def test_malformed_operations_are_not_normalized_to_empty():
    with pytest.raises(NotationEditConflict, match="source note ID|must be an object"):
        normalize_corrections({"operations": ["invalid", {"pitch": 70}]})
    with pytest.raises(NotationEditConflict):
        parse_corrections_sidecar({"operations": ["invalid", {"pitch": 70}]})
    assert normalize_corrections({"operations": []}) == []
    assert parse_corrections_sidecar({"operations": []}) == ([], {})
    with pytest.raises(NotationEditConflict, match="Unsupported"):
        normalize_corrections({"operations": [{"source_note_id": "n1", "pitch": 70, "color": "red"}]})
    with pytest.raises(NotationEditConflict, match="Invalid pitch"):
        normalize_corrections({"operations": [{"source_note_id": "n1", "pitch": 200}]})
    with pytest.raises(NotationEditConflict, match="Duplicate"):
        normalize_corrections(
            {
                "operations": [
                    {"source_note_id": "n1", "pitch": 61},
                    {"source_note_id": "n1", "track": 1},
                ]
            }
        )


def test_generated_editor_model_is_still_rejected():
    with pytest.raises(NotationEditConflict, match="generated editor model"):
        normalize_corrections({"notes": [{"id": "n1", "pitch": 60}]})
