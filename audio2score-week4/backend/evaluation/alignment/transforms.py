"""Duration probes, silence, transform searches, and correspondence (Checkpoint 9B)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Any, Sequence

import numpy as np

from evaluation.matching import match_notes
from mir.types import NoteEvent


TOLERANCE_SWEEP_SEC = (0.025, 0.05, 0.08, 0.10, 0.15, 0.20, 0.30)
OFFSET_SEARCH_RANGE_MS = (-300, 300)
OFFSET_STEP_MS = 10
SCALE_CANDIDATES = (
    0.5,
    0.67,
    0.75,
    0.8,
    0.85,
    0.87,
    0.9,
    0.95,
    0.98,
    1.0,
    1.02,
    1.05,
    1.1,
    1.15,
    1.2,
    1.25,
    1.33,
    1.5,
    1.67,
    2.0,
)


@dataclass
class AudioDurationInfo:
    filename: str
    sample_rate: int
    channels: int
    frame_count: int
    duration_sec: float
    peak_level: float
    first_nonsilent_sec: float
    leading_silence_sec: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NoteStreamInfo:
    note_count: int
    first_onset_sec: float | None
    last_offset_sec: float | None
    duration_span_sec: float
    total_end_sec: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def probe_audio(path: str | Path, *, silence_db: float = 40.0) -> AudioDurationInfo:
    import librosa
    import soundfile as sf

    path = Path(path)
    info = sf.info(str(path))
    y, sr = librosa.load(str(path), mono=True, sr=None)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    intervals = librosa.effects.split(y, top_db=silence_db) if y.size else np.zeros((0, 2))
    if len(intervals):
        first_ns = float(intervals[0][0] / sr)
        lead = first_ns
    else:
        first_ns = 0.0
        lead = float(len(y) / sr) if sr else 0.0
    return AudioDurationInfo(
        filename=path.name,
        sample_rate=int(sr),
        channels=int(info.channels),
        frame_count=int(info.frames),
        duration_sec=float(info.frames / info.samplerate) if info.samplerate else 0.0,
        peak_level=peak,
        first_nonsilent_sec=first_ns,
        leading_silence_sec=lead,
    )


def probe_notes(notes: Sequence[NoteEvent]) -> NoteStreamInfo:
    ns = list(notes)
    if not ns:
        return NoteStreamInfo(0, None, None, 0.0, 0.0)
    first = min(float(n.start_time) for n in ns)
    last = max(float(n.end_time) for n in ns)
    return NoteStreamInfo(
        note_count=len(ns),
        first_onset_sec=first,
        last_offset_sec=last,
        duration_span_sec=last - first,
        total_end_sec=last,
    )


def shift_notes(notes: Sequence[NoteEvent], offset_sec: float) -> list[NoteEvent]:
    out: list[NoteEvent] = []
    for n in notes:
        out.append(
            NoteEvent(
                pitch=int(n.pitch),
                start_time=float(n.start_time) + offset_sec,
                end_time=float(n.end_time) + offset_sec,
                velocity=int(n.velocity),
                confidence=n.confidence,
                note_id=n.note_id,
                source_backend=n.source_backend,
            )
        )
    return out


def scale_notes(
    notes: Sequence[NoteEvent],
    scale: float,
    *,
    anchor_sec: float = 0.0,
) -> list[NoteEvent]:
    """predicted' = anchor + scale * (predicted - anchor)."""
    out: list[NoteEvent] = []
    for n in notes:
        start = anchor_sec + scale * (float(n.start_time) - anchor_sec)
        end = anchor_sec + scale * (float(n.end_time) - anchor_sec)
        if end < start:
            end = start + 0.01
        out.append(
            NoteEvent(
                pitch=int(n.pitch),
                start_time=start,
                end_time=end,
                velocity=int(n.velocity),
                confidence=n.confidence,
                note_id=n.note_id,
                source_backend=n.source_backend,
            )
        )
    return out


