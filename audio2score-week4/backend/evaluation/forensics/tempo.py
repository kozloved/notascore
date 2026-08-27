"""Tempo forensics — classify predicted vs reference tempo ratios."""

from __future__ import annotations

from typing import Any


CORRECT = "CORRECT"
HALF_TEMPO = "HALF_TEMPO"
DOUBLE_TEMPO = "DOUBLE_TEMPO"
NEAR_CORRECT = "NEAR_CORRECT"
MISMATCH = "MISMATCH"
UNKNOWN = "UNKNOWN"


def classify_tempo_ratio(
    reference_bpm: float | None,
    predicted_bpm: float | None,
    *,
    correct_tol: float = 0.08,
    near_tol: float = 0.15,
    half_tol: float = 0.10,
) -> dict[str, Any]:
    """Classify tempo relationship without assuming causality for note F1."""
    if reference_bpm is None or predicted_bpm is None:
        return {
            "status": UNKNOWN,
            "reference_bpm": reference_bpm,
            "predicted_bpm": predicted_bpm,
            "ratio": None,
            "reason": "missing reference or predicted tempo",
        }
    ref = float(reference_bpm)
    pred = float(predicted_bpm)
    if ref <= 0:
        return {
            "status": UNKNOWN,
            "reference_bpm": ref,
            "predicted_bpm": pred,
            "ratio": None,
            "reason": "non-positive reference tempo",
        }
    ratio = pred / ref
    status = MISMATCH
    reason = f"ratio={ratio:.3f}"
    if abs(ratio - 1.0) <= correct_tol:
        status = CORRECT
        reason = f"within {correct_tol:.0%} of reference"
    elif abs(ratio - 0.5) <= half_tol:
        status = HALF_TEMPO
        reason = f"≈ half tempo (ratio={ratio:.3f})"
    elif abs(ratio - 2.0) <= half_tol * 2:
        status = DOUBLE_TEMPO
        reason = f"≈ double tempo (ratio={ratio:.3f})"
    elif abs(ratio - 1.0) <= near_tol:
        status = NEAR_CORRECT
        reason = f"near correct (ratio={ratio:.3f})"
    return {
        "status": status,
        "reference_bpm": ref,
        "predicted_bpm": pred,
        "ratio": ratio,
        "reason": reason,
    }


def tempo_note_f1_causality(
    *,
    tempo_status: str,
    mean_onset_error_ms: float | None,
    onset_pitch_f1: float | None,
    onset_tolerance_ms: float = 50.0,
) -> dict[str, Any]:
    """Heuristic: half-tempo alone does not imply note-timing failure.

    Note matching uses absolute seconds. If onset errors are within tolerance
    while tempo is HALF_TEMPO, tempo failure ≠ transcription timing failure.
    """
    if tempo_status not in (HALF_TEMPO, DOUBLE_TEMPO):
        return {
            "tempo_explains_note_f1": False,
            "reason": "tempo not half/double; no tempo-causality claim",
        }
    if mean_onset_error_ms is None or onset_pitch_f1 is None:
        return {
            "tempo_explains_note_f1": None,
            "reason": "insufficient onset-error / F1 evidence",
        }
    if mean_onset_error_ms <= onset_tolerance_ms and onset_pitch_f1 < 0.5:
        return {
            "tempo_explains_note_f1": False,
            "reason": (
                f"tempo={tempo_status} but mean matched onset error "
                f"{mean_onset_error_ms:.1f} ms ≤ {onset_tolerance_ms:.0f} ms; "
                "note F1 failure is not explained by a global time-scale shift"
            ),
        }
    if mean_onset_error_ms > onset_tolerance_ms * 3:
        return {
            "tempo_explains_note_f1": None,
            "reason": (
                f"tempo={tempo_status} and large onset errors "
                f"({mean_onset_error_ms:.1f} ms); possible contribution but "
                "not proven causal without controlled re-timing"
            ),
        }
    return {
        "tempo_explains_note_f1": False,
        "reason": (
            f"tempo={tempo_status}; onset errors {mean_onset_error_ms:.1f} ms "
            f"with F1={onset_pitch_f1:.3f} — insufficient evidence that tempo "
            "alone causes note mismatch"
        ),
    }
