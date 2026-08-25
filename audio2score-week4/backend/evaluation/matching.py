"""Configurable musical note matching (onset / pitch / offset)."""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Sequence

from evaluation.defaults import (
    OFFSET_TOLERANCE_SEC,
    ONSET_TOLERANCE_SEC,
    PITCH_TOLERANCE_SEMITONES,
)
from mir.types import NoteEvent


@dataclass
class MatchResult:
    reference_count: int
    predicted_count: int
    matched: int
    false_positives: int
    false_negatives: int
    onset_precision: float
    onset_recall: float
    onset_f1: float
    onset_pitch_precision: float
    onset_pitch_recall: float
    onset_pitch_f1: float
    onset_pitch_offset_precision: float | None = None
    onset_pitch_offset_recall: float | None = None
    onset_pitch_offset_f1: float | None = None
    mean_onset_error_ms: float | None = None
    median_onset_error_ms: float | None = None
    pitch_error_rate: float | None = None
    mean_duration_error_ms: float | None = None
    onset_errors_ms: list[float] = field(default_factory=list)
    duration_errors_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "reference_count": self.reference_count,
            "predicted_count": self.predicted_count,
            "matched": self.matched,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "onset_precision": self.onset_precision,
            "onset_recall": self.onset_recall,
            "onset_f1": self.onset_f1,
            "onset_pitch_precision": self.onset_pitch_precision,
            "onset_pitch_recall": self.onset_pitch_recall,
            "onset_pitch_f1": self.onset_pitch_f1,
            "onset_pitch_offset_precision": self.onset_pitch_offset_precision,
            "onset_pitch_offset_recall": self.onset_pitch_offset_recall,
            "onset_pitch_offset_f1": self.onset_pitch_offset_f1,
            "mean_onset_error_ms": self.mean_onset_error_ms,
            "median_onset_error_ms": self.median_onset_error_ms,
            "pitch_error_rate": self.pitch_error_rate,
            "mean_duration_error_ms": self.mean_duration_error_ms,
        }


def _prf(matched: int, predicted: int, reference: int) -> tuple[float, float, float]:
    precision = matched / predicted if predicted else 0.0
    recall = matched / reference if reference else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    return precision, recall, f1


def _greedy_match(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float,
    pitch_tolerance: int,
    require_pitch: bool,
    offset_tolerance_sec: float | None = None,
) -> tuple[set[int], set[int], list[float], list[float]]:
    """Greedy one-to-one matching. Returns matched pred/ref indices + errors."""
    matched_pred: set[int] = set()
    matched_ref: set[int] = set()
    onset_errors: list[float] = []
    duration_errors: list[float] = []

    for ri, ref in enumerate(reference):
        best_pi = None
        best_dt = float("inf")
        for pi, pred in enumerate(predicted):
            if pi in matched_pred:
                continue
            if require_pitch and abs(int(pred.pitch) - int(ref.pitch)) > pitch_tolerance:
                continue
            dt = abs(float(pred.start_time) - float(ref.start_time))
            if dt > onset_tolerance_sec:
                continue
            if offset_tolerance_sec is not None:
                doff = abs(float(pred.end_time) - float(ref.end_time))
                if doff > offset_tolerance_sec:
                    continue
            if dt < best_dt:
                best_dt = dt
                best_pi = pi
        if best_pi is not None:
            matched_pred.add(best_pi)
            matched_ref.add(ri)
            onset_errors.append(best_dt * 1000.0)
            pred = predicted[best_pi]
            ref_dur = max(0.0, float(ref.end_time) - float(ref.start_time))
            pred_dur = max(0.0, float(pred.end_time) - float(pred.start_time))
            duration_errors.append(abs(pred_dur - ref_dur) * 1000.0)
    return matched_pred, matched_ref, onset_errors, duration_errors


def match_notes(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = ONSET_TOLERANCE_SEC,
    offset_tolerance_sec: float = OFFSET_TOLERANCE_SEC,
    pitch_tolerance: int = PITCH_TOLERANCE_SEMITONES,
    compute_offset: bool = True,
) -> MatchResult:
    """Match predicted notes to reference with musical tolerances."""
    pred = list(predicted)
    ref = list(reference)

    # Onset-only (ignore pitch)
    onset_mp, onset_mr, _, _ = _greedy_match(
        pred,
        ref,
        onset_tolerance_sec=onset_tolerance_sec,
        pitch_tolerance=pitch_tolerance,
        require_pitch=False,
    )
    onset_p, onset_r, onset_f1 = _prf(len(onset_mp), len(pred), len(ref))

    # Onset + pitch
    pitch_mp, pitch_mr, onset_errors, duration_errors = _greedy_match(
        pred,
        ref,
        onset_tolerance_sec=onset_tolerance_sec,
        pitch_tolerance=pitch_tolerance,
        require_pitch=True,
    )
    pitch_p, pitch_r, pitch_f1 = _prf(len(pitch_mp), len(pred), len(ref))

    offset_p = offset_r = offset_f1 = None
    if compute_offset:
        off_mp, _, _, _ = _greedy_match(
            pred,
            ref,
            onset_tolerance_sec=onset_tolerance_sec,
            pitch_tolerance=pitch_tolerance,
            require_pitch=True,
            offset_tolerance_sec=offset_tolerance_sec,
        )
        offset_p, offset_r, offset_f1 = _prf(len(off_mp), len(pred), len(ref))

    matched = len(pitch_mp)
    mean_onset = (
        sum(onset_errors) / len(onset_errors) if onset_errors else None
    )
    med_onset = median(onset_errors) if onset_errors else None
    mean_dur = (
        sum(duration_errors) / len(duration_errors) if duration_errors else None
    )
    # Pitch error among onset-matched pairs that failed pitch match is hard;
    # report fraction of reference notes not pitch-matched within tolerance.
    pitch_error_rate = (
        (len(ref) - matched) / len(ref) if ref else None
    )

    return MatchResult(
        reference_count=len(ref),
        predicted_count=len(pred),
        matched=matched,
        false_positives=max(0, len(pred) - matched),
        false_negatives=max(0, len(ref) - matched),
        onset_precision=onset_p,
        onset_recall=onset_r,
        onset_f1=onset_f1,
        onset_pitch_precision=pitch_p,
        onset_pitch_recall=pitch_r,
        onset_pitch_f1=pitch_f1,
        onset_pitch_offset_precision=offset_p,
        onset_pitch_offset_recall=offset_r,
        onset_pitch_offset_f1=offset_f1,
        mean_onset_error_ms=mean_onset,
        median_onset_error_ms=med_onset,
        pitch_error_rate=pitch_error_rate,
        mean_duration_error_ms=mean_dur,
        onset_errors_ms=onset_errors,
        duration_errors_ms=duration_errors,
    )
