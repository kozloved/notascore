"""Cleaner impact forensics — beneficial vs harmful removals."""

from __future__ import annotations

from typing import Any, Sequence

from evaluation.forensics.classify import classify_notes
from evaluation.matching import match_notes
from mir.types import NoteEvent


def _matched_pred_indices(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = 0.05,
    pitch_tolerance: int = 0,
) -> set[int]:
    matched: set[int] = set()
    used: set[int] = set()
    for ref in reference:
        best_pi = None
        best_dt = float("inf")
        for pi, pred in enumerate(predicted):
            if pi in used:
                continue
            if abs(int(pred.pitch) - int(ref.pitch)) > pitch_tolerance:
                continue
            dt = abs(float(pred.start_time) - float(ref.start_time))
            if dt <= onset_tolerance_sec and dt < best_dt:
                best_dt = dt
                best_pi = pi
        if best_pi is not None:
            used.add(best_pi)
            matched.add(best_pi)
    return matched


def _find_removed_notes(
    before: Sequence[NoteEvent],
    after: Sequence[NoteEvent],
    *,
    onset_tol: float = 0.02,
    pitch_tol: int = 0,
) -> list[int]:
    """Indices in ``before`` that have no counterpart in ``after``."""
    used_after: set[int] = set()
    kept: set[int] = set()
    for bi, b in enumerate(before):
        best = None
        best_dt = float("inf")
        for ai, a in enumerate(after):
            if ai in used_after:
                continue
            if abs(int(a.pitch) - int(b.pitch)) > pitch_tol:
                continue
            dt = abs(float(a.start_time) - float(b.start_time))
            if dt <= onset_tol and dt < best_dt:
                best_dt = dt
                best = ai
        if best is not None:
            used_after.add(best)
            kept.add(bi)
    return [i for i in range(len(before)) if i not in kept]


def cleaner_impact(
    reference: Sequence[NoteEvent],
    before: Sequence[NoteEvent],
    after: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = 0.05,
    pitch_tolerance: int = 0,
) -> dict[str, Any]:
    """Quantify whether Cleaner helps or hurts vs reference_raw."""
    m_before = match_notes(
        before, reference, onset_tolerance_sec=onset_tolerance_sec, pitch_tolerance=pitch_tolerance
    )
    m_after = match_notes(
        after, reference, onset_tolerance_sec=onset_tolerance_sec, pitch_tolerance=pitch_tolerance
    )
    correct_before = _matched_pred_indices(
        before, reference, onset_tolerance_sec=onset_tolerance_sec, pitch_tolerance=pitch_tolerance
    )
    correct_after = _matched_pred_indices(
        after, reference, onset_tolerance_sec=onset_tolerance_sec, pitch_tolerance=pitch_tolerance
    )
    removed = _find_removed_notes(before, after)

    harmful = 0
    beneficial = 0
    ambiguous = 0
    removals: list[dict[str, Any]] = []
    for bi in removed:
        note = before[bi]
        if bi in correct_before:
            harmful += 1
            label = "harmful"
        else:
            # Was not a correct match before → likely beneficial FP removal
            beneficial += 1
            label = "beneficial"
        removals.append(
            {
                "before_index": bi,
                "pitch": int(note.pitch),
                "onset": float(note.start_time),
                "offset": float(note.end_time),
                "classification": label,
            }
        )

    # Taxonomy summaries for richer reporting
    tax_before = classify_notes(reference, before, stage="transcription")
    tax_after = classify_notes(reference, after, stage="post_cleaner")

    precision_delta = m_after.onset_pitch_precision - m_before.onset_pitch_precision
    recall_delta = m_after.onset_pitch_recall - m_before.onset_pitch_recall
    f1_delta = m_after.onset_pitch_f1 - m_before.onset_pitch_f1

    return {
        "notes_before": len(before),
        "notes_after": len(after),
        "notes_removed": len(removed),
        "correct_notes_before": len(correct_before),
        "correct_notes_after": len(correct_after),
        "false_positives_before": m_before.false_positives,
        "false_positives_after": m_after.false_positives,
        "false_negatives_before": m_before.false_negatives,
        "false_negatives_after": m_after.false_negatives,
        "harmful_removals": harmful,
        "beneficial_removals": beneficial,
        "ambiguous_removals": ambiguous,
        "precision_before": m_before.onset_pitch_precision,
        "precision_after": m_after.onset_pitch_precision,
        "recall_before": m_before.onset_pitch_recall,
        "recall_after": m_after.onset_pitch_recall,
        "f1_before": m_before.onset_pitch_f1,
        "f1_after": m_after.onset_pitch_f1,
        "precision_delta": precision_delta,
        "recall_delta": recall_delta,
        "f1_delta": f1_delta,
        "helps": f1_delta > 0.01,
        "hurts": f1_delta < -0.01,
        "removals": removals,
        "taxonomy_before": tax_before.summary.to_dict() if tax_before.summary else None,
        "taxonomy_after": tax_after.summary.to_dict() if tax_after.summary else None,
    }