def f1_at(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = 0.05,
) -> dict[str, Any]:
    m = match_notes(
        list(predicted),
        list(reference),
        onset_tolerance_sec=onset_tolerance_sec,
        compute_offset=False,
    )
    return {
        "onset_precision": m.onset_precision,
        "onset_recall": m.onset_recall,
        "onset_f1": m.onset_f1,
        "onset_pitch_precision": m.onset_pitch_precision,
        "onset_pitch_recall": m.onset_pitch_recall,
        "onset_pitch_f1": m.onset_pitch_f1,
        "matched": m.matched,
        "false_positives": m.false_positives,
        "false_negatives": m.false_negatives,
        "predicted_count": m.predicted_count,
        "reference_count": m.reference_count,
    }


def tolerance_sweep(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    tolerances: Sequence[float] = TOLERANCE_SWEEP_SEC,
) -> list[dict[str, Any]]:
    rows = []
    for tol in tolerances:
        row = f1_at(predicted, reference, onset_tolerance_sec=float(tol))
        row["onset_tolerance_sec"] = float(tol)
        row["onset_tolerance_ms"] = float(tol) * 1000.0
        rows.append(row)
    return rows


def offset_search(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    range_ms: tuple[int, int] = OFFSET_SEARCH_RANGE_MS,
    step_ms: int = OFFSET_STEP_MS,
    onset_tolerance_sec: float = 0.05,
) -> dict[str, Any]:
    lo, hi = int(range_ms[0]), int(range_ms[1])
    # Align lo to step grid and always include 0.
    offsets = set(range(lo, hi + 1, step_ms))
    offsets.add(0)
    scores: list[tuple[float, float]] = []  # (offset_ms, f1)
    for off_ms in sorted(offsets):
        shifted = shift_notes(predicted, off_ms / 1000.0)
        f1 = f1_at(shifted, reference, onset_tolerance_sec=onset_tolerance_sec)[
            "onset_pitch_f1"
        ]
        scores.append((float(off_ms), float(f1)))
    scores.sort(key=lambda x: (-x[1], abs(x[0])))
    zero = next(f for o, f in scores if abs(o) < 1e-9)
    best_off, best_f1 = scores[0]
    return {
        "best_offset_ms": best_off,
        "f1_at_zero_offset": zero,
        "f1_at_best_offset": best_f1,
        "delta_f1": best_f1 - zero,
        "top5": [
            {"offset_ms": o, "onset_pitch_f1": f} for o, f in scores[:5]
        ],
        "search": {"range_ms": [lo, hi], "step_ms": step_ms},
    }


def scale_search(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    scales: Sequence[float] = SCALE_CANDIDATES,
    anchor: str = "first_onset",
    onset_tolerance_sec: float = 0.05,
) -> dict[str, Any]:
    if not predicted:
        anchor_sec = 0.0
    elif anchor == "zero":
        anchor_sec = 0.0
    else:
        anchor_sec = min(float(n.start_time) for n in predicted)

    rows = []
    for s in scales:
        scaled = scale_notes(predicted, float(s), anchor_sec=anchor_sec)
        metrics = f1_at(scaled, reference, onset_tolerance_sec=onset_tolerance_sec)
        rows.append(
            {
                "scale": float(s),
                "anchor_sec": float(anchor_sec),
                "anchor_mode": anchor,
                **metrics,
            }
        )
    rows.sort(key=lambda r: (-r["onset_pitch_f1"], abs(r["scale"] - 1.0)))
    base = next(r for r in rows if abs(r["scale"] - 1.0) < 1e-12)
    best = rows[0]
    return {
        "best_scale": best["scale"],
        "f1_at_best_scale": best["onset_pitch_f1"],
        "f1_at_scale_1": base["onset_pitch_f1"],
        "delta_f1": best["onset_pitch_f1"] - base["onset_pitch_f1"],
        "anchor_mode": anchor,
        "anchor_sec": anchor_sec,
        "all_scales": sorted(rows, key=lambda r: r["scale"]),
        "top5": rows[:5],
    }


