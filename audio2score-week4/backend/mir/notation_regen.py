"""Recompute notation from an existing performance without re-transcribing audio.

Original MIDI bytes and the performance snapshot stay untouched. Only the
derived score artifacts are rewritten. Cache identity includes the MIDI
checksum, algorithm version, notation settings, interpretation context,
and applied edit identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mir.cmr_builder import build_score_meta, notes_to_events
from mir.interpretation_context import (
    FALLBACK_MIDI_INGEST,
    FALLBACK_MISSING,
    InterpretationContext,
    InterpretationContextError,
    load_context_payload,
)
from mir.notation_settings import (
    NotationSettings,
    parse_notation_settings,
    settings_for_reset,
)
from mir.performance import PerformanceSnapshot
from mir.pipeline_config import QuantizationMode
from mir.types import InstrumentKind, MusicalEvent, copy_event
from notation_engine.writer import NotationWriter
from score_edits import MAX_DURATION, MAX_START, PITCH_MAX, PITCH_MIN


def public_policy_exception(row: dict) -> dict:
    """User-facing copy for a required local grid or tuplet exception."""
    payload = dict(row or {})
    kind = str(payload.get("kind") or "")
    if not payload.get("user_message"):
        if kind == "triplet_policy":
            payload["user_message"] = (
                "A local tuplet was needed to keep this attack on the page."
            )
        elif kind in {"display_grid", "grid"}:
            payload["user_message"] = (
                "A finer local grid was needed to keep this attack in place."
            )
        else:
            payload["user_message"] = payload.get("reason") or (
                "A local notation exception was required."
            )
    return payload


class NotationEditConflict(ValueError):
    """A saved correction cannot be reapplied to the regenerated score."""

    def __init__(self, missing_ids: list[str], message: str | None = None):
        self.missing_ids = list(missing_ids)
        super().__init__(
            message
            or (
                "Notation settings were not applied because these edits cannot "
                f"be reattached: {', '.join(self.missing_ids)}."
            )
        )


@dataclass
class NotationRegenResult:
    musicxml: str
    settings: NotationSettings
    cache_key: str
    midi_sha256: str
    source_note_count: int
    transcribed: bool = False
    decisions: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    score_midi: bytes = b""
    context: InterpretationContext | None = None
    fallback: str | None = None
    policy_exceptions: list[dict] = field(default_factory=list)
    editor_model: dict | None = None
    edits_digest: str | None = None
    input_identity: str | None = None
    output_identity: str | None = None
    uncorrected: dict = field(default_factory=dict)
    uncorrected_score: dict = field(default_factory=dict)
    score_overrides: dict = field(default_factory=dict)


# Explicit contract for every field the editor/API accepts. Values are either
# preserved through regeneration as source-ID operations / score overrides, or
# rejected before publish. Performed seconds and raw MIDI are never rewritten.
EDIT_CONTRACT = {
    "pitch": {
        "preserve": True,
        "unit": "midi_note_number",
        "operation": "source_note_id",
        "stage": "layout",
    },
    "track": {
        "preserve": True,
        "unit": "staff",
        "meaning": "0=right/treble, 1=left/bass",
        "operation": "source_note_id",
        "stage": "layout",
    },
    "voice": {
        "preserve": True,
        "unit": "musical_voice",
        "operation": "source_note_id",
        "stage": "layout",
        "notes": "User musical voice; printed lane may still be allocated.",
    },
    "start": {
        "preserve": True,
        "unit": "score_beats",
        "operation": "source_note_id",
        "stage": "score_override",
        "notes": (
            "Quarter-note beats on the written score. Applied after automatic "
            "notation. Performed start_sec is left unchanged."
        ),
    },
    "duration": {
        "preserve": True,
        "unit": "score_beats",
        "operation": "source_note_id",
        "stage": "score_override",
        "notes": (
            "Written duration in quarter-note beats. Applied after automatic "
            "notation. Performed end_sec is left unchanged."
        ),
    },
    "velocity": {
        "preserve": True,
        "unit": "midi_velocity",
        "operation": "source_note_id",
        "stage": "score_override",
        "notes": "Score MIDI velocity only; raw performance MIDI is untouched.",
    },
    "start_sec": {
        "preserve": False,
        "unit": "performed_seconds",
        "reject": True,
        "notes": "Immutable performed onset from the snapshot.",
    },
    "end_sec": {
        "preserve": False,
        "unit": "performed_seconds",
        "reject": True,
        "notes": "Immutable performed release from the snapshot.",
    },
    "exclude": {
        "preserve": True,
        "unit": "note_inventory",
        "operation": "source_note_id",
        "stage": "score_override",
        "notes": "Delete a source note from the written score only.",
    },
    "insert": {
        "preserve": True,
        "unit": "note_inventory",
        "operation": "editor_id",
        "stage": "score_override",
        "notes": "Added notes have no source_note_id and are score-only.",
    },
    "tempo_bpm": {
        "preserve": True,
        "unit": "score_tempo",
        "operation": "score",
        "notes": "Display tempo override; playback/time map stay in context.",
    },
    "time_signature": {
        "preserve": True,
        "unit": "score_meter",
        "operation": "score",
        "notes": (
            "Editor meter override after automatic notation. Notation-settings "
            "meter still drives regeneration when this is not overridden."
        ),
    },
    "tempo_curve": {
        "preserve": True,
        "unit": "score_tempo_curve",
        "operation": "score",
        "notes": "Score-time tempo curve override; raw MIDI tempo is untouched.",
    },
}


def _layout_from_decisions(events, decisions, *, uncorrected=None):
    """Apply uncorrected engine layout only. Skip user-edit provenance rows."""
    from mir.types import Hand, copy_event as _copy

    unc_map = _validate_uncorrected_map(uncorrected) if uncorrected else {}
    by_id = {row.get("note_id"): row for row in decisions or [] if row.get("note_id")}
    if not by_id and not unc_map:
        return events
    out = []
    for ev in events:
        row = by_id.get(ev.note_id)
        unc = unc_map.get(ev.note_id) or {}
        if not row and not unc:
            out.append(ev)
            continue
        provenance = str((row or {}).get("voice_provenance") or "")
        user_layout = provenance == "user_edit"
        if unc.get("track") is not None and (user_layout or not row):
            hand_value = "left" if int(unc["track"]) == 1 else "right"
        elif row and not user_layout:
            hand_value = row.get("hand") or ev.hand.value
        else:
            hand_value = ev.hand.value
        try:
            hand = Hand(hand_value)
        except ValueError:
            hand = ev.hand
        if unc.get("voice") is not None and (user_layout or not row):
            printed = int(unc["voice"])
            musical = int(unc["voice"])
        elif row and not user_layout:
            printed = int(row.get("printed_voice", row.get("voice", ev.voice)) or 0)
            musical = row.get("musical_voice")
            musical = None if musical is None else int(musical)
        else:
            printed = int(ev.voice or 0)
            musical = ev.musical_voice
        voice_prov = ev.voice_provenance or "supplied"
        if row and not user_layout:
            voice_prov = row.get("voice_provenance") or voice_prov
        if voice_prov == "user_edit":
            voice_prov = "inferred"
        out.append(
            _copy(
                ev,
                hand=hand,
                voice=printed,
                musical_voice=musical,
                voice_assigned=True,
                voice_provenance=voice_prov,
            )
        )
    return out


def _uncorrected_layout_decisions(decisions, baseline_events):
    """Writer decisions with uncorrected hand/voice; never user-edit provenance."""
    by_id = {ev.note_id: ev for ev in baseline_events if getattr(ev, "note_id", "")}
    out = []
    for row in decisions or []:
        cleaned = dict(row)
        base = by_id.get(row.get("note_id"))
        if base is not None:
            cleaned["hand"] = base.hand.value
            cleaned["printed_voice"] = int(base.voice or 0)
            cleaned["voice"] = int(base.voice or 0)
            cleaned["musical_voice"] = base.musical_voice
            provenance = base.voice_provenance or "inferred"
            if provenance == "user_edit":
                provenance = "inferred"
            cleaned["voice_provenance"] = provenance
            cleaned["voice_assigned"] = bool(base.voice_assigned)
            cleaned["hand_locked"] = bool(base.hand_locked)
        elif str(cleaned.get("voice_provenance") or "") == "user_edit":
            cleaned["voice_provenance"] = "inferred"
        out.append(cleaned)
    return out


def _edits_digest(corrections: dict | list | None, score_overrides: dict | None = None) -> str | None:
    ops = normalize_corrections(corrections)
    score = _validate_score_overrides(score_overrides)
    if not ops and not score:
        return None
    blob = json.dumps(
        {"operations": canonical_ops(ops), "score": score},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def canonical_ops(ops: list[dict]) -> list[dict]:
    from mir.interpretation_context import canonical_json

    return [canonical_json(op) for op in ops]


ALLOWED_CORRECTION_FIELDS = {
    "source_note_id",
    "id",
    "pitch",
    "track",
    "voice",
    "start",
    "duration",
    "velocity",
    "articulation",
    "exclude",
    "insert",
}
ALLOWED_SIDECAR_KEYS = {"operations", "uncorrected", "score", "uncorrected_score"}
UNC_INT_FIELDS = {"pitch", "track", "voice", "velocity"}
UNC_FLOAT_FIELDS = {"start", "duration"}
UNC_STR_FIELDS = {"articulation"}
LAYOUT_OP_FIELDS = ("pitch", "track", "voice")
SCORE_OP_FIELDS = ("start", "duration", "velocity", "articulation")
SCORE_OVERRIDE_FIELDS = ("tempo_bpm", "time_signature", "tempo_curve")
CORRECTION_TRACK_MIN = 0
CORRECTION_TRACK_MAX = 1
CORRECTION_VOICE_MIN = 0
CORRECTION_VOICE_MAX = 15
BEAT_TOLERANCE = 1e-6
SEC_TOLERANCE = 1e-6


def _source_note_id(row: dict | None) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("source_note_id") or row.get("id") or "")


def _correction_int(value, *, field: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NotationEditConflict([], f"Invalid {field} in a saved correction.")
    number = int(value)
    if number != value or number < lo or number > hi:
        raise NotationEditConflict([], f"Invalid {field} in a saved correction.")
    return number


def _correction_float(value, *, field: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NotationEditConflict([], f"Invalid {field} in a saved correction.")
    number = float(value)
    if not math.isfinite(number) or number < lo or number > hi:
        raise NotationEditConflict([], f"Invalid {field} in a saved correction.")
    return number


def _correction_articulation(value) -> str | None:
    from score_edits import ALLOWED_ARTICULATIONS

    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if text not in ALLOWED_ARTICULATIONS:
        raise NotationEditConflict([], "Invalid articulation in a saved correction.")
    return text


def _beats_close(left, right) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) <= BEAT_TOLERANCE


def _validate_uncorrected_map(payload) -> dict[str, dict]:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise NotationEditConflict(
            [],
            "Saved uncorrected interpretation must be an object keyed by source note ID.",
        )
    out: dict[str, dict] = {}
    for key, row in payload.items():
        sid = str(key or "")
        if not sid:
            raise NotationEditConflict([], "Uncorrected interpretation is missing a source note ID.")
        if not isinstance(row, dict):
            raise NotationEditConflict([sid], f"Uncorrected interpretation for {sid} is not an object.")
        extra = set(row.keys()) - UNC_INT_FIELDS - UNC_FLOAT_FIELDS - UNC_STR_FIELDS
        if extra:
            raise NotationEditConflict(
                [sid],
                "Unsupported uncorrected fields: " + ", ".join(sorted(extra)) + ".",
            )
        fields: dict[str, int | float] = {}
        if "pitch" in row and row["pitch"] is not None:
            fields["pitch"] = _correction_int(row["pitch"], field="pitch", lo=PITCH_MIN, hi=PITCH_MAX)
        if "track" in row and row["track"] is not None:
            fields["track"] = _correction_int(
                row["track"], field="track", lo=CORRECTION_TRACK_MIN, hi=CORRECTION_TRACK_MAX
            )
        if "voice" in row and row["voice"] is not None:
            fields["voice"] = _correction_int(
                row["voice"], field="voice", lo=CORRECTION_VOICE_MIN, hi=CORRECTION_VOICE_MAX
            )
        if "velocity" in row and row["velocity"] is not None:
            fields["velocity"] = _correction_int(row["velocity"], field="velocity", lo=1, hi=127)
        if "start" in row and row["start"] is not None:
            fields["start"] = _correction_float(row["start"], field="start", lo=0.0, hi=MAX_START)
        if "duration" in row and row["duration"] is not None:
            fields["duration"] = _correction_float(
                row["duration"], field="duration", lo=1e-6, hi=MAX_DURATION
            )
        if "articulation" in row:
            fields["articulation"] = _correction_articulation(row.get("articulation"))
        if fields:
            out[sid] = fields
    return out


def _validate_score_overrides(payload) -> dict:
    if not payload:
        return {}
    if not isinstance(payload, dict):
        raise NotationEditConflict([], "Score overrides must be an object.")
    extra = set(payload.keys()) - set(SCORE_OVERRIDE_FIELDS)
    if extra:
        raise NotationEditConflict(
            [],
            "Unsupported score override fields: " + ", ".join(sorted(extra)) + ".",
        )
    from score_edits import validate_tempo, validate_tempo_curve, validate_time_signature

    out: dict[str, Any] = {}
    if payload.get("tempo_bpm") is not None:
        out["tempo_bpm"] = float(validate_tempo(payload["tempo_bpm"]))
    if payload.get("time_signature") is not None:
        out["time_signature"] = validate_time_signature(payload["time_signature"])
    if payload.get("tempo_curve") is not None:
        fallback = out.get("tempo_bpm") or 120.0
        out["tempo_curve"] = validate_tempo_curve(payload["tempo_curve"], fallback_bpm=fallback)
    return out


def _validate_uncorrected_score(payload) -> dict:
    if not payload:
        return {}
    return _validate_score_overrides(payload)


def correction_field_map(model: dict | None) -> dict[str, dict]:
    """Pitch/staff/voice/timing/velocity currently shown for each source note."""
    out: dict[str, dict] = {}
    for row in (model or {}).get("notes") or []:
        sid = _source_note_id(row)
        if not sid:
            continue
        fields: dict[str, int | float] = {}
        if row.get("pitch") is not None:
            fields["pitch"] = int(row["pitch"])
        if row.get("track") is not None:
            fields["track"] = int(row["track"])
        if row.get("voice") is not None:
            fields["voice"] = int(row["voice"])
        if row.get("velocity") is not None:
            fields["velocity"] = int(row["velocity"])
        if row.get("start") is not None:
            fields["start"] = float(row["start"])
        if row.get("duration") is not None:
            fields["duration"] = float(row["duration"])
        if "articulation" in row:
            fields["articulation"] = row.get("articulation") or None
        if fields:
            out[sid] = fields
    return out


def uncorrected_from_events(events) -> dict[str, dict]:
    """Interpreted pitch/staff/musical voice/score timing before user operations."""
    notes = []
    for ev in events or []:
        sid = str(getattr(ev, "note_id", "") or "")
        if not sid:
            continue
        track = 1 if getattr(getattr(ev, "hand", None), "value", "") == "left" else 0
        provenance = str(getattr(ev, "voice_provenance", "") or "")
        musical = getattr(ev, "musical_voice", None)
        printed = int(getattr(ev, "voice", 0) or 0)
        voice = int(musical) if provenance == "user_edit" and musical is not None else printed
        notes.append(
            {
                "source_note_id": sid,
                "pitch": int(ev.pitch),
                "track": track,
                "voice": voice,
                "start": float(ev.start_beat),
                "duration": float(ev.duration_beats),
                "velocity": int(ev.velocity or 64),
                "articulation": getattr(ev, "articulation", None) or None,
            }
        )
    return correction_field_map({"notes": notes})


def baseline_uncorrected(
    *,
    displayed: dict | None,
    existing_ops: list[dict] | None,
    snapshot: PerformanceSnapshot | None,
    stored: dict | None = None,
) -> dict[str, dict]:
    """Uncorrected interpretation: stored baseline, else currently displayed fields without ops."""
    existing = {
        op["source_note_id"]: op
        for op in normalize_corrections(existing_ops or [])
        if op.get("source_note_id") and not op.get("insert")
    }
    displayed_map = correction_field_map(displayed)
    stored_map = _validate_uncorrected_map(stored)
    original = {n.note_id: n for n in snapshot.notes} if snapshot is not None else {}
    sids = set(displayed_map) | set(stored_map) | set(existing) | set(original)
    out: dict[str, dict] = {}
    for sid in sids:
        prev = stored_map.get(sid) or {}
        disp = displayed_map.get(sid) or {}
        op = existing.get(sid) or {}
        orig = original.get(sid)
        row: dict[str, int | float | str | None] = {}
        for field in ("pitch", "track", "voice", "velocity"):
            if prev.get(field) is not None:
                row[field] = int(prev[field])
            elif field not in op and disp.get(field) is not None:
                row[field] = int(disp[field])
            elif field == "pitch" and orig is not None:
                row[field] = int(orig.pitch)
            elif field == "velocity" and orig is not None:
                row[field] = int(orig.velocity or 64)
        for field in ("start", "duration"):
            if prev.get(field) is not None:
                row[field] = float(prev[field])
            elif field not in op and disp.get(field) is not None:
                row[field] = float(disp[field])
        if "articulation" in prev or "articulation" in op or "articulation" in disp:
            if "articulation" in prev:
                row["articulation"] = prev.get("articulation") or None
            elif "articulation" not in op:
                row["articulation"] = disp.get("articulation") or None
        if row:
            out[sid] = row
    return out


def parse_corrections_sidecar(corrections: dict | list | None) -> tuple[list[dict], dict]:
    """Return (operations, uncorrected map). Empty sidecar is valid; malformed is not."""
    if not corrections:
        return [], {}
    stored = {}
    if isinstance(corrections, dict):
        extra = set(corrections.keys()) - ALLOWED_SIDECAR_KEYS - {"notes"}
        if extra:
            raise NotationEditConflict(
                [],
                "Unsupported correction sidecar fields: " + ", ".join(sorted(extra)) + ".",
            )
        if corrections.get("notes") is not None and "operations" not in corrections:
            raise NotationEditConflict(
                [],
                "Saved score corrections are a generated editor model, not "
                "explicit operations. The published score was left unchanged.",
            )
        if "notes" in corrections and "operations" in corrections:
            raise NotationEditConflict(
                [],
                "Correction sidecar cannot mix a generated editor model with operations.",
            )
        stored = _validate_uncorrected_map(corrections.get("uncorrected"))
        _validate_score_overrides(corrections.get("score"))
        _validate_uncorrected_score(corrections.get("uncorrected_score"))
    return normalize_corrections(corrections), stored


def parse_score_sidecar(corrections: dict | list | None) -> tuple[dict, dict]:
    if not isinstance(corrections, dict):
        return {}, {}
    return (
        _validate_score_overrides(corrections.get("score")),
        _validate_uncorrected_score(corrections.get("uncorrected_score")),
    )


def normalize_corrections(corrections: dict | list | None) -> list[dict]:
    """Return explicit correction operations, never a generated editor model.

    A missing or empty operations list is valid. A nonempty malformed payload
    is rejected rather than silently normalized to [].
    """
    if not corrections:
        return []
    if isinstance(corrections, list):
        rows = corrections
    elif isinstance(corrections, dict):
        if "operations" not in corrections:
            if corrections.get("notes"):
                raise NotationEditConflict(
                    [],
                    "Saved score corrections are a generated editor model, not "
                    "explicit operations. The published score was left unchanged.",
                )
            extra = set(corrections.keys()) - ALLOWED_SIDECAR_KEYS
            if extra:
                raise NotationEditConflict(
                    [],
                    "Unsupported correction sidecar fields: "
                    + ", ".join(sorted(extra))
                    + ".",
                )
            return []
        rows = corrections.get("operations")
        if rows is None:
            raise NotationEditConflict([], "Correction operations must be a list.")
        if corrections.get("notes"):
            raise NotationEditConflict(
                [],
                "Correction sidecar cannot mix a generated editor model with operations.",
            )
        extra = set(corrections.keys()) - ALLOWED_SIDECAR_KEYS - {"notes"}
        if extra:
            raise NotationEditConflict(
                [],
                "Unsupported correction sidecar fields: " + ", ".join(sorted(extra)) + ".",
            )
    else:
        raise NotationEditConflict(
            [],
            "Saved score corrections must be a list or an object with operations.",
        )
    if not isinstance(rows, list):
        raise NotationEditConflict([], "Correction operations must be a list.")
    ops = []
    seen = set()
    seen_inserts = set()
    for row in rows:
        if not isinstance(row, dict):
            raise NotationEditConflict(
                [],
                "Each correction operation must be an object with a source note ID.",
            )
        extra = set(row.keys()) - ALLOWED_CORRECTION_FIELDS
        if extra:
            raise NotationEditConflict(
                [],
                "Unsupported correction fields: " + ", ".join(sorted(extra)) + ".",
            )
        is_insert = bool(row.get("insert"))
        if is_insert:
            note_id = str(row.get("id") or "")
            if not note_id:
                raise NotationEditConflict([], "Each inserted note requires an editor id.")
            if note_id in seen_inserts:
                raise NotationEditConflict([note_id], f"Duplicate inserted note {note_id}.")
            seen_inserts.add(note_id)
            if row.get("source_note_id"):
                raise NotationEditConflict(
                    [note_id],
                    "Inserted notes cannot claim a source note ID.",
                )
            op = {"insert": True, "id": note_id}
            if "pitch" not in row or row["pitch"] is None:
                raise NotationEditConflict([note_id], "Inserted notes require pitch.")
            if "start" not in row or row["start"] is None:
                raise NotationEditConflict([note_id], "Inserted notes require start in score beats.")
            if "duration" not in row or row["duration"] is None:
                raise NotationEditConflict([note_id], "Inserted notes require duration in score beats.")
            op["pitch"] = _correction_int(row["pitch"], field="pitch", lo=PITCH_MIN, hi=PITCH_MAX)
            op["start"] = _correction_float(row["start"], field="start", lo=0.0, hi=MAX_START)
            op["duration"] = _correction_float(
                row["duration"], field="duration", lo=1e-6, hi=MAX_DURATION
            )
            op["velocity"] = _correction_int(row.get("velocity", 80), field="velocity", lo=1, hi=127)
            op["track"] = _correction_int(
                row.get("track", 0), field="track", lo=CORRECTION_TRACK_MIN, hi=CORRECTION_TRACK_MAX
            )
            op["voice"] = _correction_int(
                row.get("voice", 0), field="voice", lo=CORRECTION_VOICE_MIN, hi=CORRECTION_VOICE_MAX
            )
            if "articulation" in row:
                op["articulation"] = _correction_articulation(row.get("articulation"))
            ops.append(op)
            continue
        sid = _source_note_id(row)
        if not sid:
            raise NotationEditConflict(
                [],
                "Each correction operation requires a source note ID.",
            )
        if sid in seen:
            raise NotationEditConflict(
                [sid],
                f"Duplicate correction for source note {sid}.",
            )
        seen.add(sid)
        op = {"source_note_id": sid}
        if row.get("exclude"):
            if row.get("exclude") is not True and row.get("exclude") != 1:
                raise NotationEditConflict([sid], "Invalid exclude in a saved correction.")
            op["exclude"] = True
        if "pitch" in row and row["pitch"] is not None:
            op["pitch"] = _correction_int(row["pitch"], field="pitch", lo=PITCH_MIN, hi=PITCH_MAX)
        if "track" in row and row["track"] is not None:
            op["track"] = _correction_int(
                row["track"], field="track", lo=CORRECTION_TRACK_MIN, hi=CORRECTION_TRACK_MAX
            )
        if "voice" in row and row["voice"] is not None:
            op["voice"] = _correction_int(
                row["voice"], field="voice", lo=CORRECTION_VOICE_MIN, hi=CORRECTION_VOICE_MAX
            )
        if "start" in row and row["start"] is not None:
            op["start"] = _correction_float(row["start"], field="start", lo=0.0, hi=MAX_START)
        if "duration" in row and row["duration"] is not None:
            op["duration"] = _correction_float(
                row["duration"], field="duration", lo=1e-6, hi=MAX_DURATION
            )
        if "velocity" in row and row["velocity"] is not None:
            op["velocity"] = _correction_int(row["velocity"], field="velocity", lo=1, hi=127)
        if "articulation" in row:
            op["articulation"] = _correction_articulation(row.get("articulation"))
        if len(op) == 1:
            continue
        ops.append(op)
    return ops


def extract_corrections(
    submitted: dict | None,
    *,
    snapshot: PerformanceSnapshot | None,
    baseline: dict | None = None,
    displayed: dict | None = None,
    uncorrected: dict | None = None,
    existing: list[dict] | dict | None = None,
) -> list[dict]:
    """Merge submitted editor changes into explicit operations.

    Uncorrected interpretation stays separate from user operations. A field is
    recorded only when the submitted value differs from the uncorrected
    interpreted value. Automatic hand/voice inference is never stored. An
    operation is removed only when the user restores that uncorrected value.
    """
    existing_ops = {
        op["source_note_id"]: dict(op)
        for op in normalize_corrections(existing or [])
        if op.get("source_note_id") and not op.get("insert")
    }
    existing_inserts = {
        op["id"]: dict(op) for op in normalize_corrections(existing or []) if op.get("insert")
    }
    if not submitted or submitted.get("notes") is None:
        return normalize_corrections(existing or [])
    original = {n.note_id: n for n in snapshot.notes} if snapshot is not None else {}
    shown = correction_field_map(displayed if displayed is not None else baseline)
    if uncorrected is None:
        uncorrected = {}
    if isinstance(uncorrected, dict) and "notes" in uncorrected:
        uncorrected_map = correction_field_map(uncorrected)
    else:
        uncorrected_map = _validate_uncorrected_map(uncorrected)
    merged: dict[str, dict] = {sid: dict(op) for sid, op in existing_ops.items()}
    inserts: dict[str, dict] = dict(existing_inserts)
    seen_submitted = set()
    seen_insert_ids = set()
    submitted_source_ids = set()
    submitted_insert_ids = set()
    for row in submitted["notes"]:
        sid = str(row.get("source_note_id") or "")
        note_id = str(row.get("id") or "")
        orig = original.get(sid) if sid else None
        if sid and orig is not None:
            submitted_source_ids.add(sid)
            if sid in seen_submitted:
                raise NotationEditConflict([sid], f"Duplicate correction for source note {sid}.")
            seen_submitted.add(sid)
            _reject_performed_timing_mutation(row, orig)
            current = merged.get(sid) or {"source_note_id": sid}
            current.pop("exclude", None)
            unc = dict(uncorrected_map.get(sid) or {})
            if unc.get("pitch") is None:
                unc["pitch"] = int(orig.pitch)
            if unc.get("velocity") is None:
                unc["velocity"] = int(orig.velocity or 64)
            disp = shown.get(sid) or {}
            _merge_note_fields(current, row, unc, disp)
            if len(current) > 1:
                merged[sid] = current
            else:
                merged.pop(sid, None)
            continue
        if snapshot is not None and sid:
            if _row_looks_like_correction(row, None, shown.get(sid), existing_ops.get(sid)):
                raise NotationEditConflict(
                    [sid],
                    f"Correction {sid} does not match a source note.",
                )
            continue
        if snapshot is not None and not sid:
            if not note_id:
                raise NotationEditConflict([], "Each inserted note requires an editor id.")
            if note_id in seen_insert_ids:
                raise NotationEditConflict([note_id], f"Duplicate inserted note {note_id}.")
            seen_insert_ids.add(note_id)
            submitted_insert_ids.add(note_id)
            inserts[note_id] = {
                "insert": True,
                "id": note_id,
                "pitch": int(row["pitch"]),
                "start": float(row["start"]),
                "duration": float(row["duration"]),
                "velocity": int(row.get("velocity") or 80),
                "track": int(row.get("track") or 0),
                "voice": int(row.get("voice") or 0),
            }
            continue
        # MusicXML-only jobs keep publishing the editor model; source-ID operations
        # are recorded only when a source note ID is present.
        if not sid:
            continue
        if sid in seen_submitted:
            raise NotationEditConflict([sid], f"Duplicate correction for source note {sid}.")
        seen_submitted.add(sid)
        submitted_source_ids.add(sid)
        current = merged.get(sid) or {"source_note_id": sid}
        current.pop("exclude", None)
        _merge_note_fields(current, row, uncorrected_map.get(sid) or {}, shown.get(sid) or {})
        if len(current) > 1:
            merged[sid] = current
        else:
            merged.pop(sid, None)
    if snapshot is not None:
        displayed_source_ids = set(shown) | set(existing_ops)
        for sid in displayed_source_ids:
            if sid in submitted_source_ids:
                continue
            if sid not in original:
                continue
            current = merged.get(sid) or {"source_note_id": sid}
            current["exclude"] = True
            merged[sid] = current
        for note_id in list(inserts):
            if note_id not in submitted_insert_ids:
                inserts.pop(note_id, None)
    source_ops = [merged[sid] for sid in sorted(merged)]
    insert_ops = [inserts[note_id] for note_id in sorted(inserts)]
    return source_ops + insert_ops


def _merge_note_fields(current: dict, row: dict, unc: dict, disp: dict) -> None:
    for field in LAYOUT_OP_FIELDS + ("velocity",):
        if row.get(field) is None:
            continue
        submitted_value = int(row[field])
        uncorrected_value = unc.get(field)
        displayed_value = disp.get(field)
        if displayed_value is not None and submitted_value == int(displayed_value):
            continue
        if uncorrected_value is not None and submitted_value == int(uncorrected_value):
            current.pop(field, None)
        else:
            current[field] = submitted_value
    for field in ("start", "duration"):
        if row.get(field) is None:
            continue
        submitted_value = float(row[field])
        uncorrected_value = unc.get(field)
        displayed_value = disp.get(field)
        if displayed_value is not None and _beats_close(submitted_value, displayed_value):
            continue
        if uncorrected_value is not None and _beats_close(submitted_value, uncorrected_value):
            current.pop(field, None)
        else:
            current[field] = submitted_value
    if "articulation" in row:
        submitted_value = _correction_articulation(row.get("articulation"))
        uncorrected_value = unc.get("articulation") if "articulation" in unc else None
        displayed_value = disp.get("articulation") if "articulation" in disp else None
        if displayed_value is not None and submitted_value == (displayed_value or None):
            return
        if "articulation" in unc and submitted_value == (uncorrected_value or None):
            current.pop("articulation", None)
        else:
            current["articulation"] = submitted_value


def _reject_performed_timing_mutation(row: dict, orig) -> None:
    sid = _source_note_id(row)
    if "start_sec" in row and row["start_sec"] is not None:
        if abs(float(row["start_sec"]) - float(orig.start_sec)) > SEC_TOLERANCE:
            raise NotationEditConflict(
                [sid],
                "Performed start_sec cannot be changed. Use start (score beats) instead.",
            )
    if "end_sec" in row and row["end_sec"] is not None:
        if abs(float(row["end_sec"]) - float(orig.end_sec)) > SEC_TOLERANCE:
            raise NotationEditConflict(
                [sid],
                "Performed end_sec cannot be changed. Use duration (score beats) instead.",
            )


def _curves_close(left, right) -> bool:
    if not left or not right:
        return False
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if abs(float(a.get("beat", 0)) - float(b.get("beat", 0))) > BEAT_TOLERANCE:
            return False
        if abs(float(a.get("bpm", 0)) - float(b.get("bpm", 0))) > 1e-6:
            return False
    return True


def extract_score_overrides(
    submitted: dict | None,
    *,
    displayed: dict | None = None,
    uncorrected_score: dict | None = None,
    existing_score: dict | None = None,
) -> dict:
    """Preserve editor tempo/meter when they actually change; ignore echoed values."""
    if not submitted:
        return _validate_score_overrides(existing_score)
    existing = dict(_validate_score_overrides(existing_score))
    unc = dict(_validate_uncorrected_score(uncorrected_score))
    disp = displayed or {}
    if submitted.get("tempo_bpm") is not None:
        submitted_bpm = float(submitted["tempo_bpm"])
        displayed_bpm = float(disp["tempo_bpm"]) if disp.get("tempo_bpm") is not None else None
        uncorrected_bpm = float(unc["tempo_bpm"]) if unc.get("tempo_bpm") is not None else None
        if displayed_bpm is None or abs(submitted_bpm - displayed_bpm) > 1e-6:
            if uncorrected_bpm is not None and abs(submitted_bpm - uncorrected_bpm) <= 1e-6:
                existing.pop("tempo_bpm", None)
            else:
                existing["tempo_bpm"] = submitted_bpm
    if submitted.get("time_signature"):
        submitted_meter = str(submitted["time_signature"])
        displayed_meter = str(disp["time_signature"]) if disp.get("time_signature") else None
        uncorrected_meter = str(unc["time_signature"]) if unc.get("time_signature") else None
        if displayed_meter is None or submitted_meter != displayed_meter:
            if uncorrected_meter is not None and submitted_meter == uncorrected_meter:
                existing.pop("time_signature", None)
            else:
                existing["time_signature"] = submitted_meter
    if submitted.get("tempo_curve") is not None:
        submitted_curve = submitted["tempo_curve"]
        displayed_curve = disp.get("tempo_curve")
        uncorrected_curve = unc.get("tempo_curve")
        if displayed_curve is None or not _curves_close(submitted_curve, displayed_curve):
            if uncorrected_curve is not None and _curves_close(submitted_curve, uncorrected_curve):
                existing.pop("tempo_curve", None)
            else:
                existing["tempo_curve"] = submitted_curve
    return _validate_score_overrides(existing)


def _row_looks_like_correction(row: dict, orig, previous: dict | None, existing: dict | None = None) -> bool:
    if orig is not None:
        return False
    if existing:
        return True
    if previous is None:
        return any(row.get(field) is not None for field in ("pitch", "track", "voice", "start", "duration", "velocity", "articulation"))
    if row.get("pitch") is not None and int(row["pitch"]) != int(previous.get("pitch") or -1):
        return True
    if row.get("track") is not None and int(row["track"]) != int(previous.get("track") or -1):
        return True
    if row.get("voice") is not None and int(row["voice"]) != int(previous.get("voice") or 0):
        return True
    if row.get("velocity") is not None and int(row["velocity"]) != int(previous.get("velocity") or 0):
        return True
    if row.get("start") is not None and not _beats_close(row["start"], previous.get("start")):
        return True
    if row.get("duration") is not None and not _beats_close(row["duration"], previous.get("duration")):
        return True
    if "articulation" in row and (row.get("articulation") or None) != (previous.get("articulation") or None):
        return True
    return False


def apply_note_edits(events, corrections, snapshot: PerformanceSnapshot, *, stage: str = "all"):
    """Reattach explicit corrections by stable source IDs.

    ``stage="layout"`` applies pitch/staff/musical voice before automatic
    notation. ``stage="score"`` applies score-beat timing, velocity, deletes,
    and inserts after automatic notation. Performed seconds stay on the event.
    """
    ops = normalize_corrections(corrections)
    if not ops:
        return list(events)
    if stage in {"layout", "all"}:
        events = _apply_layout_ops(events, ops, snapshot)
    if stage in {"score", "all"}:
        events = _apply_score_ops(events, ops, snapshot)
    return events


def _apply_layout_ops(events, ops: list[dict], snapshot: PerformanceSnapshot):
    from mir.types import Hand

    present = {ev.note_id for ev in events}
    original = {n.note_id: n for n in snapshot.notes}
    missing = []
    by_source = {}
    for op in ops:
        if op.get("insert") or op.get("exclude"):
            continue
        if not any(field in op for field in LAYOUT_OP_FIELDS):
            continue
        sid = op["source_note_id"]
        by_source[sid] = op
        if sid not in present or sid not in original:
            missing.append(sid)
    if missing:
        raise NotationEditConflict(missing)
    if not by_source:
        return list(events)
    out = []
    for ev in events:
        op = by_source.get(ev.note_id)
        if not op:
            out.append(ev)
            continue
        changes: dict[str, Any] = {}
        if op.get("pitch") is not None and int(op["pitch"]) != int(ev.pitch):
            changes["pitch"] = int(op["pitch"])
        if op.get("track") is not None:
            hand = Hand.LEFT if int(op["track"]) == 1 else Hand.RIGHT if int(op["track"]) == 0 else ev.hand
            if hand != ev.hand:
                changes["hand"] = hand
                changes["hand_locked"] = True
        if op.get("voice") is not None:
            musical_voice = int(op["voice"])
            if musical_voice != int(ev.voice) or getattr(ev, "musical_voice", None) != musical_voice:
                changes["voice"] = musical_voice
                changes["musical_voice"] = musical_voice
                changes["voice_assigned"] = True
                changes["voice_provenance"] = "user_edit"
        out.append(copy_event(ev, **changes) if changes else ev)
    return out


def _apply_score_ops(events, ops: list[dict], snapshot: PerformanceSnapshot):
    from mir.types import Hand

    original = {n.note_id: n for n in snapshot.notes}
    present = {ev.note_id for ev in events}
    excluded = {op["source_note_id"] for op in ops if op.get("exclude") and op.get("source_note_id")}
    missing = [
        op["source_note_id"]
        for op in ops
        if not op.get("insert")
        and op.get("source_note_id")
        and (op.get("exclude") or any(field in op for field in SCORE_OP_FIELDS))
        and (op["source_note_id"] not in original or (op["source_note_id"] not in present and not op.get("exclude")))
    ]
    if missing:
        raise NotationEditConflict(missing)
    by_source = {
        op["source_note_id"]: op
        for op in ops
        if op.get("source_note_id") and not op.get("insert")
    }
    out = []
    for ev in events:
        if ev.note_id in excluded:
            continue
        op = by_source.get(ev.note_id)
        if not op:
            out.append(ev)
            continue
        changes: dict[str, Any] = {}
        if op.get("start") is not None and not _beats_close(op["start"], ev.start_beat):
            changes["start_beat"] = float(op["start"])
            changes["score_timing_locked"] = True
        if op.get("duration") is not None and not _beats_close(op["duration"], ev.duration_beats):
            changes["duration_beats"] = float(op["duration"])
            changes["score_timing_locked"] = True
        if op.get("velocity") is not None and int(op["velocity"]) != int(ev.velocity or 64):
            changes["velocity"] = int(op["velocity"])
        if "articulation" in op:
            mark = op.get("articulation") or None
            if mark != (ev.articulation or None):
                changes["articulation"] = mark
        out.append(copy_event(ev, **changes) if changes else ev)
    for op in ops:
        if not op.get("insert"):
            continue
        hand = Hand.LEFT if int(op.get("track") or 0) == 1 else Hand.RIGHT
        out.append(
            MusicalEvent(
                int(op["pitch"]),
                float(op["start"]),
                float(op["duration"]),
                velocity=int(op.get("velocity") or 80),
                note_id=str(op["id"]),
                voice=int(op.get("voice") or 0),
                musical_voice=int(op.get("voice") or 0),
                hand=hand,
                voice_assigned=True,
                voice_provenance="user_edit",
                hand_locked=True,
                score_timing_locked=True,
                articulation=op.get("articulation") or None,
            )
        )
    return out


def _planner_edit_error(exc: Exception) -> NotationEditConflict | None:
    text = str(exc)
    lowered = text.lower()
    if any(
        token in lowered
        for token in (
            "unspellable",
            "overlapping attack",
            "edited duration",
            "edited onset",
            "not a positive writable",
        )
    ):
        return NotationEditConflict(
            [],
            "Edited timing cannot be engraved without changing the written values. "
            f"{text}",
        )
    if any(
        token in lowered
        for token in (
            "articulation ownership",
            "source articulation",
            "tied continuation",
            "mixed chord articulation",
        )
    ):
        return NotationEditConflict(
            [],
            "These articulations cannot be engraved without dropping or "
            f"reassigning a source-note mark. {text}",
        )
    return None


def _apply_score_meta_overrides(meta, settings, score_overrides: dict | None):
    if not score_overrides:
        return meta
    extra = dict(meta.extra or {})
    if score_overrides.get("tempo_bpm") is not None:
        meta.display_tempo_bpm = max(1, int(round(float(score_overrides["tempo_bpm"]))))
        extra["display_bpm_exact"] = float(score_overrides["tempo_bpm"])
    if score_overrides.get("time_signature"):
        meter = str(score_overrides["time_signature"])
        meta.time_sig_hint = meter
        extra["notation_settings"] = settings.replace(meter=meter).to_dict()
    if score_overrides.get("tempo_curve") is not None:
        extra["playback_tempo"] = [
            {"beat": float(point["beat"]), "bpm": float(point["bpm"])}
            for point in score_overrides["tempo_curve"]
        ]
    meta.extra = extra
    return meta


def _has_score_stage_ops(ops: list[dict]) -> bool:
    for op in ops:
        if op.get("insert") or op.get("exclude"):
            return True
        if any(field in op for field in SCORE_OP_FIELDS):
            return True
    return False


def _apply_score_model_overrides(model: dict, score_overrides: dict | None) -> dict:
    if not score_overrides:
        return model
    updated = dict(model)
    if score_overrides.get("tempo_bpm") is not None:
        updated["tempo_bpm"] = float(score_overrides["tempo_bpm"])
    if score_overrides.get("time_signature"):
        updated["time_signature"] = str(score_overrides["time_signature"])
    if score_overrides.get("tempo_curve") is not None:
        updated["tempo_curve"] = list(score_overrides["tempo_curve"])
    return updated


def corrections_sidecar_payload(
    operations: list[dict] | None,
    uncorrected: dict | None,
    *,
    score_overrides: dict | None = None,
    uncorrected_score: dict | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "operations": list(operations or []),
        "uncorrected": uncorrected or {},
    }
    if score_overrides:
        payload["score"] = score_overrides
    if uncorrected_score:
        payload["uncorrected_score"] = uncorrected_score
    return payload


def corrections_have_edits(operations: list[dict] | None, score_overrides: dict | None = None) -> bool:
    return bool(operations) or bool(score_overrides)


def editor_model_from_events(
    events,
    *,
    tempo_bpm: float,
    time_signature: str,
    printed_marks=None,
    time_map=None,
) -> dict:
    from score_edits import (
        ID_RE,
        MAX_DURATION,
        PITCH_MAX,
        PITCH_MIN,
        PROVENANCE_PERFORMANCE,
        assign_overlap_voices,
        curve_from_time_map,
        validate_notes,
        validate_tempo,
        validate_time_signature,
    )

    notes = []
    has_user_voice = False
    for index, ev in enumerate(events):
        note_id = str(ev.note_id or f"n-{index:04d}")
        track = 1 if getattr(ev.hand, "value", "") == "left" else 0
        provenance = str(getattr(ev, "voice_provenance", "") or "")
        musical = getattr(ev, "musical_voice", None)
        printed = int(getattr(ev, "voice", 0) or 0)
        if provenance == "user_edit":
            has_user_voice = True
            voice = int(musical) if musical is not None else printed
        else:
            voice = printed
        notes.append(
            {
                "id": note_id if ID_RE.match(note_id) else f"n-{index:04d}",
                "source_note_id": ev.note_id if ID_RE.match(str(ev.note_id or "")) else None,
                "pitch": max(PITCH_MIN, min(PITCH_MAX, int(ev.pitch))),
                "start": max(0.0, float(ev.start_beat)),
                "duration": min(MAX_DURATION, max(1e-6, float(ev.duration_beats))),
                "velocity": max(1, min(127, int(ev.velocity or 64))),
                "track": track,
                "voice": voice,
                "start_sec": getattr(ev, "start_time_sec", None),
                "end_sec": getattr(ev, "end_time_sec", None),
                "articulation": getattr(ev, "articulation", None) or None,
            }
        )
    notes = (
        assign_overlap_voices(notes)
        if not has_user_voice and all(int(n.get("voice") or 0) == 0 for n in notes)
        else notes
    )
    printed = []
    for mark in printed_marks or []:
        if isinstance(mark, dict):
            printed.append(
                {
                    "beat": float(mark.get("beat", 0)),
                    "bpm": mark.get("bpm"),
                    "mark": str(mark.get("mark") or "metronome"),
                    "reason": str(mark.get("reason") or ""),
                }
            )
    tempo = validate_tempo(tempo_bpm)
    curve = (
        curve_from_time_map(time_map, fallback_bpm=tempo)
        if time_map is not None
        else [{"beat": 0.0, "bpm": tempo}]
    )
    return {
        "tempo_bpm": tempo,
        "time_signature": validate_time_signature(time_signature, strict=False),
        "tempo_curve": curve,
        "printed_tempo_marks": printed,
        "provenance": PROVENANCE_PERFORMANCE,
        "notes": validate_notes(notes),
    }


def _select_notes(performance: PerformanceSnapshot, context: InterpretationContext | None):
    notes = list(performance.to_notes())
    if context is None:
        return notes
    known = {n.note_id for n in notes}
    accepted = [ident for ident in context.accepted_source_note_ids if ident]
    excluded = [ident for ident in context.excluded_source_note_ids if ident]
    if len(accepted) != len(set(accepted)):
        raise InterpretationContextError("Accepted source note IDs contain duplicates.")
    if len(excluded) != len(set(excluded)):
        raise InterpretationContextError("Excluded source note IDs contain duplicates.")
    both = sorted(set(accepted) & set(excluded))
    if both:
        raise InterpretationContextError(
            "Notes cannot be both kept and excluded: " + ", ".join(both) + "."
        )
    unknown_accepted = [ident for ident in accepted if ident not in known]
    unknown_excluded = [ident for ident in excluded if ident not in known]
    if unknown_accepted:
        raise InterpretationContextError(
            "Interpretation context lists unknown accepted notes: "
            + ", ".join(unknown_accepted)
            + ". The published score was left unchanged."
        )
    if unknown_excluded:
        raise InterpretationContextError(
            "Interpretation context lists unknown excluded notes: "
            + ", ".join(unknown_excluded)
            + ". The published score was left unchanged."
        )
    if not context.has_recorded_selection:
        blocked = set(excluded)
        return [note for note in notes if note.note_id not in blocked]
    if not accepted and not excluded:
        raise InterpretationContextError(
            "Interpretation context recorded an empty note selection. "
            "The published score was left unchanged."
        )
    if accepted:
        selected = [note for note in notes if note.note_id in set(accepted)]
        if not selected:
            raise InterpretationContextError(
                "Interpretation context does not match any source notes. "
                "The published score was left unchanged."
            )
        return selected
    remaining = [note for note in notes if note.note_id not in set(excluded)]
    if not remaining:
        raise InterpretationContextError(
            "Interpretation context selected no source notes. "
            "The published score was left unchanged."
        )
    return remaining


def _layout_rows(context: InterpretationContext | None, prior_decisions: list[dict] | None):
    """Published interpretation wins; original debug is migration-only."""
    if context is not None and context.layout_decisions:
        return list(context.layout_decisions)
    if context is not None and not context.fallback:
        return None
    if prior_decisions:
        return list(prior_decisions)
    return None


def _bind_snapshot(performance: PerformanceSnapshot | None, midi_bytes: bytes) -> PerformanceSnapshot:
    if performance is None:
        import io
        import pretty_midi

        midi = pretty_midi.PrettyMIDI(io.BytesIO(midi_bytes))
        from mir.performance import snapshot_midi

        return snapshot_midi(midi, midi_bytes, backend="midi")
    if performance.midi_sha256 is None:
        performance = performance.with_midi_identity(midi_bytes)
    performance.verify_midi(midi_bytes)
    return performance


def recompute_notation(
    *,
    midi_bytes: bytes,
    settings: NotationSettings | dict | None = None,
    performance: PerformanceSnapshot | None = None,
    meter: str | None = None,
    prior_decisions: list[dict] | None = None,
    tempo_map=None,
    display_bpm: int | None = None,
    context: InterpretationContext | None = None,
    edits: dict | None = None,
    corrections: dict | list | None = None,
    uncorrected: dict | None = None,
    score_overrides: dict | None = None,
    fallback: str | None = None,
    explicit_pickup: bool = False,
) -> NotationRegenResult:
    """Build a new score from frozen performance MIDI and production context.

    Never calls an audio transcriber. Raises if the MIDI checksum does not
    match a provided performance snapshot. A display-grid change reuses the
    supplied seconds-to-score-beats map instead of re-ingesting MIDI tempo.
    """
    settings = parse_notation_settings(settings)
    performance = _bind_snapshot(performance, midi_bytes)
    digest = hashlib.sha256(midi_bytes).hexdigest()

    used_fallback = fallback or (context.fallback if context is not None else None)
    mapper = None
    meter_hint = settings.meter or meter
    key_hint = None
    instrument = InstrumentKind.PIANO
    pedal_events = []
    printed = []
    playback = []
    if context is not None:
        mapper = context.time_map
        meter_hint = settings.meter or context.selected_meter or meter_hint
        key_hint = context.key_name
        try:
            instrument = InstrumentKind(context.instrument)
        except ValueError:
            instrument = InstrumentKind.PIANO
        pedal_events = list(context.pedal_events)
        printed = list(context.printed_tempo)
        playback = list(context.playback_tempo)
        if not explicit_pickup and not context.time_map_includes_score_offset:
            if context.pickup_beats is not None and settings.pickup_beats is None:
                settings = settings.replace(pickup_beats=context.pickup_beats)
            if context.first_downbeat_beat is not None and settings.first_downbeat_beat is None:
                settings = settings.replace(first_downbeat_beat=context.first_downbeat_beat)
        if not meter_hint:
            meter_hint = context.selected_meter
        if context.midi_sha256 and context.midi_sha256 != digest:
            raise ValueError("Interpretation context MIDI checksum mismatch")
    elif tempo_map is not None:
        mapper = tempo_map
        used_fallback = used_fallback or FALLBACK_MIDI_INGEST
    elif used_fallback == FALLBACK_MISSING:
        raise InterpretationContextError(
            "Missing production interpretation context; refusing silent "
            "MIDI-tempo reinterpretation."
        )
    else:
        mapper = _ingest_mapper(midi_bytes)
        used_fallback = used_fallback or FALLBACK_MIDI_INGEST

    if mapper is None:
        raise InterpretationContextError(
            "Missing production interpretation context; refusing silent "
            "MIDI-tempo reinterpretation."
        )

    notes = _select_notes(performance, context)
    if not notes:
        raise InterpretationContextError(
            "No accepted source notes remain for notation regeneration."
        )
    source_ids = [n.note_id for n in notes]
    backend = performance.source_backend or (context.source_backend if context else "midi")
    events = notes_to_events(notes, mapper, source_backend=backend)
    layout_rows = _layout_rows(context, prior_decisions)
    stored_uncorrected = _validate_uncorrected_map(uncorrected)
    events = _layout_from_decisions(events, layout_rows, uncorrected=stored_uncorrected)
    baseline_events = list(events)
    applied_corrections = corrections if corrections is not None else edits
    applied_ops = normalize_corrections(applied_corrections)
    applied_score = _validate_score_overrides(score_overrides)
    events = apply_note_edits(events, applied_ops, performance, stage="layout")
    if notes:
        try:
            instrument = notes[0].instrument if notes[0].instrument != InstrumentKind.UNKNOWN else instrument
        except Exception:
            pass
    display = display_bpm
    if display is None and context is not None:
        display = context.display_bpm
    if display is None:
        bpm_at = getattr(mapper, "bpm_at", None)
        display = bpm_at(0) if callable(bpm_at) else 120
    from mir.interpretation_context import tempo_map_from_musical
    from timing.tempo_map import MusicalTimeMap

    if context is not None:
        score_tempo = context.tempo_map()
    elif isinstance(mapper, MusicalTimeMap):
        score_tempo = tempo_map_from_musical(mapper)
    else:
        score_tempo = mapper
    meta = build_score_meta(
        score_tempo,
        instrument,
        [],
        display_bpm=max(1, int(round(float(display)))),
        instrument_confidence=0.9,
        time_sig_hint=meter_hint,
        key_hint=key_hint,
    )
    meta.extra = {
        **(meta.extra or {}),
        "notation_settings": settings.to_dict(),
        "pedal_events": pedal_events,
        "preserve_midi_tempo": True,
        "printed_tempo": printed,
        "playback_tempo": playback,
        "interpretation_context": context.to_dict() if context is not None else None,
        "display_bpm_exact": float(display),
    }
    writer = NotationWriter()
    score = writer.write_from_events_direct(
        events, meta, quantization_mode=QuantizationMode.PERFORMANCE
    )
    if [n.note_id for n in notes] != source_ids:
        raise ValueError("Notation regen mutated source note IDs")
    performance.verify_midi(midi_bytes)
    decisions = list(writer.last_quantization_decisions or [])
    summary = dict(writer.last_quantization_summary or {})
    policy_exceptions = [
        public_policy_exception(row) for row in (summary.get("policy_exceptions") or [])
    ]
    quantized = list(writer.last_quantized_events or events)
    previous_report = (
        writer.last_result.quantization.report
        if writer.last_result is not None and writer.last_result.quantization is not None
        else None
    )
    model_kwargs = dict(
        tempo_bpm=float(display or 120),
        time_signature=str(meter_hint or "4/4"),
        printed_marks=printed,
        time_map=mapper if hasattr(mapper, "interval_bpms") else (
            context.time_map if context is not None else None
        ),
    )
    baseline_by_id = {ev.note_id: ev for ev in baseline_events if getattr(ev, "note_id", "")}
    uncorrected_quantized = []
    for ev in quantized:
        base = baseline_by_id.get(ev.note_id)
        if base is None:
            uncorrected_quantized.append(ev)
            continue
        uncorrected_quantized.append(
            copy_event(
                ev,
                pitch=base.pitch,
                hand=base.hand,
                voice=base.voice,
                musical_voice=base.musical_voice,
                voice_provenance=base.voice_provenance if base.voice_provenance != "user_edit" else "inferred",
                hand_locked=base.hand_locked,
                voice_assigned=base.voice_assigned,
            )
        )
    uncorrected_model = editor_model_from_events(uncorrected_quantized, **model_kwargs)
    reconstructed_uncorrected = correction_field_map(uncorrected_model)
    # Keep previously stored pitch/staff/voice when present so a later grid
    # change cannot rebuild uncorrected layout from a corrected context.
    next_uncorrected: dict[str, dict] = {}
    for sid, row in reconstructed_uncorrected.items():
        merged_row = dict(row)
        prev = stored_uncorrected.get(sid) or {}
        for field in ("pitch", "track", "voice"):
            if prev.get(field) is not None:
                merged_row[field] = int(prev[field])
        next_uncorrected[sid] = merged_row
    for sid, prev in stored_uncorrected.items():
        if sid not in next_uncorrected:
            next_uncorrected[sid] = dict(prev)
    uncorrected_score = {
        "tempo_bpm": float(uncorrected_model["tempo_bpm"]),
        "time_signature": str(uncorrected_model["time_signature"]),
        "tempo_curve": list(uncorrected_model.get("tempo_curve") or []),
    }
    published_events = apply_note_edits(quantized, applied_ops, performance, stage="score")
    editor_model = editor_model_from_events(published_events, **model_kwargs)
    editor_model = _apply_score_model_overrides(editor_model, applied_score)
    meta = _apply_score_meta_overrides(meta, settings, applied_score)
    if _has_score_stage_ops(applied_ops) or applied_score:
        try:
            score = writer.write_from_quantized_events(
                published_events,
                meta,
                report=previous_report,
            )
        except ValueError as exc:
            conflict = _planner_edit_error(exc)
            if conflict:
                raise conflict from exc
            raise
        writer.last_quantization_decisions = decisions
        writer.last_quantization_summary = summary
        writer.last_quantized_events = published_events
    xml, score_midi = writer.export_musicxml_and_midi(score, meta)
    edits_digest = _edits_digest(applied_ops, applied_score)
    input_identity = context.identity_digest() if context is not None else None
    cache = settings.cache_key(
        digest, context_digest=input_identity, edits_digest=edits_digest
    )
    next_context = context
    if context is not None:
        accepted = tuple(n.note_id for n in notes)
        next_payload = {
            **context.to_dict(),
            "accepted_source_note_ids": list(accepted),
            "has_recorded_selection": True,
            "layout_decisions": _uncorrected_layout_decisions(decisions, baseline_events),
            "midi_sha256": digest,
            "fallback": used_fallback,
            "score_beat_offset": float(summary.get("score_beat_offset", context.score_beat_offset) or 0.0),
        }
        if explicit_pickup:
            next_payload["pickup_beats"] = settings.pickup_beats
            next_payload["first_downbeat_beat"] = settings.first_downbeat_beat
        else:
            if settings.pickup_beats is not None:
                next_payload["pickup_beats"] = settings.pickup_beats
            if settings.first_downbeat_beat is not None:
                next_payload["first_downbeat_beat"] = settings.first_downbeat_beat
        next_context = InterpretationContext.from_dict(next_payload)
    output_identity = next_context.identity_digest() if next_context is not None else None
    return NotationRegenResult(
        musicxml=xml,
        settings=settings,
        cache_key=cache,
        midi_sha256=digest,
        source_note_count=len(notes),
        transcribed=False,
        decisions=decisions,
        summary=summary,
        score_midi=score_midi,
        context=next_context,
        fallback=used_fallback,
        policy_exceptions=policy_exceptions,
        editor_model=editor_model,
        edits_digest=edits_digest,
        input_identity=input_identity,
        output_identity=output_identity,
        uncorrected=next_uncorrected,
        uncorrected_score=uncorrected_score,
        score_overrides=applied_score,
    )


def _ingest_mapper(midi_bytes: bytes):
    import tempfile

    from mir.midi_ingest import ingest_midi

    with tempfile.NamedTemporaryFile(suffix=".mid") as handle:
        handle.write(midi_bytes)
        handle.flush()
        ingested = ingest_midi(Path(handle.name))
    return ingested.tempo_map


def recompute_job_dir(out_dir: Path, job_id: str, settings: NotationSettings | dict | None = None) -> NotationRegenResult:
    """Rewrite derived score files in an existing job directory."""
    out_dir = Path(out_dir)
    raw_path = out_dir / f"{job_id}.raw.mid"
    snap_path = out_dir / f"{job_id}.performance.json"
    debug_path = out_dir / f"{job_id}.debug.json"
    context_path = out_dir / f"{job_id}.interpretation_context.json"
    tempo_path = out_dir / f"{job_id}.tempo.json"
    if not raw_path.exists():
        raise FileNotFoundError(f"Missing raw MIDI for job {job_id}")
    midi_bytes = raw_path.read_bytes()
    performance = PerformanceSnapshot.read_json(snap_path) if snap_path.exists() else None
    prior = None
    if debug_path.exists():
        debug = json.loads(debug_path.read_text(encoding="utf-8"))
        extra = debug.get("extra") or debug
        prior = extra.get("quantization_decisions") or extra.get("quantization_summary")
        if isinstance(prior, dict):
            prior = None
    tempo_payload = None
    if tempo_path.exists():
        tempo_payload = json.loads(tempo_path.read_text(encoding="utf-8"))
    context_raw = context_path.read_bytes() if context_path.exists() else None
    context, status = load_context_payload(
        context_raw,
        tempo_payload=tempo_payload,
        midi_sha256=getattr(performance, "midi_sha256", None),
        source_backend=getattr(performance, "source_backend", "") or "",
        layout_decisions=tuple(prior) if isinstance(prior, list) else (),
    )
    if context is None and status == FALLBACK_MISSING:
        raise InterpretationContextError(
            "Missing production interpretation context; refusing silent "
            "MIDI-tempo reinterpretation."
        )
    result = recompute_notation(
        midi_bytes=midi_bytes,
        settings=settings,
        performance=performance,
        prior_decisions=None if context is not None and not getattr(context, "fallback", None) else (
            prior if isinstance(prior, list) else None
        ),
        context=context,
        fallback=status,
    )
    after = raw_path.read_bytes()
    if hashlib.sha256(after).hexdigest() != result.midi_sha256:
        raise ValueError("Notation regen changed original MIDI bytes")
    (out_dir / f"{job_id}.musicxml").write_text(result.musicxml, encoding="utf-8")
    if result.score_midi:
        (out_dir / f"{job_id}.score.mid").write_bytes(result.score_midi)
    if result.context is not None:
        result.context.write_json(out_dir / f"{job_id}.interpretation_context.json")
    (out_dir / f"{job_id}.notation_settings.json").write_text(
        json.dumps(
            {
                "notation_settings": result.settings.to_dict(),
                "algorithm_version": result.settings.algorithm_version,
                "notation_cache_key": result.cache_key,
                "midi_sha256": result.midi_sha256,
                "interpretation_context_digest": (
                    result.output_identity
                    or (result.context.identity_digest() if result.context else None)
                ),
                "input_identity": result.input_identity,
                "output_identity": result.output_identity,
                "identity_role": "regenerated_output",
                "fallback": result.fallback,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def reset_settings() -> NotationSettings:
    return settings_for_reset()
