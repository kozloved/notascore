"""Compare Basic Pitch profiles without changing production defaults.

This module records precision and recall. It never names a winning profile
unless the rows include real model inference (`inferred=True`). Missing audio
or skipped inference is reported as `not_evaluated`.
"""

from __future__ import annotations

from typing import Any, Sequence

from adapters.basic_pitch_backend import (
    BASIC_PITCH_PROFILES,
    PRODUCTION_PROFILE,
    basic_pitch_settings,
    inference_settings,
)
from evaluation.defaults import ONSET_TOLERANCE_SEC
from evaluation.matching import match_notes
from mir.types import NoteEvent

COMPARISON_AXES = (
    "minimum_note_length",
    "onset_threshold",
    "frame_threshold",
    "minimum_frequency",
    "maximum_frequency",
)

MUSICAL_CHALLENGES = (
    "short_notes",
    "ornaments",
    "repeated_attacks",
    "high_piano",
    "bass",
    "quiet_passages",
)


def profile_catalog() -> dict[str, Any]:
    return {
        "production_profile": PRODUCTION_PROFILE,
        "production_defaults": dict(BASIC_PITCH_PROFILES[PRODUCTION_PROFILE]),
        "profiles": {
            name: dict(values) for name, values in BASIC_PITCH_PROFILES.items()
        },
        "comparison_axes": list(COMPARISON_AXES),
        "challenges": list(MUSICAL_CHALLENGES),
        "effective_settings": basic_pitch_settings(),
    }


def settings_delta(profile: str, *, versus: str = PRODUCTION_PROFILE) -> dict[str, Any]:
    left = inference_settings(basic_pitch_settings(versus))
    right = dict(BASIC_PITCH_PROFILES[profile])
    changed = {
        key: {"from": left[key], "to": right[key]}
        for key in COMPARISON_AXES
        if left.get(key) != right.get(key)
    }
    return {
        "profile": profile,
        "versus": versus,
        "changed": changed,
        "unchanged": [key for key in COMPARISON_AXES if key not in changed],
    }


def precision_recall(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = ONSET_TOLERANCE_SEC,
) -> dict[str, Any]:
    match = match_notes(
        list(predicted),
        list(reference),
        onset_tolerance_sec=onset_tolerance_sec,
    )
    return {
        "precision": match.onset_pitch_precision
        if hasattr(match, "onset_pitch_precision")
        else _precision(match.matched, match.false_positives),
        "recall": match.onset_pitch_recall
        if hasattr(match, "onset_pitch_recall")
        else _recall(match.matched, match.false_negatives),
        "f1": match.onset_pitch_f1,
        "matched": match.matched,
        "false_positives": match.false_positives,
        "false_negatives": match.false_negatives,
        "predicted_count": len(predicted),
        "reference_count": len(reference),
    }


def _precision(matched: int, false_positives: int) -> float | None:
    denom = matched + false_positives
    if denom <= 0:
        return None
    return matched / denom


def _recall(matched: int, false_negatives: int) -> float | None:
    denom = matched + false_negatives
    if denom <= 0:
        return None
    return matched / denom


def summarize_profile_runs(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate comparison rows. No winner without real inference."""
    inferred = [row for row in rows if row.get("inferred")]
    skipped = [row for row in rows if not row.get("inferred")]
    by_profile: dict[str, list[dict[str, Any]]] = {}
    for row in inferred:
        by_profile.setdefault(str(row.get("profile") or "unknown"), []).append(row)

    def _mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    summary = {}
    for name, group in by_profile.items():
        precisions = [
            float(r["precision"])
            for r in group
            if isinstance(r.get("precision"), (int, float))
        ]
        recalls = [
            float(r["recall"]) for r in group if isinstance(r.get("recall"), (int, float))
        ]
        f1s = [float(r["f1"]) for r in group if isinstance(r.get("f1"), (int, float))]
        summary[name] = {
            "n": len(group),
            "mean_precision": _mean(precisions),
            "mean_recall": _mean(recalls),
            "mean_f1": _mean(f1s),
        }

    winner = None
    reason = "no real inference results"
    if inferred:
        # Require both precision and recall; do not optimize recall alone.
        scored = []
        for name, stats in summary.items():
            if stats["mean_precision"] is None or stats["mean_recall"] is None:
                continue
            scored.append((stats["mean_f1"] or 0.0, stats["mean_precision"], name))
        if scored:
            scored.sort(reverse=True)
            winner = scored[0][2]
            reason = "highest mean F1 among inferred runs (precision and recall required)"
        else:
            reason = "inferred runs lacked precision/recall"
    return {
        "status": "evaluated" if inferred else "not_evaluated",
        "winner": winner,
        "reason": reason,
        "inferred_count": len(inferred),
        "skipped_count": len(skipped),
        "by_profile": summary,
        "challenges": list(MUSICAL_CHALLENGES),
    }
