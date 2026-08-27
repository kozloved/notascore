"""Robust note classification for Checkpoint 8 forensics.

Matching strategy (documented):
1. Build a bipartite cost matrix over reference × predicted notes.
2. Cost is onset distance (seconds) plus a pitch penalty (semitones × weight).
   Pairs with onset distance above ``assign_window_sec`` are forbidden.
3. Solve one-to-one optimal assignment with the Hungarian algorithm
   (``scipy.optimize.linear_sum_assignment``).
4. Classify each assigned pair using musical tolerances:
   - MATCH: pitch within tolerance AND onset within onset_tol AND offset within
     offset_tol (offset checked as secondary label OFFSET_ERROR when onset+pitch OK)
   - ONSET_ERROR: pitch OK, onset outside onset_tol but inside assign window
   - PITCH_ERROR / PITCH_CONFUSION: onset within a pitch-confusion window,
     pitch outside tolerance
   - EARLY / LATE: pitch OK, onset outside onset_tol (signed)
5. Unassigned references: search for one-to-many same-pitch overlaps → FRAGMENTED;
   else MISSED. Multiple refs covered by one pred → MERGED (ref side).
6. Unassigned predictions: same-pitch overlap with an explained ref → DUPLICATE
   or EXTRA_FRAGMENT; else SPURIOUS.

This is diagnostic-only and does not alter production F1 matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from evaluation.defaults import OFFSET_TOLERANCE_SEC, ONSET_TOLERANCE_SEC
from evaluation.forensics.taxonomy import (
    PRED_DUPLICATE,
    PRED_EARLY,
    PRED_EXTRA_FRAGMENT,
    PRED_LATE,
    PRED_MATCH,
    PRED_PITCH_CONFUSION,
    PRED_SPURIOUS,
    REF_FRAGMENTED,
    REF_MATCH,
    REF_MERGED,
    REF_MISSED,
    REF_OFFSET_ERROR,
    REF_ONSET_ERROR,
    REF_PITCH_ERROR,
    NoteErrorRow,
    TaxonomySummary,
    midi_note_name,
)
from mir.types import NoteEvent

# Assignment window is intentionally wider than F1 onset tolerance so we can
# separate "near miss timing" from "completely unrelated" notes.
DEFAULT_ASSIGN_WINDOW_SEC = 0.35
DEFAULT_PITCH_CONFUSION_WINDOW_SEC = 0.15
DEFAULT_PITCH_PENALTY = 0.08  # seconds of cost per semitone
DEFAULT_FRAGMENT_OVERLAP_RATIO = 0.25


def matching_strategy_doc() -> str:
    return __doc__ or ""


@dataclass
class ClassificationResult:
    stage: str
    rows: list[NoteErrorRow] = field(default_factory=list)
    summary: TaxonomySummary | None = None
    pairs: list[dict[str, Any]] = field(default_factory=list)
    # Indices for MIDI export
    match_pred_indices: list[int] = field(default_factory=list)
    match_ref_indices: list[int] = field(default_factory=list)
    fn_ref_indices: list[int] = field(default_factory=list)
    fp_pred_indices: list[int] = field(default_factory=list)
    pitch_error_pairs: list[tuple[int, int]] = field(default_factory=list)
    timing_error_pairs: list[tuple[int, int]] = field(default_factory=list)
    fragmented_ref_indices: list[int] = field(default_factory=list)
    duplicate_pred_indices: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "summary": self.summary.to_dict() if self.summary else None,
            "pairs": self.pairs,
            "row_count": len(self.rows),
            "matching_strategy": "hungarian_onset_cost_plus_pitch_penalty",
        }


def _dur(n: NoteEvent) -> float:
    return max(0.0, float(n.end_time) - float(n.start_time))


def _overlap(a: NoteEvent, b: NoteEvent) -> float:
    start = max(float(a.start_time), float(b.start_time))
    end = min(float(a.end_time), float(b.end_time))
    return max(0.0, end - start)


def _local_polyphony(notes: Sequence[NoteEvent], index: int) -> int:
    n = notes[index]
    t = float(n.start_time) + 1e-6
    return sum(
        1
        for o in notes
        if float(o.start_time) - 1e-9 <= t <= float(o.end_time) + 1e-9
    )


def _nearest_onset_ms(
    notes: Sequence[NoteEvent], time_sec: float, *, skip: int | None = None
) -> float | None:
    best = None
    for i, n in enumerate(notes):
        if skip is not None and i == skip:
            continue
        d = abs(float(n.start_time) - time_sec) * 1000.0
        if best is None or d < best:
            best = d
    return best


def classify_notes(
    reference: Sequence[NoteEvent],
    predicted: Sequence[NoteEvent],
    *,
    stage: str,
    case_id: str = "",
    onset_tolerance_sec: float = ONSET_TOLERANCE_SEC,
    offset_tolerance_sec: float = OFFSET_TOLERANCE_SEC,
    pitch_tolerance: int = 0,
    assign_window_sec: float = DEFAULT_ASSIGN_WINDOW_SEC,
    pitch_confusion_window_sec: float = DEFAULT_PITCH_CONFUSION_WINDOW_SEC,
    pitch_penalty: float = DEFAULT_PITCH_PENALTY,
    reference_tempo: float | None = None,
    predicted_tempo: float | None = None,
) -> ClassificationResult:
    """Classify reference and predicted notes with optimal 1-1 matching."""
    refs = list(reference)
    preds = list(predicted)
    n_r, n_p = len(refs), len(preds)
    result = ClassificationResult(stage=stage)

    if n_r == 0 and n_p == 0:
        result.summary = TaxonomySummary(
            stage=stage, reference_count=0, predicted_count=0
        )
        return result

    # Cost matrix (pad to square for clarity; scipy handles rectangular)
    LARGE = 1e6
    cost = np.full((n_r, n_p), LARGE, dtype=float)
    for i, ref in enumerate(refs):
        for j, pred in enumerate(preds):
            dt = abs(float(pred.start_time) - float(ref.start_time))
            if dt > assign_window_sec:
                continue
            dpitch = abs(int(pred.pitch) - int(ref.pitch))
            cost[i, j] = dt + pitch_penalty * float(dpitch)

    assigned_ref: dict[int, int] = {}
    assigned_pred: dict[int, int] = {}
    if n_r and n_p:
        ri, pj = linear_sum_assignment(cost)
        for i, j in zip(ri.tolist(), pj.tolist()):
            if cost[i, j] >= LARGE / 2:
                continue
            assigned_ref[i] = j
            assigned_pred[j] = i

    used_ref: set[int] = set()
    used_pred: set[int] = set()
    ref_class: dict[int, str] = {}
    pred_class: dict[int, str] = {}
    pair_meta: dict[tuple[int, int], dict[str, Any]] = {}

    for i, j in assigned_ref.items():
        ref, pred = refs[i], preds[j]
        dt = float(pred.start_time) - float(ref.start_time)
        abs_dt = abs(dt)
        dpitch = abs(int(pred.pitch) - int(ref.pitch))
        doff = abs(float(pred.end_time) - float(ref.end_time))
        pitch_ok = dpitch <= pitch_tolerance
        onset_ok = abs_dt <= onset_tolerance_sec
        offset_ok = doff <= offset_tolerance_sec

        r_label = REF_MISSED
        p_label = PRED_SPURIOUS
        reason = ""

        if pitch_ok and onset_ok:
            if offset_ok:
                r_label, p_label = REF_MATCH, PRED_MATCH
                reason = "onset+pitch+offset within tolerance"
            else:
                r_label, p_label = REF_OFFSET_ERROR, PRED_MATCH
                reason = (
                    f"onset+pitch OK; offset error {doff * 1000:.1f} ms "
                    f"(tol {offset_tolerance_sec * 1000:.0f} ms)"
                )
                result.timing_error_pairs.append((i, j))
        elif pitch_ok and not onset_ok:
            r_label = REF_ONSET_ERROR
            p_label = PRED_EARLY if dt < 0 else PRED_LATE
            reason = f"pitch OK; onset error {dt * 1000:.1f} ms"
            result.timing_error_pairs.append((i, j))
        elif (not pitch_ok) and abs_dt <= pitch_confusion_window_sec:
            r_label = REF_PITCH_ERROR
            p_label = PRED_PITCH_CONFUSION
            reason = f"onset near ({abs_dt * 1000:.1f} ms); pitch Δ={dpitch}"
            result.pitch_error_pairs.append((i, j))
        elif (not pitch_ok) and abs_dt <= onset_tolerance_sec:
            r_label = REF_PITCH_ERROR
            p_label = PRED_PITCH_CONFUSION
            reason = f"onset within F1 tol; pitch Δ={dpitch}"
            result.pitch_error_pairs.append((i, j))
        else:
            # Assignment exists but too weak for a semantic link — treat as
            # unmatched for taxonomy (will fall through to fragment/miss logic).
            continue

        used_ref.add(i)
        used_pred.add(j)
        ref_class[i] = r_label
        pred_class[j] = p_label
        pair_meta[(i, j)] = {
            "onset_error_ms": dt * 1000.0,
            "offset_error_ms": (
                (float(pred.end_time) - float(ref.end_time)) * 1000.0
            ),
            "duration_error_ms": (_dur(pred) - _dur(ref)) * 1000.0,
            "pitch_error_semitones": int(pred.pitch) - int(ref.pitch),
            "reason": reason,
            "ref_class": r_label,
            "pred_class": p_label,
        }
        if r_label in (REF_MATCH, REF_OFFSET_ERROR):
            result.match_pred_indices.append(j)
            result.match_ref_indices.append(i)

    def _same_pitch_cover_preds(ref_i: int) -> list[int]:
        ref = refs[ref_i]
        hits: list[int] = []
        for j, pred in enumerate(preds):
            if abs(int(pred.pitch) - int(ref.pitch)) > pitch_tolerance:
                continue
            ov = _overlap(ref, pred)
            near = abs(float(pred.start_time) - float(ref.start_time)) <= assign_window_sec
            if ov / max(_dur(ref), 1e-6) >= DEFAULT_FRAGMENT_OVERLAP_RATIO or (
                near and ov > 0
            ) or (
                near and _dur(pred) <= _dur(ref) * 0.75
            ):
                hits.append(j)
        return hits

    def _same_pitch_cover_refs(pred_j: int) -> list[int]:
        pred = preds[pred_j]
        hits: list[int] = []
        for i, ref in enumerate(refs):
            if abs(int(pred.pitch) - int(ref.pitch)) > pitch_tolerance:
                continue
            ov = _overlap(ref, pred)
            near = abs(float(pred.start_time) - float(ref.start_time)) <= assign_window_sec
            if ov / max(_dur(ref), 1e-6) >= DEFAULT_FRAGMENT_OVERLAP_RATIO or (
                near and ov > 0
            ):
                hits.append(i)
        return hits

    # Fragmentation may override a weak 1-1 OFFSET_ERROR/MATCH when ≥2 fragments exist
    for i, ref in enumerate(refs):
        fragments = _same_pitch_cover_preds(i)
        if len(fragments) < 2:
            continue
        # Require that fragments collectively look like splits (short pieces)
        shortish = sum(1 for j in fragments if _dur(preds[j]) < _dur(ref) * 0.85)
        if shortish < 2 and ref_class.get(i) in (REF_MATCH,):
            continue
        # Clear previous assignment labels for this ref / its fragments
        if i in assigned_ref:
            old_j = assigned_ref[i]
            pair_meta.pop((i, old_j), None)
            if old_j in result.match_pred_indices:
                result.match_pred_indices = [x for x in result.match_pred_indices if x != old_j]
            if i in result.match_ref_indices:
                result.match_ref_indices = [x for x in result.match_ref_indices if x != i]
            result.timing_error_pairs = [
                (a, b) for a, b in result.timing_error_pairs if a != i
            ]
        ref_class[i] = REF_FRAGMENTED
        used_ref.add(i)
        if i not in result.fragmented_ref_indices:
            result.fragmented_ref_indices.append(i)
        for j in fragments:
            pred_class[j] = PRED_EXTRA_FRAGMENT
            used_pred.add(j)
            if j not in result.duplicate_pred_indices:
                result.duplicate_pred_indices.append(j)

    # Merged: one pred covers ≥2 refs (may override a single OFFSET_ERROR assignment)
    for j, pred in enumerate(preds):
        covered = _same_pitch_cover_refs(j)
        if len(covered) < 2:
            continue
        # Prefer merge when pred duration spans multiple refs
        if _dur(pred) < sum(_dur(refs[i]) for i in covered) * 0.5:
            continue
        for i in covered:
            if i in assigned_ref and assigned_ref[i] != j:
                continue
            if i in assigned_ref:
                pair_meta.pop((i, j), None)
                result.timing_error_pairs = [
                    (a, b) for a, b in result.timing_error_pairs if not (a == i and b == j)
                ]
                if i in result.match_ref_indices:
                    result.match_ref_indices = [x for x in result.match_ref_indices if x != i]
                if j in result.match_pred_indices:
                    result.match_pred_indices = [x for x in result.match_pred_indices if x != j]
            ref_class[i] = REF_MERGED
            used_ref.add(i)
        pred_class[j] = PRED_MATCH
        used_pred.add(j)

    # Duplicates: unmatched pred near an already-matched same-pitch ref
    for j, pred in enumerate(preds):
        if j in used_pred:
            continue
        for i in result.match_ref_indices:
            ref = refs[i]
            if abs(int(pred.pitch) - int(ref.pitch)) > pitch_tolerance:
                continue
            if abs(float(pred.start_time) - float(ref.start_time)) <= assign_window_sec:
                pred_class[j] = PRED_DUPLICATE
                used_pred.add(j)
                result.duplicate_pred_indices.append(j)
                break
            if _overlap(ref, pred) > 0:
                pred_class[j] = PRED_EXTRA_FRAGMENT
                used_pred.add(j)
                result.duplicate_pred_indices.append(j)
                break

    # Remaining unmatched
    for i in range(n_r):
        if i not in used_ref:
            ref_class[i] = REF_MISSED
            result.fn_ref_indices.append(i)
    for j in range(n_p):
        if j not in used_pred:
            pred_class[j] = PRED_SPURIOUS
            result.fp_pred_indices.append(j)

    # Also treat pitch/onset errors as FN/FP-ish for export buckets
    for i, label in ref_class.items():
        if label in (REF_MISSED, REF_PITCH_ERROR, REF_ONSET_ERROR, REF_FRAGMENTED):
            if i not in result.fn_ref_indices and label == REF_MISSED:
                pass
        if label == REF_MISSED and i not in result.fn_ref_indices:
            result.fn_ref_indices.append(i)
    for j, label in pred_class.items():
        if label == PRED_SPURIOUS and j not in result.fp_pred_indices:
            result.fp_pred_indices.append(j)

    # Build rows
    rows: list[NoteErrorRow] = []
    for (i, j), meta in pair_meta.items():
        ref, pred = refs[i], preds[j]
        rows.append(
            NoteErrorRow(
                case_id=case_id,
                stage=stage,
                side="pair",
                classification=meta["ref_class"],
                reference_index=i,
                predicted_index=j,
                reference_pitch=int(ref.pitch),
                reference_note_name=midi_note_name(ref.pitch),
                reference_onset=float(ref.start_time),
                reference_offset=float(ref.end_time),
                reference_duration=_dur(ref),
                predicted_pitch=int(pred.pitch),
                predicted_note_name=midi_note_name(pred.pitch),
                predicted_onset=float(pred.start_time),
                predicted_offset=float(pred.end_time),
                predicted_duration=_dur(pred),
                pitch_error_semitones=meta["pitch_error_semitones"],
                onset_error_ms=meta["onset_error_ms"],
                offset_error_ms=meta["offset_error_ms"],
                duration_error_ms=meta["duration_error_ms"],
                velocity_reference=int(ref.velocity),
                velocity_predicted=int(pred.velocity),
                local_polyphony=_local_polyphony(refs, i),
                reference_tempo=reference_tempo,
                predicted_tempo=predicted_tempo,
                nearest_reference_distance_ms=_nearest_onset_ms(
                    refs, float(pred.start_time), skip=i
                ),
                nearest_predicted_distance_ms=_nearest_onset_ms(
                    preds, float(ref.start_time), skip=j
                ),
                confidence=float(pred.confidence) if pred.confidence is not None else None,
                reason=meta["reason"],
            )
        )
        result.pairs.append({"ref": i, "pred": j, **meta})

    for i, label in ref_class.items():
        if any(r.reference_index == i and r.side == "pair" for r in rows):
            continue
        ref = refs[i]
        rows.append(
            NoteErrorRow(
                case_id=case_id,
                stage=stage,
                side="reference",
                classification=label,
                reference_index=i,
                reference_pitch=int(ref.pitch),
                reference_note_name=midi_note_name(ref.pitch),
                reference_onset=float(ref.start_time),
                reference_offset=float(ref.end_time),
                reference_duration=_dur(ref),
                velocity_reference=int(ref.velocity),
                local_polyphony=_local_polyphony(refs, i),
                reference_tempo=reference_tempo,
                predicted_tempo=predicted_tempo,
                nearest_predicted_distance_ms=_nearest_onset_ms(
                    preds, float(ref.start_time)
                ),
                reason=f"reference classified as {label}",
            )
        )

    for j, label in pred_class.items():
        if any(r.predicted_index == j and r.side == "pair" for r in rows):
            # Still add predicted-side label when pair used ref classification
            if label in (PRED_MATCH, PRED_EARLY, PRED_LATE, PRED_PITCH_CONFUSION):
                continue
        if any(r.predicted_index == j and r.side == "predicted" for r in rows):
            continue
        if any(
            r.predicted_index == j and r.side == "pair" and r.classification
            for r in rows
        ):
            # Pair already recorded; skip duplicate predicted row for matches
            if j in assigned_pred and assigned_pred[j] in used_ref:
                if pred_class.get(j) in (PRED_MATCH, PRED_EARLY, PRED_LATE, PRED_PITCH_CONFUSION):
                    continue
        pred = preds[j]
        if label in (PRED_MATCH, PRED_EARLY, PRED_LATE, PRED_PITCH_CONFUSION) and j in assigned_pred:
            continue
        rows.append(
            NoteErrorRow(
                case_id=case_id,
                stage=stage,
                side="predicted",
                classification=label,
                predicted_index=j,
                predicted_pitch=int(pred.pitch),
                predicted_note_name=midi_note_name(pred.pitch),
                predicted_onset=float(pred.start_time),
                predicted_offset=float(pred.end_time),
                predicted_duration=_dur(pred),
                velocity_predicted=int(pred.velocity),
                local_polyphony=_local_polyphony(preds, j),
                reference_tempo=reference_tempo,
                predicted_tempo=predicted_tempo,
                nearest_reference_distance_ms=_nearest_onset_ms(
                    refs, float(pred.start_time)
                ),
                confidence=float(pred.confidence) if pred.confidence is not None else None,
                reason=f"predicted classified as {label}",
            )
        )

    result.rows = rows

    def _count(mapping: dict[int, str], labels: tuple[str, ...]) -> dict[str, int]:
        out = {lab: 0 for lab in labels}
        for lab in mapping.values():
            out[lab] = out.get(lab, 0) + 1
        return out

    from evaluation.forensics.taxonomy import PRED_CLASSES, REF_CLASSES

    rc = _count(ref_class, REF_CLASSES)
    pc = _count(pred_class, PRED_CLASSES)
    matched = rc.get(REF_MATCH, 0) + rc.get(REF_OFFSET_ERROR, 0)
    result.summary = TaxonomySummary(
        stage=stage,
        reference_count=n_r,
        predicted_count=n_p,
        reference_classes=rc,
        predicted_classes=pc,
        matched_pairs=matched,
        false_positives=pc.get(PRED_SPURIOUS, 0),
        false_negatives=rc.get(REF_MISSED, 0),
        pitch_errors=rc.get(REF_PITCH_ERROR, 0),
        onset_errors=rc.get(REF_ONSET_ERROR, 0),
        offset_errors=rc.get(REF_OFFSET_ERROR, 0),
        fragmented=rc.get(REF_FRAGMENTED, 0),
        merged=rc.get(REF_MERGED, 0),
        duplicates=pc.get(PRED_DUPLICATE, 0) + pc.get(PRED_EXTRA_FRAGMENT, 0),
    )
    return result