def combined_search(
    predicted: Sequence[NoteEvent],
    reference: Sequence[NoteEvent],
    *,
    onset_tolerance_sec: float = 0.05,
) -> dict[str, Any]:
    """Coarse offset×scale search then refine around the best region."""
    pred = list(predicted)
    ref = list(reference)
    zero = f1_at(pred, ref, onset_tolerance_sec=onset_tolerance_sec)

    # Coarse grid
    coarse_offsets = list(range(-300, 301, 25))
    coarse_scales = [
        0.5, 0.67, 0.75, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.25, 1.33, 1.5, 2.0
    ]
    anchor = min((float(n.start_time) for n in pred), default=0.0)
    best = {
        "scale": 1.0,
        "offset_ms": 0.0,
        "onset_pitch_f1": zero["onset_pitch_f1"],
    }
    for s in coarse_scales:
        scaled = scale_notes(pred, s, anchor_sec=anchor)
        for off in coarse_offsets:
            shifted = shift_notes(scaled, off / 1000.0)
            f1 = f1_at(shifted, ref, onset_tolerance_sec=onset_tolerance_sec)[
                "onset_pitch_f1"
            ]
            if f1 > best["onset_pitch_f1"] + 1e-12 or (
                abs(f1 - best["onset_pitch_f1"]) < 1e-12
                and abs(s - 1.0) + abs(off) / 1000.0
                < abs(best["scale"] - 1.0) + abs(best["offset_ms"]) / 1000.0
            ):
                best = {"scale": float(s), "offset_ms": float(off), "onset_pitch_f1": f1}

    # Refine around best
    refine_scales = sorted(
        {
            round(best["scale"] + d, 4)
            for d in (-0.05, -0.02, -0.01, 0.0, 0.01, 0.02, 0.05)
            if 0.45 <= best["scale"] + d <= 2.05
        }
    )
    refine_offsets = sorted(
        {
            int(best["offset_ms"] + d)
            for d in range(-40, 41, 5)
            if -300 <= best["offset_ms"] + d <= 300
        }
    )
    for s in refine_scales:
        scaled = scale_notes(pred, s, anchor_sec=anchor)
        for off in refine_offsets:
            shifted = shift_notes(scaled, off / 1000.0)
            f1 = f1_at(shifted, ref, onset_tolerance_sec=onset_tolerance_sec)[
                "onset_pitch_f1"
            ]
            if f1 > best["onset_pitch_f1"] + 1e-12:
                best = {"scale": float(s), "offset_ms": float(off), "onset_pitch_f1": f1}

    off_only = offset_search(pred, ref, onset_tolerance_sec=onset_tolerance_sec)
    scale_only = scale_search(pred, ref, onset_tolerance_sec=onset_tolerance_sec)

    return {
        "zero_transform": {"scale": 1.0, "offset_ms": 0.0, **zero},
        "best_offset_only": {
            "scale": 1.0,
            "offset_ms": off_only["best_offset_ms"],
            "onset_pitch_f1": off_only["f1_at_best_offset"],
            "delta_f1": off_only["delta_f1"],
        },
        "best_scale_only": {
            "scale": scale_only["best_scale"],
            "offset_ms": 0.0,
            "onset_pitch_f1": scale_only["f1_at_best_scale"],
            "delta_f1": scale_only["delta_f1"],
        },
        "best_combined_transform": {
            **best,
            "delta_f1": best["onset_pitch_f1"] - zero["onset_pitch_f1"],
            "anchor_sec": anchor,
        },
    }


