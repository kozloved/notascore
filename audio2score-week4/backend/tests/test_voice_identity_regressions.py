"""Voice-identity regressions reuse the rollout comparator and regen path."""

from __future__ import annotations

from evaluation.notation_fixtures import FIXTURE_META, FIXTURES
from evaluation.readable_v2_cases import READABLE_V2_CASES
from evaluation.readable_v2_rollout import (
    _assignments,
    compare_case,
    compare_staff_voice,
)
from mir.midi_ingest import ingest_midi
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings
from tests.test_shared_engraving import _context_for


def test_velocity_edit_preserves_musical_identity(tmp_path):
    path = tmp_path / "held.mid"
    READABLE_V2_CASES["G_held_voice_same_staff"](path)
    original = path.read_bytes()
    ingested = ingest_midi(path)
    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    sid = auto.editor_model["notes"][0].get("source_note_id") or auto.editor_model["notes"][0]["id"]
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": sid, "velocity": 108}],
    )
    assert path.read_bytes() == original
    compared = compare_staff_voice(_assignments(auto), _assignments(edited))
    assert compared["kind"] == "unchanged"
    assert compared["assignments_unchanged"] is True
    assert compared["musical_grouping_equal"] is True
    assert compared["printed_grouping_equal"] is True
    auto_vel = next(
        row for row in auto.editor_model["notes"] if (row.get("source_note_id") or row["id"]) == sid
    )
    edited_vel = next(
        row
        for row in edited.editor_model["notes"]
        if (row.get("source_note_id") or row["id"]) == sid
    )
    assert int(auto_vel["velocity"]) != 108
    assert int(edited_vel["velocity"]) == 108


def test_readable_v2_duration_changes_preserve_independent_held_voices(tmp_path):
    row = compare_case(
        "G_held_voice_same_staff",
        READABLE_V2_CASES,
        {"meter": "4/4", "tempo": 120},
        "synthetic_fixture",
        True,
        tmp_path,
    )
    assert row["source_midi_unchanged"] is True
    assert row["hand_voice"]["assignments_unchanged"] is True
    assert row["hand_voice"]["kind"] in {"unchanged", "printed_lane_adjustment"}
    hold_v1 = next(note for note in row["v1"]["assignments"]["notes"] if note["pitch"] == 67)
    hold_v2 = next(note for note in row["v2"]["assignments"]["notes"] if note["pitch"] == 67)
    assert hold_v1["id"] == hold_v2["id"]
    assert hold_v1["musical_voice"] == hold_v2["musical_voice"]
    assert hold_v2["duration"] + 1e-6 >= hold_v1["duration"]
    assert hold_v2["duration"] >= 1.9

    triplets = compare_case(
        "L_held_voice_under_triplets",
        READABLE_V2_CASES,
        {"meter": "4/4", "tempo": 120},
        "readable_v2",
        False,
        tmp_path,
    )
    bass_v1 = next(note for note in triplets["v1"]["assignments"]["notes"] if note["pitch"] == 48)
    bass_v2 = next(note for note in triplets["v2"]["assignments"]["notes"] if note["pitch"] == 48)
    assert triplets["hand_voice"]["assignments_unchanged"] is True
    assert bass_v1["musical_voice"] == bass_v2["musical_voice"]
    assert bass_v2["duration"] + 1e-6 >= bass_v1["duration"]


def test_user_locked_staff_and_voice_survive_unrelated_edit(tmp_path):
    path = tmp_path / "crossing.mid"
    FIXTURES["unison_crossing"](path)
    original = path.read_bytes()
    ingested = ingest_midi(path)
    context = _context_for(ingested, selected_meter=FIXTURE_META["unison_crossing"]["meter"])
    auto = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    treble = next(note for note in auto.editor_model["notes"] if int(note["track"]) == 0)
    sid = treble.get("source_note_id") or treble["id"]
    locked_voice = int(treble.get("voice") or 0) + 1
    locked = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
        corrections=[{"source_note_id": sid, "track": 1, "voice": locked_voice}],
    )
    louder = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
        corrections=[
            {"source_note_id": sid, "track": 1, "voice": locked_voice, "velocity": 111}
        ],
    )
    assert path.read_bytes() == original
    locked_row = next(
        note
        for note in locked.editor_model["notes"]
        if (note.get("source_note_id") or note["id"]) == sid
    )
    louder_row = next(
        note
        for note in louder.editor_model["notes"]
        if (note.get("source_note_id") or note["id"]) == sid
    )
    assert int(locked_row["track"]) == 1
    assert int(locked_row["voice"]) == locked_voice
    assert int(louder_row["track"]) == 1
    assert int(louder_row["voice"]) == locked_voice
    assert int(louder_row["velocity"]) == 111
    locked_dec = next(row for row in locked.decisions if row.get("note_id") == sid)
    louder_dec = next(row for row in louder.decisions if row.get("note_id") == sid)
    assert locked_dec.get("voice_provenance") == "user_edit"
    assert louder_dec.get("voice_provenance") == "user_edit"
    assert locked_dec.get("musical_voice") == locked_voice
    assert louder_dec.get("musical_voice") == locked_voice
    compared = compare_staff_voice(_assignments(locked), _assignments(louder))
    assert compared["kind"] == "unchanged"
    assert compared["assignments_unchanged"] is True
