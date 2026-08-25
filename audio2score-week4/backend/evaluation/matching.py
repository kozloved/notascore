"""Musical note matching built on top of benchmark.metrics.match_notes.

Keeps evaluation-specific onset-only and offset-aware views without forking
the core pitch+onset matcher used by the synthetic benchmark suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Sequence

from benchmark.metrics import match_notes as benchmark_match_notes
from benchmark.metrics import onset_f_measure as onset_f_measure
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


def _offset_match_count(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float,
    offset_tolerance_sec: float,
    pitch_tolerance: int,
) -> int:
    """Greedy onset+pitch+offset match count (evaluation extension only)."""
    matched_pred: set[int] = set()
    matched = 0
    for ref in reference:
        best_pi = None
        best_dt = float("inf")
        for pi, pred in enumerate(predicted):
            if pi in matched_pred:
                continue
            if abs(int(pred.pitch) - int(ref.pitch)) > pitch_tolerance:
                continue
            dt = abs(float(pred.start_time) - float(ref.start_time))
            if dt > onset_tolerance_sec:
                continue
            doff = abs(float(pred.end_time) - float(ref.end_time))
            if doff > offset_tolerance_sec:
                continue
            if dt < best_dt:
                best_dt = dt
                best_pi = pi
        if best_pi is not None:
            matched_pred.add(best_pi)
            matched += 1
    return matched


def _duration_errors_ms(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float,
    pitch_tolerance: int,
) -> list[float]:
    matched_pred: set[int] = set()
    errors: list[float] = []
    for ref in reference:
        best_pi = None
        best_dt = float("inf")
        for pi, pred in enumerate(predicted):
            if pi in matched_pred:
                continue
            if abs(int(pred.pitch) - int(ref.pitch)) > pitch_tolerance:
                continue
            dt = abs(float(pred.start_time) - float(ref.start_time))
            if dt <= onset_tolerance_sec and dt < best_dt:
                best_dt = dt
                best_pi = pi
        if best_pi is None:
            continue
        matched_pred.add(best_pi)
        pred = predicted[best_pi]
        ref_dur = max(0.0, float(ref.end_time) - float(ref.start_time))
        pred_dur = max(0.0, float(pred.end_time) - float(pred.start_time))
        errors.append(abs(pred_dur - ref_dur) * 1000.0)
    return errors


def match_notes(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = ONSET_TOLERANCE_SEC,
    offset_tolerance_sec: float = OFFSET_TOLERANCE_SEC,
    pitch_tolerance: int = PITCH_TOLERANCE_SEMITONES,
    compute_offset: bool = True,
) -> MatchResult:
    """Match predicted notes to reference with musical tolerances.

    Onset+pitch matching delegates to ``benchmark.metrics.match_notes``.
    Onset-only and offset-aware views are thin evaluation extensions.
    """
    pred = list(predicted)
    ref = list(reference)

    onset_p, onset_r, onset_f1 = onset_f_measure(
        [float(n.start_time) for n in pred],
        [float(n.start_time) for n in ref],
        tolerance_sec=onset_tolerance_sec,
    )

    core = benchmark_match_notes(
        pred,
        ref,
        onset_tolerance_sec=onset_tolerance_sec,
        pitch_tolerance=pitch_tolerance,
    )
    matched = int(core.pitch_matches)
    pitch_p, pitch_r, pitch_f1 = core.precision, core.recall, core.f1
    onset_errors = list(core.onset_errors_ms)

    offset_p = offset_r = offset_f1 = None
    if compute_offset:
        off_matched = _offset_match_count(
            pred,
            ref,
            onset_tolerance_sec=onset_tolerance_sec,
            offset_tolerance_sec=offset_tolerance_sec,
            pitch_tolerance=pitch_tolerance,
        )
        offset_p, offset_r, offset_f1 = _prf(off_matched, len(pred), len(ref))

    duration_errors = _duration_errors_ms(
        pred,
        ref,
        onset_tolerance_sec=onset_tolerance_sec,
        pitch_tolerance=pitch_tolerance,
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
        mean_onset_error_ms=(
            sum(onset_errors) / len(onset_errors) if onset_errors else None
        ),
        median_onset_error_ms=median(onset_errors) if onset_errors else None,
        pitch_error_rate=((len(ref) - matched) / len(ref) if ref else None),
        mean_duration_error_ms=(
            sum(duration_errors) / len(duration_errors) if duration_errors else None
        ),
        onset_errors_ms=onset_errors,
        duration_errors_ms=duration_errors,
    )
