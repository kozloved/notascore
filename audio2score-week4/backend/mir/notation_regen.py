"""Recompute notation from an existing performance without re-transcribing audio.

Original MIDI bytes and the performance snapshot stay untouched. Only the
derived score artifacts are rewritten. Cache identity includes the MIDI
checksum, algorithm version, notation settings, interpretation context,
and applied edit identity.
"""

from __future__ import annotations

import hashlib
import json
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
from mir.types import InstrumentKind, ScoreMeta, copy_event
from notation_engine.writer import NotationWriter


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


def _layout_from_decisions(events, decisions):
    from mir.types import Hand, copy_event as _copy

    by_id = {row.get("note_id"): row for row in decisions or [] if row.get("note_id")}
    if not by_id:
        return events
    out = []
    for ev in events:
        row = by_id.get(ev.note_id)
        if not row:
            out.append(ev)
            continue
        hand_value = row.get("hand") or ev.hand.value
        try:
            hand = Hand(hand_value)
        except ValueError:
            hand = ev.hand
        musical = row.get("musical_voice")
        out.append(
            _copy(
                ev,
                hand=hand,
                voice=int(row.get("printed_voice", row.get("voice", ev.voice)) or 0),
                musical_voice=None if musical is None else int(musical),
                voice_assigned=True,
                voice_provenance=row.get("voice_provenance") or ev.voice_provenance or "supplied",
            )
        )
    return out


def _edits_digest(corrections: dict | list | None) -> str | None:
    ops = normalize_corrections(corrections)
    if not ops:
        return None
    blob = json.dumps(canonical_ops(ops), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def canonical_ops(ops: list[dict]) -> list[dict]:
    from mir.interpretation_context import canonical_json

    return [canonical_json(op) for op in ops]


def normalize_corrections(corrections: dict | list | None) -> list[dict]:
    """Return explicit correction operations, never a generated editor model."""
    if not corrections:
        return []
    if isinstance(corrections, list):
        rows = corrections
    else:
        rows = corrections.get("operations")
        if rows is None and corrections.get("notes"):
            raise NotationEditConflict(
                [],
                "Saved score corrections are a generated editor model, not "
                "explicit operations. The published score was left unchanged.",
            )
        rows = rows or []
    ops = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("source_note_id") or row.get("id") or "")
        if not sid:
            continue
        if sid in seen:
            raise NotationEditConflict(
                [sid],
                f"Duplicate correction for source note {sid}.",
            )
        seen.add(sid)
        op = {"source_note_id": sid}
        if row.get("pitch") is not None:
            op["pitch"] = int(row["pitch"])
        if row.get("track") is not None:
            op["track"] = int(row["track"])
        if row.get("voice") is not None:
            op["voice"] = int(row["voice"])
        if len(op) == 1:
            continue
        ops.append(op)
    return ops


def extract_corrections(
    submitted: dict | None,
    *,
    snapshot: PerformanceSnapshot,
    baseline: dict | None = None,
) -> list[dict]:
    """Diff a saved editor model against snapshot pitch/staff and baseline voice."""
    if not submitted or not submitted.get("notes"):
        return []
    original = {n.note_id: n for n in snapshot.notes}
    previous = {}
    for row in (baseline or {}).get("notes") or []:
        sid = str(row.get("source_note_id") or row.get("id") or "")
        if sid:
            previous[sid] = row
    ops = []
    for row in submitted["notes"]:
        sid = str(row.get("source_note_id") or row.get("id") or "")
        if not sid:
            continue
        orig = original.get(sid)
        op: dict[str, Any] = {"source_note_id": sid}
        if orig is None:
            if _row_looks_like_correction(row, None, previous.get(sid)):
                raise NotationEditConflict(
                    [sid],
                    f"Correction {sid} does not match a source note.",
                )
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


def _row_looks_like_correction(row: dict, orig, previous: dict | None) -> bool:
    if orig is None and (row.get("pitch") is not None or row.get("track") is not None):
        if previous is None:
            return True
        if row.get("pitch") is not None and int(row["pitch"]) != int(previous.get("pitch") or -1):
            return True
        if row.get("track") is not None and int(row["track"]) != int(previous.get("track") or -1):
            return True
        if row.get("voice") is not None and int(row["voice"]) != int(previous.get("voice") or 0):
            return True
    return False


