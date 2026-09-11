"""Deterministic fusion of parallel transcriptions. Never duplicates matches."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from engine.ir import NoteEvidence
from mir.types import InstrumentKind, NoteEvent

EPS = 1e-9
FULL_MIX_SOURCE = "full_mix"


@dataclass
class FusedNote:
    note: NoteEvent
    evidence: list[NoteEvidence] = field(default_factory=list)
    canonical_backend: str = ""
    dropped_ghost: bool = False
    instrument: str = ""
    instrument_confidence: float = 0.0


@dataclass
class ReconciliationResult:
    notes: list[NoteEvent]
    fused: list[FusedNote]
    unmatched_global: list[NoteEvent]
    unmatched_specialist: list[NoteEvent]
    dropped_ghosts: list[NoteEvent]
    diagnostics: dict = field(default_factory=dict)


def _onset(note: NoteEvent) -> float:
    return float(note.start_time)


def _offset(note: NoteEvent) -> float:
    return float(note.end_time)


def _instrument(note: NoteEvent) -> str:
    inst = getattr(note, "instrument", None)
    if inst is None:
        return InstrumentKind.UNKNOWN.value
    return inst.value if hasattr(inst, "value") else str(inst or InstrumentKind.UNKNOWN.value)


def _stem_id(note: NoteEvent) -> str:
    return str(getattr(note, "source_track_id", "") or "")


def _backend(note: NoteEvent, default: str) -> str:
    raw = str(getattr(note, "source_backend", "") or "")
    return raw if raw and raw != "unknown" else default


def instruments_compatible(left: str, right: str) -> bool:
    """Same-pitch events from different instruments stay distinct.

    Unlabeled (unknown) evidence may pair with a labeled stem so the stem can
    identify the mix note. Two concrete instruments never merge.
    """
    a = (left or InstrumentKind.UNKNOWN.value).lower()
    b = (right or InstrumentKind.UNKNOWN.value).lower()
    if a == b:
        return True
    unknown = InstrumentKind.UNKNOWN.value
    if a == unknown or b == unknown:
        return True
    return False


def _evidence(backend: str, note: NoteEvent, *, source: str = "") -> NoteEvidence:
    stem = _stem_id(note)
    src = source or stem or FULL_MIX_SOURCE
    return NoteEvidence(
        backend=backend,
        onset_sec=_onset(note),
        offset_sec=_offset(note),
        confidence=float(note.confidence),
        stem_id=stem if stem != FULL_MIX_SOURCE else "",
        pitch=int(note.pitch),
        velocity=int(note.velocity),
        instrument=_instrument(note),
        source=src,
    )


def _evidence_key(ev: NoteEvidence) -> tuple[str, str]:
    return (ev.backend, ev.stem_id or ev.source or "")


def reconcile_transcriptions(
    global_notes: list[NoteEvent],
    specialist_notes: list[NoteEvent],
    *,
    onset_window: float = 0.05,
    specialist_backend: str = "transkun",
    global_backend: str = "mt3",
    ghost_confidence: float = 0.35,
    specialist_win_confidence: float = 0.6,
    keep_global_timing: bool = True,
    stem_only_min_confidence: float | None = None,
    specialist_may_replace_timing: bool | None = None,
) -> ReconciliationResult:
    """Bipartite greedy match on pitch + onset + instrument/stem identity.

    Full-mix notes are the anchor: unmatched mix events are kept (separation
    can drop real music). Matching stem evidence enriches instrument identity
    and provenance without replacing mix timing by default.

    Weak unmatched stem notes are ghosts (diagnostics only). Strong unmatched
    stem notes may become derived candidates when they pass the confidence gate.
    """
    if specialist_may_replace_timing is None:
        specialist_may_replace_timing = not keep_global_timing
    if stem_only_min_confidence is None:
        stem_only_min_confidence = specialist_win_confidence

    used_spec: set[int] = set()
    fused: list[FusedNote] = []
    unmatched_global: list[NoteEvent] = []

    spec_index = list(enumerate(specialist_notes))
    for g in global_notes:
        g_backend = _backend(g, global_backend)
        g_inst = _instrument(g)
        candidates = []
        for i, s in spec_index:
            if i in used_spec or int(s.pitch) != int(g.pitch):
                continue
            if not instruments_compatible(g_inst, _instrument(s)):
                continue
            dist = abs(_onset(s) - _onset(g))
            if dist <= onset_window:
                dur_g = max(_offset(g) - _onset(g), EPS)
                dur_s = max(_offset(s) - _onset(s), EPS)
                dur_err = abs(dur_g - dur_s) / max(dur_g, dur_s)
                candidates.append((dist, dur_err, abs(_offset(s) - _offset(g)), i, s))
        if not candidates:
            unmatched_global.append(g)
            fused.append(
                FusedNote(
                    note=g,
                    evidence=[_evidence(g_backend, g, source=FULL_MIX_SOURCE)],
                    canonical_backend=g_backend,
                    instrument=g_inst,
                    instrument_confidence=float(g.confidence),
                )
            )
            continue
        candidates.sort()
        _, _, _, idx, s = candidates[0]
        used_spec.add(idx)
        s_backend = _backend(s, specialist_backend)
        specialist_conf = float(s.confidence)
        use_specialist_timing = (
            specialist_may_replace_timing and specialist_conf >= specialist_win_confidence
        )
        chosen = s if use_specialist_timing else g
        fused_inst = g_inst
        inst_conf = float(g.confidence)
        s_inst = _instrument(s)
        if s_inst != InstrumentKind.UNKNOWN.value and (
            fused_inst == InstrumentKind.UNKNOWN.value or s_inst == fused_inst
        ):
            fused_inst = s_inst
            inst_conf = max(float(g.confidence), specialist_conf)
        canonical = replace(
            chosen,
            note_id=g.note_id or s.note_id,
            start_time=_onset(g) if not use_specialist_timing else _onset(chosen),
            end_time=_offset(g) if not use_specialist_timing else _offset(chosen),
            pitch=int(g.pitch),
            velocity=int(g.velocity) if not use_specialist_timing else int(chosen.velocity),
            original_start_time=g.original_start_time,
            original_end_time=g.original_end_time,
            source_backend=f"{g_backend}+{s_backend}",
            instrument=_as_instrument(fused_inst, g.instrument),
            confidence=max(float(g.confidence), specialist_conf),
        )
        fused.append(
            FusedNote(
                note=canonical,
                evidence=[
                    _evidence(g_backend, g, source=FULL_MIX_SOURCE),
                    _evidence(s_backend, s, source=_stem_id(s) or s_inst),
                ],
                canonical_backend=s_backend if use_specialist_timing else g_backend,
                instrument=fused_inst,
                instrument_confidence=inst_conf,
            )
        )

    unmatched_specialist: list[NoteEvent] = []
    dropped_ghosts: list[NoteEvent] = []
    for i, s in spec_index:
        if i in used_spec:
            continue
        s_backend = _backend(s, specialist_backend)
        s_inst = _instrument(s)
        s_stem = _stem_id(s)
        duplicate_of = None
        for item in fused:
            if int(item.note.pitch) != int(s.pitch):
                continue
            if not instruments_compatible(item.instrument or _instrument(item.note), s_inst):
                continue
            if abs(_onset(item.note) - _onset(s)) > onset_window:
                continue
            already = {_evidence_key(ev) for ev in item.evidence}
            if (s_backend, s_stem or s_inst) in already:
                # Same stem already contributed — this is a later attack, not extra evidence.
                continue
            duplicate_of = item
            break
        if duplicate_of is not None:
            duplicate_of.evidence.append(
                _evidence(s_backend, s, source=s_stem or s_inst)
            )
            continue
        if float(s.confidence) < max(ghost_confidence, stem_only_min_confidence):
            dropped_ghosts.append(s)
            continue
        unmatched_specialist.append(s)
        fused.append(
            FusedNote(
                note=s,
                evidence=[_evidence(s_backend, s, source=s_stem or s_inst)],
                canonical_backend=s_backend,
                instrument=s_inst,
                instrument_confidence=float(s.confidence),
            )
        )

    fused.sort(key=lambda item: (_onset(item.note), item.note.pitch, item.instrument))
    return ReconciliationResult(
        notes=[item.note for item in fused],
        fused=fused,
        unmatched_global=unmatched_global,
        unmatched_specialist=unmatched_specialist,
        dropped_ghosts=dropped_ghosts,
        diagnostics={
            "dropped_ghosts": [_note_debug(n) for n in dropped_ghosts],
            "unmatched_global": [_note_debug(n) for n in unmatched_global],
            "unmatched_specialist": [_note_debug(n) for n in unmatched_specialist],
            "keep_global_timing": not specialist_may_replace_timing,
            "stem_only_min_confidence": stem_only_min_confidence,
            "ghost_confidence": ghost_confidence,
        },
    )


def _as_instrument(name: str, current):
    if isinstance(current, InstrumentKind) and (
        current == InstrumentKind.UNKNOWN or current.value == name
    ):
        try:
            return InstrumentKind(name)
        except ValueError:
            return current
    try:
        return InstrumentKind(name)
    except ValueError:
        return current


def _note_debug(note: NoteEvent) -> dict:
    return {
        "note_id": note.note_id,
        "pitch": int(note.pitch),
        "onset_seconds": _onset(note),
        "offset_seconds": _offset(note),
        "velocity": int(note.velocity),
        "confidence": float(note.confidence),
        "backend": note.source_backend,
        "stem_id": _stem_id(note),
        "instrument": _instrument(note),
    }