def nearest_neighbor_diagnostics(
    reference: Sequence[NoteEvent],
    predicted: Sequence[NoteEvent],
) -> dict[str, Any]:
    refs = list(reference)
    preds = list(predicted)
    pairs = []
    onset_errors = []
    abs_onset_errors = []
    pitch_buckets = {"0": 0, "1": 0, "2": 0, "12": 0, "other": 0}

    for i, ref in enumerate(refs):
        if not preds:
            pairs.append(
                {
                    "reference_index": i,
                    "reference_pitch": int(ref.pitch),
                    "predicted_index": None,
                    "predicted_pitch": None,
                    "onset_diff_ms": None,
                    "pitch_diff_semitones": None,
                }
            )
            continue
        best_j = min(
            range(len(preds)),
            key=lambda j: abs(float(preds[j].start_time) - float(ref.start_time)),
        )
        pred = preds[best_j]
        dt = (float(pred.start_time) - float(ref.start_time)) * 1000.0
        dp = int(pred.pitch) - int(ref.pitch)
        onset_errors.append(dt)
        abs_onset_errors.append(abs(dt))
        adp = abs(dp)
        if adp == 0:
            pitch_buckets["0"] += 1
        elif adp == 1:
            pitch_buckets["1"] += 1
        elif adp == 2:
            pitch_buckets["2"] += 1
        elif adp == 12:
            pitch_buckets["12"] += 1
        else:
            pitch_buckets["other"] += 1
        pairs.append(
            {
                "reference_index": i,
                "reference_pitch": int(ref.pitch),
                "predicted_index": best_j,
                "predicted_pitch": int(pred.pitch),
                "onset_diff_ms": dt,
                "pitch_diff_semitones": dp,
            }
        )

    def _p90(vals: list[float]) -> float | None:
        if not vals:
            return None
        arr = sorted(vals)
        return arr[int(round(0.9 * (len(arr) - 1)))]

    return {
        "pairs": pairs,
        "median_onset_error_ms": median(onset_errors) if onset_errors else None,
        "mean_onset_error_ms": mean(onset_errors) if onset_errors else None,
        "median_abs_onset_error_ms": median(abs_onset_errors) if abs_onset_errors else None,
        "mean_abs_onset_error_ms": mean(abs_onset_errors) if abs_onset_errors else None,
        "p90_abs_onset_error_ms": _p90(abs_onset_errors),
        "max_abs_onset_error_ms": max(abs_onset_errors) if abs_onset_errors else None,
        "pitch_difference_buckets": pitch_buckets,
    }


# Correspondence categories
EXACT_MATCH = "EXACT_MATCH"
MATCH_PITCH_WRONG_ONSET = "MATCH_PITCH_WRONG_ONSET"
MATCH_ONSET_WRONG_PITCH = "MATCH_ONSET_WRONG_PITCH"
MATCHED_WITH_LARGE_OFFSET = "MATCHED_WITH_LARGE_OFFSET"
PITCH_CORRECT_BUT_OUTSIDE_TOLERANCE = "PITCH_CORRECT_BUT_OUTSIDE_TOLERANCE"
WRONG_OCTAVE = "WRONG_OCTAVE"
DUPLICATE = "DUPLICATE"
FRAGMENT = "FRAGMENT"
MERGED = "MERGED"
SPURIOUS = "SPURIOUS"
MISSED_REFERENCE = "MISSED_REFERENCE"


