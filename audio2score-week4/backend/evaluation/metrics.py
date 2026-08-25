"""Aggregate metric helpers: meter, tempo, hands, pipeline."""

from __future__ import annotations

from typing import Any, Sequence

from evaluation.defaults import ONSET_TOLERANCE_SEC, TEMPO_MATCH_TOLERANCE_BPM
from evaluation.matching import MatchResult, match_notes
from mir.types import Hand, MusicalEvent, NoteEvent

NOT_EVALUATED = "NOT_EVALUATED"


def meter_metrics(
    *,
    predicted: str | None,
    expected: str | None,
    confidence: float | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if not expected:
        status = NOT_EVALUATED
        correct = None
    elif not predicted:
        status = "incorrect"
        correct = False
    else:
        if expected == "4/4":
            correct = predicted in ("4/4", "2/4")
        else:
            correct = predicted == expected
        status = "correct" if correct else "incorrect"
    return {
        "predicted": predicted,
        "expected": expected,
        "confidence": confidence,
        "reason": reason,
        "status": status,
        "correct": correct,
    }


def tempo_metrics(
    *,
    predicted_bpm: float | None,
    reference_bpm: float | None,
    tolerance_bpm: float = TEMPO_MATCH_TOLERANCE_BPM,
) -> dict[str, Any]:
    if reference_bpm is None or predicted_bpm is None:
        return {
            "reference_bpm": reference_bpm,
            "predicted_bpm": predicted_bpm,
            "error_bpm": None,
            "status": NOT_EVALUATED,
            "within_tolerance": None,
        }
    error = abs(float(predicted_bpm) - float(reference_bpm))
    return {
        "reference_bpm": float(reference_bpm),
        "predicted_bpm": float(predicted_bpm),
        "error_bpm": error,
        "status": "evaluated",
        "within_tolerance": error <= tolerance_bpm,
    }


def hand_metrics(
    predicted_events: Sequence[MusicalEvent],
    reference_notes: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = ONSET_TOLERANCE_SEC,
) -> dict[str, Any]:
    labeled = [n for n in reference_notes if n.hand in (Hand.LEFT, Hand.RIGHT)]
    if not labeled:
        return {
            "status": NOT_EVALUATED,
            "accuracy": None,
            "total": 0,
            "correct": 0,
            "lh_to_rh": 0,
            "rh_to_lh": 0,
            "confusion": {},
            "reason": "reference has no LH/RH track labels",
        }

    used: set[int] = set()
    correct = 0
    total = 0
    lh_to_rh = 0
    rh_to_lh = 0
    confusion: dict[str, int] = {}

    for ref in labeled:
        best_i = None
        best_dt = float("inf")
        for i, ev in enumerate(predicted_events):
            if i in used:
                continue
            if int(ev.pitch) != int(ref.pitch):
                continue
            pred_t = ev.start_time_sec
            if pred_t is None:
                continue
            dt = abs(float(pred_t) - float(ref.start_time))
            if dt <= onset_tolerance_sec and dt < best_dt:
                best_dt = dt
                best_i = i
        if best_i is None:
            continue
        used.add(best_i)
        got = predicted_events[best_i].hand.value
        expected = ref.hand.value
        total += 1
        key = f"{expected}->{got}"
        confusion[key] = confusion.get(key, 0) + 1
        if got == expected:
            correct += 1
        elif expected == Hand.LEFT.value and got == Hand.RIGHT.value:
            lh_to_rh += 1
        elif expected == Hand.RIGHT.value and got == Hand.LEFT.value:
            rh_to_lh += 1

    return {
        "status": "evaluated",
        "accuracy": (correct / total) if total else None,
        "total": total,
        "correct": correct,
        "lh_to_rh": lh_to_rh,
        "rh_to_lh": rh_to_lh,
        "confusion": confusion,
        "reference_labeled": len(labeled),
    }


def note_metrics_dict(result: MatchResult) -> dict[str, Any]:
    return result.to_dict()


def compare_stage_notes(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    **kwargs: Any,
) -> dict[str, Any]:
    return note_metrics_dict(match_notes(predicted, reference, **kwargs))
