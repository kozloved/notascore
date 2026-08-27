"""Experiment metrics, ranking, and anti-overfitting aggregates (Checkpoint 9A)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import mean, median
from typing import Any, Sequence

from evaluation.forensics.classify import classify_notes
from evaluation.matching import match_notes
from mir.types import NoteEvent


@dataclass
class CaseExperimentMetrics:
    case_id: str
    experiment: str
    predicted_note_count: int
    reference_note_count: int
    # Note detection
    onset_precision: float
    onset_recall: float
    onset_f1: float
    # Pitch
    onset_pitch_precision: float
    onset_pitch_recall: float
    onset_pitch_f1: float
    # Error counts (production F1 FP/FN + taxonomy)
    false_positives: int
    false_negatives: int
    taxonomy_false_positives: int
    taxonomy_false_negatives: int
    pitch_errors: int
    fragmented_notes: int
    merged_notes: int
    duplicate_notes: int
    onset_errors: int
    # Timing on F1-matched pairs (absolute time)
    median_onset_error_ms: float | None
    mean_onset_error_ms: float | None
    p90_onset_error_ms: float | None
    # Diagnostic only
    mean_duration_error_ms: float | None = None
    beat_tracker_tempo_bpm: float | None = None
    expected_tempo_bpm: float | None = None
    preprocess: dict[str, Any] = field(default_factory=dict)
    transcription_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentAggregate:
    experiment: str
    n_cases: int
    baseline_mean_f1: float | None
    experiment_mean_f1: float
    delta_mean_f1: float | None
    mean_onset_f1: float
    mean_precision: float
    mean_recall: float
    total_fp: int
    total_fn: int
    total_pitch_errors: int
    total_fragmented: int
    total_merged: int
    total_duplicates: int
    per_case_delta: dict[str, float]
    worst_case_delta: float | None
    regression_count: int
    improved_count: int
    taxonomy_delta: dict[str, int]
    promising: bool
    promising_reason: str
    rank_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _p90(values: Sequence[float]) -> float | None:
    if not values:
        return None
    arr = sorted(float(v) for v in values)
    idx = int(round(0.9 * (len(arr) - 1)))
    return arr[idx]


def compute_case_metrics(
    *,
    case_id: str,
    experiment: str,
    reference: Sequence[NoteEvent],
    predicted: Sequence[NoteEvent],
    preprocess: dict[str, Any] | None = None,
    transcription_params: dict[str, Any] | None = None,
    beat_tracker_tempo_bpm: float | None = None,
    expected_tempo_bpm: float | None = None,
) -> CaseExperimentMetrics:
    """Compute F1 + taxonomy metrics in absolute time (no tempo correction)."""
    match = match_notes(list(predicted), list(reference), compute_offset=False)
    taxonomy = classify_notes(
        list(reference),
        list(predicted),
        stage="transcription",
        case_id=case_id,
    )
    summary = taxonomy.summary
    onset_errors = list(match.onset_errors_ms)

    return CaseExperimentMetrics(
        case_id=case_id,
        experiment=experiment,
        predicted_note_count=match.predicted_count,
        reference_note_count=match.reference_count,
        onset_precision=match.onset_precision,
        onset_recall=match.onset_recall,
        onset_f1=match.onset_f1,
        onset_pitch_precision=match.onset_pitch_precision,
        onset_pitch_recall=match.onset_pitch_recall,
        onset_pitch_f1=match.onset_pitch_f1,
        false_positives=match.false_positives,
        false_negatives=match.false_negatives,
        taxonomy_false_positives=summary.false_positives if summary else 0,
        taxonomy_false_negatives=summary.false_negatives if summary else 0,
        pitch_errors=summary.pitch_errors if summary else 0,
        fragmented_notes=summary.fragmented if summary else 0,
        merged_notes=summary.merged if summary else 0,
        duplicate_notes=summary.duplicates if summary else 0,
        onset_errors=summary.onset_errors if summary else 0,
        median_onset_error_ms=match.median_onset_error_ms,
        mean_onset_error_ms=match.mean_onset_error_ms,
        p90_onset_error_ms=_p90(onset_errors),
        mean_duration_error_ms=match.mean_duration_error_ms,
        beat_tracker_tempo_bpm=beat_tracker_tempo_bpm,
        expected_tempo_bpm=expected_tempo_bpm,
        preprocess=dict(preprocess or {}),
        transcription_params=dict(transcription_params or {}),
    )


def _macro_mean(values: Sequence[float]) -> float:
    return float(mean(values)) if values else 0.0


def taxonomy_totals(cases: Sequence[CaseExperimentMetrics]) -> dict[str, int]:
    return {
        "false_positives": sum(c.taxonomy_false_positives for c in cases),
        "false_negatives": sum(c.taxonomy_false_negatives for c in cases),
        "pitch_errors": sum(c.pitch_errors for c in cases),
        "fragmented": sum(c.fragmented_notes for c in cases),
        "merged": sum(c.merged_notes for c in cases),
        "duplicates": sum(c.duplicate_notes for c in cases),
        "f1_false_positives": sum(c.false_positives for c in cases),
        "f1_false_negatives": sum(c.false_negatives for c in cases),
    }


def aggregate_experiment(
    experiment: str,
    case_metrics: Sequence[CaseExperimentMetrics],
    *,
    baseline_by_case: dict[str, CaseExperimentMetrics] | None = None,
    meaningful_delta: float = 0.02,
    catastrophic_regression: float = -0.05,
) -> ExperimentAggregate:
    """Macro-average onset+pitch F1 and compute anti-overfitting stats."""
    cases = list(case_metrics)
    f1s = [c.onset_pitch_f1 for c in cases]
    experiment_mean_f1 = _macro_mean(f1s)
    mean_onset_f1 = _macro_mean([c.onset_f1 for c in cases])
    mean_precision = _macro_mean([c.onset_pitch_precision for c in cases])
    mean_recall = _macro_mean([c.onset_pitch_recall for c in cases])

    per_case_delta: dict[str, float] = {}
    baseline_mean_f1 = None
    delta_mean_f1 = None
    worst_case_delta = None
    regression_count = 0
    improved_count = 0
    taxonomy_delta: dict[str, int] = {}

    if baseline_by_case:
        base_list = []
        for c in cases:
            b = baseline_by_case.get(c.case_id)
            if b is None:
                continue
            delta = float(c.onset_pitch_f1) - float(b.onset_pitch_f1)
            per_case_delta[c.case_id] = delta
            base_list.append(float(b.onset_pitch_f1))
            if delta < -1e-12:
                regression_count += 1
            if delta > 1e-12:
                improved_count += 1
        if base_list:
            baseline_mean_f1 = _macro_mean(base_list)
            delta_mean_f1 = experiment_mean_f1 - baseline_mean_f1
        if per_case_delta:
            worst_case_delta = min(per_case_delta.values())

        base_tax = taxonomy_totals(
            [baseline_by_case[c.case_id] for c in cases if c.case_id in baseline_by_case]
        )
        exp_tax = taxonomy_totals(cases)
        taxonomy_delta = {k: exp_tax[k] - base_tax[k] for k in exp_tax}

    # Promising heuristic (conservative; show data, do not hardcode blindly)
    promising = False
    reason = "insufficient baseline comparison"
    if baseline_by_case and delta_mean_f1 is not None and worst_case_delta is not None:
        strong = delta_mean_f1 >= meaningful_delta
        multi_improve = improved_count >= 2
        single_strong = improved_count == 1 and delta_mean_f1 >= 2 * meaningful_delta
        no_catastrophe = worst_case_delta > catastrophic_regression
        # Avoid "improve F1 by deleting notes" — require recall not collapsing
        recall_ok = mean_recall + 1e-12 >= (
            _macro_mean(
                [
                    baseline_by_case[c.case_id].onset_pitch_recall
                    for c in cases
                    if c.case_id in baseline_by_case
                ]
            )
            - 0.05
        )
        if strong and (multi_improve or single_strong) and no_catastrophe and recall_ok:
            promising = True
            reason = (
                f"mean ΔF1={delta_mean_f1:+.3f}, improved={improved_count}, "
                f"regressions={regression_count}, worst_case_delta={worst_case_delta:+.3f}"
            )
        else:
            promising = False
            reason = (
                f"not robust: mean ΔF1={delta_mean_f1:+.3f}, improved={improved_count}, "
                f"regressions={regression_count}, worst_case_delta={worst_case_delta:+.3f}, "
                f"recall_ok={recall_ok}"
            )
    elif not baseline_by_case:
        reason = "baseline experiment (control)"

    # Primary ranking score = macro mean onset+pitch F1
    rank_score = experiment_mean_f1

    return ExperimentAggregate(
        experiment=experiment,
        n_cases=len(cases),
        baseline_mean_f1=baseline_mean_f1,
        experiment_mean_f1=experiment_mean_f1,
        delta_mean_f1=delta_mean_f1,
        mean_onset_f1=mean_onset_f1,
        mean_precision=mean_precision,
        mean_recall=mean_recall,
        total_fp=sum(c.false_positives for c in cases),
        total_fn=sum(c.false_negatives for c in cases),
        total_pitch_errors=sum(c.pitch_errors for c in cases),
        total_fragmented=sum(c.fragmented_notes for c in cases),
        total_merged=sum(c.merged_notes for c in cases),
        total_duplicates=sum(c.duplicate_notes for c in cases),
        per_case_delta=per_case_delta,
        worst_case_delta=worst_case_delta,
        regression_count=regression_count,
        improved_count=improved_count,
        taxonomy_delta=taxonomy_delta,
        promising=promising,
        promising_reason=reason,
        rank_score=rank_score,
    )


def rank_experiments(
    aggregates: Sequence[ExperimentAggregate],
) -> list[ExperimentAggregate]:
    """Rank primarily by macro mean onset+pitch F1; tie-break FN then FP then worst-case."""

    def key(a: ExperimentAggregate) -> tuple:
        worst = a.worst_case_delta if a.worst_case_delta is not None else -999.0
        return (
            a.experiment_mean_f1,
            -a.total_fn,
            -a.total_fp,
            worst,
            -a.regression_count,
        )

    return sorted(aggregates, key=key, reverse=True)


def compare_to_checkpoint8_baseline(
    case_metrics: Sequence[CaseExperimentMetrics],
    *,
    expected: dict[str, dict[str, float]] | None = None,
    f1_atol: float = 0.03,
) -> dict[str, Any]:
    """Validate experiment baseline approximately reproduces Checkpoint 8 numbers."""
    # From docs/CHECKPOINT_8_TRANSCRIPTION_FORENSICS.md / 7B
    expected = expected or {
        "Case1": {"onset_pitch_f1": 0.125, "predicted_note_count": 9, "reference_note_count": 7},
        "Case2": {"onset_pitch_f1": 0.200, "predicted_note_count": 16, "reference_note_count": 14},
        "Case3": {"onset_pitch_f1": 0.102, "predicted_note_count": 35, "reference_note_count": 24},
    }
    details = []
    ok = True
    for m in case_metrics:
        exp = expected.get(m.case_id)
        if exp is None:
            details.append({"case_id": m.case_id, "status": "no_expected"})
            continue
        f1_diff = abs(m.onset_pitch_f1 - exp["onset_pitch_f1"])
        pred_diff = abs(m.predicted_note_count - exp["predicted_note_count"])
        ref_ok = m.reference_note_count == exp["reference_note_count"]
        case_ok = f1_diff <= f1_atol and pred_diff <= 2 and ref_ok
        if not case_ok:
            ok = False
        details.append(
            {
                "case_id": m.case_id,
                "status": "ok" if case_ok else "mismatch",
                "onset_pitch_f1": m.onset_pitch_f1,
                "expected_onset_pitch_f1": exp["onset_pitch_f1"],
                "f1_diff": f1_diff,
                "predicted_note_count": m.predicted_note_count,
                "expected_predicted_note_count": exp["predicted_note_count"],
                "reference_note_count": m.reference_note_count,
                "expected_reference_note_count": exp["reference_note_count"],
            }
        )
    return {"reproduces_checkpoint8": ok, "details": details}
