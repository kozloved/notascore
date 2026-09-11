"""Deterministic fusion of parallel transcriptions. Never duplicates matches."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from engine.ir import NoteEvidence
from mir.types import NoteEvent

EPS = 1e-9


@dataclass
class FusedNote:
    note: NoteEvent
    evidence: list[NoteEvidence] = field(default_factory=list)
    canonical_backend: str = ""
    dropped_ghost: bool = False


@dataclass
class ReconciliationResult:
    notes: list[NoteEvent]
    fused: list[FusedNote]
    unmatched_global: list[NoteEvent]
    unmatched_specialist: list[NoteEvent]
    dropped_ghosts: list[NoteEvent]


def _onset(note: NoteEvent) -> float:
    return float(note.start_time)


def _offset(note: NoteEvent) -> float:
    return float(note.end_time)


def reconcile_transcriptions(
    global_notes: list[NoteEvent],
    specialist_notes: list[NoteEvent],
    *,
    onset_window: float = 0.05,
    specialist_backend: str = "transkun",
    global_backend: str = "mt3",
    ghost_confidence: float = 0.35,
    specialist_win_confidence: float = 0.6,
) -> ReconciliationResult:
    """Bipartite greedy match on pitch + onset.

    Specialist wins timing when confident. Unmatched full-mix notes are kept
    (separation can drop real music). Weak unmatched specialist notes are
    ghosts and do not become canonical notes.
    """
    used_spec: set[int] = set()
    fused: list[FusedNote] = []
    unmatched_global: list[NoteEvent] = []

    spec_index = list(enumerate(specialist_notes))
    for g in global_notes:
        candidates = []
        for i, s in spec_index:
            if i in used_spec or int(s.pitch) != int(g.pitch):
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
                    evidence=[_evidence(global_backend, g)],
                    canonical_backend=global_backend,
                )
            )
            continue
        candidates.sort()
        _, _, _, idx, s = candidates[0]
        used_spec.add(idx)
        specialist_conf = float(s.confidence)
        use_specialist = specialist_conf >= specialist_win_confidence
        chosen = s if use_specialist else g
        canonical = replace(
            chosen,
            note_id=g.note_id or s.note_id,
            source_backend=f"{global_backend}+{specialist_backend}",
        )
        fused.append(
            FusedNote(
                note=canonical,
                evidence=[_evidence(global_backend, g), _evidence(specialist_backend, s)],
                canonical_backend=specialist_backend if use_specialist else global_backend,
            )
        )

    unmatched_specialist: list[NoteEvent] = []
    dropped_ghosts: list[NoteEvent] = []
    for i, s in spec_index:
        if i in used_spec:
            continue
        duplicate_of = None
        for item in fused:
            if int(item.note.pitch) != int(s.pitch):
                continue
            if abs(_onset(item.note) - _onset(s)) <= onset_window:
                duplicate_of = item
                break
        if duplicate_of is not None:
            duplicate_of.evidence.append(_evidence(specialist_backend, s))
            continue
        if float(s.confidence) < ghost_confidence:
            dropped_ghosts.append(s)
            continue
        unmatched_specialist.append(s)
        fused.append(
            FusedNote(
                note=s,
                evidence=[_evidence(specialist_backend, s)],
                canonical_backend=specialist_backend,
            )
        )

    fused.sort(key=lambda item: (_onset(item.note), item.note.pitch))
    return ReconciliationResult(
        notes=[item.note for item in fused],
        fused=fused,
        unmatched_global=unmatched_global,
        unmatched_specialist=unmatched_specialist,
        dropped_ghosts=dropped_ghosts,
    )


def _evidence(backend: str, note: NoteEvent) -> NoteEvidence:
    return NoteEvidence(
        backend=backend,
        onset_sec=_onset(note),
        offset_sec=_offset(note),
        confidence=float(note.confidence),
        pitch=int(note.pitch),
    )
