"""Evaluation metrics for transcription quality."""

from __future__ import annotations

from dataclasses import dataclass

from mir.types import NoteEvent


@dataclass
class NoteMetrics:
    precision: float
    recall: float
    f1: float
    onset_errors_ms: list[float]
    pitch_matches: int
    pitch_total: int


def match_notes(
    predicted: list[NoteEvent],
    reference: list[NoteEvent],
    onset_tolerance_sec: float = 0.05,
    pitch_tolerance: int = 0,
) -> NoteMetrics:
    """Match notes by pitch + onset within tolerance."""
    matched_pred = set()
    matched_ref = set()
    onset_errors: list[float] = []
    pitch_matches = 0

    for ri, ref in enumerate(reference):
        best_pi = None
        best_dt = float("inf")
        for pi, pred in enumerate(predicted):
            if pi in matched_pred:
                continue
            if abs(pred.pitch - ref.pitch) > pitch_tolerance:
                continue
            dt = abs(pred.start_time - ref.start_time)
            if dt <= onset_tolerance_sec and dt < best_dt:
                best_dt = dt
                best_pi = pi
        if best_pi is not None:
            matched_pred.add(best_pi)
            matched_ref.add(ri)
            onset_errors.append(best_dt * 1000)
            pitch_matches += 1

    tp = len(matched_pred)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(reference) if reference else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return NoteMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        onset_errors_ms=onset_errors,
        pitch_matches=pitch_matches,
        pitch_total=len(reference),
    )


def onset_f_measure(
    predicted_times: list[float],
    reference_times: list[float],
    tolerance_sec: float = 0.05,
) -> tuple[float, float, float]:
    matched = 0
    used_ref = set()
    for pt in predicted_times:
        for ri, rt in enumerate(reference_times):
            if ri in used_ref:
                continue
            if abs(pt - rt) <= tolerance_sec:
                matched += 1
                used_ref.add(ri)
                break
    p = matched / len(predicted_times) if predicted_times else 0.0
    r = matched / len(reference_times) if reference_times else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1