def apply_note_edits(events, corrections, snapshot: PerformanceSnapshot):
    """Reattach explicit pitch/staff/voice corrections by stable source IDs."""
    ops = normalize_corrections(corrections)
    if not ops:
        return list(events)
    from mir.types import Hand

    present = {ev.note_id for ev in events}
    original = {n.note_id: n for n in snapshot.notes}
    missing = []
    by_source = {}
    for op in ops:
        sid = op["source_note_id"]
        by_source[sid] = op
        if sid not in present or sid not in original:
            missing.append(sid)
    if missing:
        raise NotationEditConflict(missing)
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
        if op.get("voice") is not None and int(op["voice"]) != int(ev.voice):
            changes["voice"] = int(op["voice"])
            changes["voice_assigned"] = True
            changes["voice_provenance"] = "user_edit"
        out.append(copy_event(ev, **changes) if changes else ev)
    return out


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
    for index, ev in enumerate(events):
        note_id = str(ev.note_id or f"n-{index:04d}")
        track = 1 if getattr(ev.hand, "value", "") == "left" else 0
        notes.append(
            {
                "id": note_id if ID_RE.match(note_id) else f"n-{index:04d}",
                "source_note_id": ev.note_id if ID_RE.match(str(ev.note_id or "")) else None,
                "pitch": max(PITCH_MIN, min(PITCH_MAX, int(ev.pitch))),
                "start": max(0.0, float(ev.start_beat)),
                "duration": min(MAX_DURATION, max(1e-6, float(ev.duration_beats))),
                "velocity": max(1, min(127, int(ev.velocity or 64))),
                "track": track,
                "voice": int(getattr(ev, "voice", 0) or 0),
                "start_sec": getattr(ev, "start_time_sec", None),
                "end_sec": getattr(ev, "end_time_sec", None),
            }
        )
    notes = assign_overlap_voices(notes) if all(int(n.get("voice") or 0) == 0 for n in notes) else notes
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
    events = _layout_from_decisions(events, layout_rows)
    applied_corrections = corrections if corrections is not None else edits
    events = apply_note_edits(events, applied_corrections, performance)
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
    import tempfile as _tf

    with _tf.TemporaryDirectory() as tmp:
        path = Path(tmp) / "score.musicxml"
        midi_path = Path(tmp) / "score.mid"
        writer._export_musicxml(score, path)
        xml = path.read_text(encoding="utf-8")
        playback_score = writer._score_for_playback(score, meta)
        playback_score.write("midi", fp=str(midi_path))
        score_midi = midi_path.read_bytes()
    if [n.note_id for n in notes] != source_ids:
        raise ValueError("Notation regen mutated source note IDs")
    performance.verify_midi(midi_bytes)
    decisions = list(writer.last_quantization_decisions or [])
    summary = dict(writer.last_quantization_summary or {})
    policy_exceptions = [
        public_policy_exception(row) for row in (summary.get("policy_exceptions") or [])
    ]
    quantized = list(writer.last_quantized_events or events)
    editor_model = editor_model_from_events(
        quantized,
        tempo_bpm=float(display or 120),
        time_signature=str(meter_hint or "4/4"),
        printed_marks=printed,
        time_map=mapper if hasattr(mapper, "interval_bpms") else (
            context.time_map if context is not None else None
        ),
    )
    edits_digest = _edits_digest(applied_corrections)
    context_digest = context.identity_digest() if context is not None else None
    cache = settings.cache_key(
        digest, context_digest=context_digest, edits_digest=edits_digest
    )
    next_context = context
    if context is not None:
        accepted = tuple(n.note_id for n in notes)
        next_payload = {
            **context.to_dict(),
            "accepted_source_note_ids": list(accepted),
            "has_recorded_selection": True,
            "layout_decisions": decisions,
            "midi_sha256": digest,
            "fallback": used_fallback,
            "score_beat_offset": float(summary.get("score_beat_offset", context.score_beat_offset) or 0.0),
        }
        if settings.pickup_beats is not None:
            next_payload["pickup_beats"] = settings.pickup_beats
        if settings.first_downbeat_beat is not None:
            next_payload["first_downbeat_beat"] = settings.first_downbeat_beat
        next_context = InterpretationContext.from_dict(next_payload)
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
                    result.context.identity_digest() if result.context else None
                ),
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