def correspondence_analysis(
    reference: Sequence[NoteEvent],
    predicted: Sequence[NoteEvent],
    *,
    onset_tol: float = 0.05,
    large_offset_sec: float = 0.35,
) -> dict[str, Any]:
    """Classify notes preserving pitch-correct / timing-shifted correspondence."""
    from evaluation.forensics.classify import classify_notes

    refs = list(reference)
    preds = list(predicted)
    tax = classify_notes(refs, preds, stage="transcription")

    # Additional correspondence: pitch-correct nearest within large window
    used_pred: set[int] = set()
    used_ref: set[int] = set()
    categories: dict[str, int] = {
        EXACT_MATCH: 0,
        MATCH_PITCH_WRONG_ONSET: 0,
        MATCH_ONSET_WRONG_PITCH: 0,
        MATCHED_WITH_LARGE_OFFSET: 0,
        PITCH_CORRECT_BUT_OUTSIDE_TOLERANCE: 0,
        WRONG_OCTAVE: 0,
        DUPLICATE: 0,
        FRAGMENT: 0,
        MERGED: 0,
        SPURIOUS: 0,
        MISSED_REFERENCE: 0,
    }
    details: list[dict[str, Any]] = []

    # First pass: exact pitch + onset within tol
    for i, ref in enumerate(refs):
        best = None
        for j, pred in enumerate(preds):
            if j in used_pred:
                continue
            if int(pred.pitch) != int(ref.pitch):
                continue
            dt = abs(float(pred.start_time) - float(ref.start_time))
            if dt <= onset_tol and (best is None or dt < best[0]):
                best = (dt, j)
        if best is not None:
            used_ref.add(i)
            used_pred.add(best[1])
            categories[EXACT_MATCH] += 1
            details.append(
                {
                    "ref": i,
                    "pred": best[1],
                    "category": EXACT_MATCH,
                    "onset_error_ms": best[0] * 1000.0,
                }
            )

    # Pitch correct outside tol but within large window
    for i, ref in enumerate(refs):
        if i in used_ref:
            continue
        best = None
        for j, pred in enumerate(preds):
            if j in used_pred:
                continue
            if int(pred.pitch) != int(ref.pitch):
                continue
            dt = abs(float(pred.start_time) - float(ref.start_time))
            if dt <= large_offset_sec and (best is None or dt < best[0]):
                best = (dt, j)
        if best is not None:
            used_ref.add(i)
            used_pred.add(best[1])
            cat = (
                MATCHED_WITH_LARGE_OFFSET
                if best[0] > onset_tol
                else EXACT_MATCH
            )
            if best[0] > onset_tol:
                categories[PITCH_CORRECT_BUT_OUTSIDE_TOLERANCE] += 1
                categories[MATCH_PITCH_WRONG_ONSET] += 1
            categories[cat] += 1
            details.append(
                {
                    "ref": i,
                    "pred": best[1],
                    "category": cat,
                    "onset_error_ms": best[0] * 1000.0,
                }
            )

    # Wrong octave within onset tol
    for i, ref in enumerate(refs):
        if i in used_ref:
            continue
        for j, pred in enumerate(preds):
            if j in used_pred:
                continue
            if abs(int(pred.pitch) - int(ref.pitch)) == 12:
                dt = abs(float(pred.start_time) - float(ref.start_time))
                if dt <= large_offset_sec:
                    used_ref.add(i)
                    used_pred.add(j)
                    categories[WRONG_OCTAVE] += 1
                    details.append(
                        {
                            "ref": i,
                            "pred": j,
                            "category": WRONG_OCTAVE,
                            "onset_error_ms": dt * 1000.0,
                        }
                    )
                    break

    # Onset-aligned wrong pitch
    for i, ref in enumerate(refs):
        if i in used_ref:
            continue
        for j, pred in enumerate(preds):
            if j in used_pred:
                continue
            dt = abs(float(pred.start_time) - float(ref.start_time))
            if dt <= onset_tol and int(pred.pitch) != int(ref.pitch):
                used_ref.add(i)
                used_pred.add(j)
                categories[MATCH_ONSET_WRONG_PITCH] += 1
                details.append(
                    {
                        "ref": i,
                        "pred": j,
                        "category": MATCH_ONSET_WRONG_PITCH,
                        "onset_error_ms": dt * 1000.0,
                        "pitch_diff": int(pred.pitch) - int(ref.pitch),
                    }
                )
                break

    # Taxonomy fragment/merge/duplicate counts
    if tax.summary:
        categories[FRAGMENT] = tax.summary.fragmented
        categories[MERGED] = tax.summary.merged
        categories[DUPLICATE] = tax.summary.duplicates

    for i in range(len(refs)):
        if i not in used_ref:
            categories[MISSED_REFERENCE] += 1
            details.append({"ref": i, "pred": None, "category": MISSED_REFERENCE})
    for j in range(len(preds)):
        if j not in used_pred:
            categories[SPURIOUS] += 1
            details.append({"ref": None, "pred": j, "category": SPURIOUS})

    return {
        "categories": categories,
        "details": details,
        "taxonomy_summary": tax.summary.to_dict() if tax.summary else None,
    }


def text_note_summary(
    reference: Sequence[NoteEvent],
    predicted: Sequence[NoteEvent],
    *,
    limit: int = 40,
) -> str:
    from evaluation.forensics.taxonomy import midi_note_name

    lines = ["REFERENCE:"]
    for n in list(reference)[:limit]:
        lines.append(f"  {midi_note_name(n.pitch):4s}  {float(n.start_time):7.3f}")
    if len(reference) > limit:
        lines.append(f"  ... ({len(reference) - limit} more)")
    lines.append("PREDICTED:")
    for n in list(predicted)[:limit]:
        lines.append(f"  {midi_note_name(n.pitch):4s}  {float(n.start_time):7.3f}")
    if len(predicted) > limit:
        lines.append(f"  ... ({len(predicted) - limit} more)")
    return "\n".join(lines) + "\n"
