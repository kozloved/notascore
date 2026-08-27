"""Offset forensics — multi-tolerance diagnostic (does not change production metric)."""

from __future__ import annotations

from typing import Any, Sequence

from evaluation.forensics.stats import distribution
from evaluation.matching import match_notes
from mir.types import NoteEvent

OFFSET_TOLERANCES_SEC = (0.05, 0.10, 0.20, 0.30, 0.50)


def relative_duration_errors(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = 0.05,
    pitch_tolerance: int = 0,
) -> list[float]:
    """Relative duration error for onset+pitch matched pairs."""
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
        ref_dur = max(1e-6, float(ref.end_time) - float(ref.start_time))
        pred_dur = max(0.0, float(pred.end_time) - float(pred.start_time))
        errors.append(abs(pred_dur - ref_dur) / ref_dur)
    return errors


def offset_forensics(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = 0.05,
    pitch_tolerance: int = 0,
    production_offset_tol_sec: float = 0.10,
) -> dict[str, Any]:
    """Evaluate offset F1 at multiple tolerances + error distributions."""
    by_tol: dict[str, Any] = {}
    for tol in OFFSET_TOLERANCES_SEC:
        m = match_notes(
            predicted,
            reference,
            onset_tolerance_sec=onset_tolerance_sec,
            offset_tolerance_sec=tol,
            pitch_tolerance=pitch_tolerance,
            compute_offset=True,
        )
        by_tol[f"{int(tol * 1000)}ms"] = {
            "offset_tolerance_sec": tol,
            "onset_pitch_offset_f1": m.onset_pitch_offset_f1,
            "onset_pitch_f1": m.onset_pitch_f1,
            "matched_onset_pitch": m.matched,
            "mean_duration_error_ms": m.mean_duration_error_ms,
        }

    strict = match_notes(
        predicted,
        reference,
        onset_tolerance_sec=onset_tolerance_sec,
        offset_tolerance_sec=production_offset_tol_sec,
        pitch_tolerance=pitch_tolerance,
        compute_offset=True,
    )
    rel = relative_duration_errors(
        predicted,
        reference,
        onset_tolerance_sec=onset_tolerance_sec,
        pitch_tolerance=pitch_tolerance,
    )

    # Signed offset errors for matched onset+pitch pairs
    matched_pred: set[int] = set()
    signed_offset_ms: list[float] = []
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
        signed_offset_ms.append(
            (float(pred.end_time) - float(ref.end_time)) * 1000.0
        )

    conclusion = _conclude_offset(
        strict_f1=strict.onset_pitch_offset_f1,
        by_tol=by_tol,
        duration_errors_ms=strict.duration_errors_ms,
        relative_errors=rel,
        signed_offset_ms=signed_offset_ms,
        matched=strict.matched,
    )
    return {
        "production_offset_tolerance_sec": production_offset_tol_sec,
        "strict_onset_pitch_offset_f1": strict.onset_pitch_offset_f1,
        "strict_onset_pitch_f1": strict.onset_pitch_f1,
        "matched_onset_pitch_pairs": strict.matched,
        "by_tolerance": by_tol,
        "duration_error_ms": distribution(strict.duration_errors_ms),
        "relative_duration_error": distribution(rel),
        "signed_offset_error_ms": distribution(signed_offset_ms),
        "conclusion": conclusion,
    }


def _conclude_offset(
    *,
    strict_f1: float | None,
    by_tol: dict[str, Any],
    duration_errors_ms: list[float],
    relative_errors: list[float],
    signed_offset_ms: list[float],
    matched: int,
) -> dict[str, Any]:
    if matched <= 0:
        return {
            "verdict": "no_onset_pitch_matches",
            "reason": (
                "Offset F1 is zero/undefined because almost no notes match on "
                "onset+pitch; duration quality cannot be assessed yet."
            ),
        }
    f500 = (by_tol.get("500ms") or {}).get("onset_pitch_offset_f1")
    f100 = (by_tol.get("100ms") or {}).get("onset_pitch_offset_f1")
    mean_dur = (
        sum(duration_errors_ms) / len(duration_errors_ms) if duration_errors_ms else None
    )
    mean_rel = sum(relative_errors) / len(relative_errors) if relative_errors else None
    mean_signed = (
        sum(signed_offset_ms) / len(signed_offset_ms) if signed_offset_ms else None
    )

    if strict_f1 == 0 and f500 is not None and f500 > 0.3:
        return {
            "verdict": "tolerance_sensitive",
            "reason": (
                f"Production offset F1={strict_f1} at 100ms, but F1={f500:.3f} "
                f"at 500ms (n={matched} onset+pitch matches). Zero offset F1 is "
                "partly a tolerance effect, not total absence of duration signal."
            ),
            "mean_duration_error_ms": mean_dur,
            "mean_relative_duration_error": mean_rel,
            "mean_signed_offset_ms": mean_signed,
        }
    if mean_dur is not None and mean_dur > 300:
        return {
            "verdict": "genuine_duration_failure",
            "reason": (
                f"Onset+pitch matches exist (n={matched}) but mean duration error "
                f"is {mean_dur:.0f} ms; offsets are genuinely far from reference "
                f"(strict F1={strict_f1}, 500ms F1={f500})."
            ),
            "mean_duration_error_ms": mean_dur,
            "mean_relative_duration_error": mean_rel,
            "mean_signed_offset_ms": mean_signed,
        }
    if mean_signed is not None and abs(mean_signed) > 150 and mean_dur is not None:
        direction = "late" if mean_signed > 0 else "early"
        return {
            "verdict": "systematic_offset_bias",
            "reason": (
                f"Matched notes show systematic {direction} note-off bias "
                f"(mean signed offset {mean_signed:.0f} ms)."
            ),
            "mean_duration_error_ms": mean_dur,
            "mean_relative_duration_error": mean_rel,
            "mean_signed_offset_ms": mean_signed,
        }
    return {
        "verdict": "mixed",
        "reason": (
            f"strict F1={strict_f1}, 100ms F1={f100}, 500ms F1={f500}, "
            f"mean duration error={mean_dur} ms over {matched} pairs."
        ),
        "mean_duration_error_ms": mean_dur,
        "mean_relative_duration_error": mean_rel,
        "mean_signed_offset_ms": mean_signed,
    }
