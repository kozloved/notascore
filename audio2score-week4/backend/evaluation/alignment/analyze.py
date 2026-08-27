"""Per-case and corpus alignment forensics orchestration (Checkpoint 9B)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from benchmark.note_extract import notes_from_midi
from evaluation.alignment.midi_time import audit_midi_file, conversion_method_doc
from evaluation.alignment.pianoroll import write_piano_roll
from evaluation.alignment.transforms import (
    OFFSET_SEARCH_RANGE_MS,
    combined_search,
    correspondence_analysis,
    f1_at,
    nearest_neighbor_diagnostics,
    offset_search,
    probe_audio,
    probe_notes,
    scale_notes,
    scale_search,
    shift_notes,
    text_note_summary,
    tolerance_sweep,
)
from evaluation.normalize import normalize_reference_midi
from evaluation.schema import CaseSpec
from mir.types import NoteEvent

OFFICIAL_TOLERANCE_SEC = 0.05


def _write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def find_prediction_midi(case: CaseSpec, *, eval_results_root: Path) -> Path | None:
    """Locate a reusable transcription.mid without re-running Basic Pitch."""
    # Prefer newest run dir that contains this case's transcription.mid
    if not eval_results_root.is_dir():
        return None
    candidates: list[Path] = []
    for run_dir in sorted(eval_results_root.iterdir(), reverse=True):
        if not run_dir.is_dir() or run_dir.name.startswith("."):
            continue
        # case_id may be nested; try direct and search
        direct = run_dir / case.case_id / "transcription.mid"
        if direct.is_file():
            candidates.append(direct)
            continue
        for mid in run_dir.rglob("transcription.mid"):
            if mid.parent.name == case.case_id or case.case_id in str(mid):
                candidates.append(mid)
    return candidates[0] if candidates else None


def load_prediction_notes(
    case: CaseSpec,
    *,
    eval_results_root: Path,
    prediction_midi: Path | None = None,
) -> tuple[list[NoteEvent], str]:
    mid = prediction_midi or find_prediction_midi(case, eval_results_root=eval_results_root)
    if mid is None or not mid.is_file():
        raise FileNotFoundError(
            f"No reusable transcription.mid for {case.case_id}; "
            "run evaluation.runner first or pass --prediction-midi"
        )
    return notes_from_midi(mid), str(mid.resolve())


def analyze_case(
    case: CaseSpec,
    *,
    out_dir: Path,
    eval_results_root: Path,
    prediction_midi: Path | None = None,
) -> dict[str, Any]:
    if case.missing_audio() or case.missing_raw_reference():
        return {
            "case_id": case.case_id,
            "status": "skipped",
            "reason": "missing audio or reference_raw",
        }

    assert case.audio_path is not None
    assert case.reference_raw_midi is not None

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    audio_info = probe_audio(case.audio_path)
    ref_audit = audit_midi_file(case.reference_raw_midi)
    ref_notes = list(normalize_reference_midi(case.reference_raw_midi).notes)
    pred_notes, pred_source = load_prediction_notes(
        case, eval_results_root=eval_results_root, prediction_midi=prediction_midi
    )
    pred_info = probe_notes(pred_notes)
    ref_info = probe_notes(ref_notes)

    audio_dur = audio_info.duration_sec
    ref_dur = ref_info.total_end_sec
    pred_dur = pred_info.total_end_sec
    ratio_ar = (audio_dur / ref_dur) if ref_dur > 1e-9 else None
    ratio_pr = (pred_dur / ref_dur) if ref_dur > 1e-9 else None

    baseline = f1_at(pred_notes, ref_notes, onset_tolerance_sec=OFFICIAL_TOLERANCE_SEC)
    tol_rows = tolerance_sweep(pred_notes, ref_notes)

    # Widen offset search when start deltas look large (diagnostic only).
    start_delta_ms = 0.0
    if ref_info.first_onset_sec is not None and pred_info.first_onset_sec is not None:
        start_delta_ms = abs(
            (pred_info.first_onset_sec - ref_info.first_onset_sec) * 1000.0
        )
    off_lo, off_hi = OFFSET_SEARCH_RANGE_MS
    if start_delta_ms > 300:
        pad = int(min(2500, start_delta_ms + 500))
        off_lo, off_hi = -pad, pad
    off = offset_search(pred_notes, ref_notes, range_ms=(off_lo, off_hi))
    scale_first = scale_search(pred_notes, ref_notes, anchor="first_onset")
    scale_zero = scale_search(pred_notes, ref_notes, anchor="zero")
    combined = combined_search(pred_notes, ref_notes)
    nn = nearest_neighbor_diagnostics(ref_notes, pred_notes)
    corr = correspondence_analysis(ref_notes, pred_notes)

    # Explicit tempo-meta reinterpret diagnostic:
    # If MIDI embeds meta_bpm but musical/export tempo was expected_bpm,
    # pretty_midi seconds are stretched by meta/expected vs audio.
    # Reinterpret reference by scaling absolute times by meta/expected.
    tempo_reinterpret = None
    meta_bpm = ref_audit.tempo_events[0][1] if ref_audit.tempo_events else None
    expected_bpm = case.expected_tempo_bpm
    if meta_bpm and expected_bpm and abs(float(meta_bpm) - float(expected_bpm)) > 0.5:
        ratio = float(meta_bpm) / float(expected_bpm)
        ref_reinterp = scale_notes(ref_notes, ratio, anchor_sec=0.0)
        f1_reinterp = f1_at(
            pred_notes, ref_reinterp, onset_tolerance_sec=OFFICIAL_TOLERANCE_SEC
        )
        # Also scale predictions by expected/meta (equivalent direction)
        pred_scaled = scale_notes(
            pred_notes, float(expected_bpm) / float(meta_bpm), anchor_sec=0.0
        )
        f1_pred_scale = f1_at(
            pred_scaled, ref_notes, onset_tolerance_sec=OFFICIAL_TOLERANCE_SEC
        )
        tempo_reinterpret = {
            "midi_meta_bpm": float(meta_bpm),
            "expected_tempo_bpm": float(expected_bpm),
            "scale_reference_by_meta_over_expected": ratio,
            "f1_after_reference_reinterpret": f1_reinterp["onset_pitch_f1"],
            "scale_predicted_by_expected_over_meta": float(expected_bpm) / float(meta_bpm),
            "f1_after_predicted_rescale": f1_pred_scale["onset_pitch_f1"],
            "baseline_f1": baseline["onset_pitch_f1"],
            "delta_f1_reference_reinterpret": (
                f1_reinterp["onset_pitch_f1"] - baseline["onset_pitch_f1"]
            ),
            "interpretation": (
                "Strong F1 recovery after meta/expected reinterpret indicates "
                "DAW MIDI tempo-meta mismatch (ticks authored at expected tempo, "
                "file embeds meta tempo) — a time-base conversion problem, NOT "
                "musical half/double-tempo equivalence."
            ),
        }

    # Silence / start deltas
    ref_first = ref_info.first_onset_sec
    pred_first = pred_info.first_onset_sec
    silence = {
        "audio_first_nonsilent_sec": audio_info.first_nonsilent_sec,
        "reference_first_note_sec": ref_first,
        "predicted_first_note_sec": pred_first,
        "audio_to_reference_start_delta_sec": (
            None
            if ref_first is None
            else float(audio_info.first_nonsilent_sec) - float(ref_first)
        ),
        "predicted_to_reference_start_delta_sec": (
            None
            if ref_first is None or pred_first is None
            else float(pred_first) - float(ref_first)
        ),
    }

    # Duration flags
    flags = []
    for name, ratio in (("audio/reference", ratio_ar), ("predicted/reference", ratio_pr)):
        if ratio is None:
            continue
        if abs(ratio - 0.5) < 0.08:
            flags.append(f"{name} near 0.5 ({ratio:.3f})")
        if abs(ratio - 2.0) < 0.15:
            flags.append(f"{name} near 2.0 ({ratio:.3f})")
        if abs(ratio - 1.0) > 0.25:
            flags.append(f"{name} differs significantly ({ratio:.3f})")

    # Expected tempo vs MIDI meta
    meta_bpm = ref_audit.tempo_events[0][1] if ref_audit.tempo_events else None
    expected_bpm = case.expected_tempo_bpm
    tempo_meta = {
        "midi_meta_bpm": meta_bpm,
        "expected_tempo_bpm": expected_bpm,
        "meta_vs_expected_ratio": (
            None
            if meta_bpm is None or not expected_bpm
            else float(meta_bpm) / float(expected_bpm)
        ),
        "note": (
            "If DAW ticks were authored at expected tempo but file embeds meta_bpm, "
            "pretty_midi seconds stretch by meta/expected relative to audio."
        ),
    }

    # Diagnostic transforms for piano rolls
    best_off_notes = shift_notes(pred_notes, off["best_offset_ms"] / 1000.0)
    best_scale = scale_first["best_scale"]
    anchor = scale_first["anchor_sec"]
    best_scale_notes = scale_notes(pred_notes, best_scale, anchor_sec=anchor)
    comb = combined["best_combined_transform"]
    best_comb_notes = shift_notes(
        scale_notes(pred_notes, comb["scale"], anchor_sec=anchor),
        comb["offset_ms"] / 1000.0,
    )

    rolls = {}
    for name, pred in (
        ("original", pred_notes),
        ("best_offset", best_off_notes),
        ("best_scale", best_scale_notes),
        ("best_combined", best_comb_notes),
    ):
        p = write_piano_roll(
            out_dir / f"pianoroll_{name}.png",
            reference=ref_notes,
            predicted=pred,
            title=f"{case.case_id} — {name}",
        )
        rolls[name] = str(p) if p else None

    summary_txt = text_note_summary(ref_notes, pred_notes)
    (out_dir / "note_summary.txt").write_text(summary_txt, encoding="utf-8")

    # Root-cause hints for this case
    delta_tol = tol_rows[-1]["onset_pitch_f1"] - tol_rows[1]["onset_pitch_f1"]  # 300ms vs 50ms
    delta_off = off["delta_f1"]
    delta_scale = scale_first["delta_f1"]
    delta_comb = comb["delta_f1"]
    delta_tempo_meta = (
        tempo_reinterpret["delta_f1_reference_reinterpret"]
        if tempo_reinterpret
        else 0.0
    )
    hint = "GENUINE_TRANSCRIPTION_FAILURE"
    if delta_tempo_meta >= 0.25:
        hint = "TIME_BASE_OR_MIDI_CONVERSION"
    elif delta_scale >= 0.25 and (
        abs(scale_first["best_scale"] - 0.5) < 0.08
        or abs(scale_first["best_scale"] - 2.0) < 0.08
        or abs(scale_first["best_scale"] - 0.75) < 0.08
        or abs(scale_first["best_scale"] - 1.33) < 0.08
        or abs(scale_first["best_scale"] - 1.15) < 0.08
    ):
        hint = "TIME_BASE_OR_MIDI_CONVERSION"
    elif delta_off >= 0.25:
        hint = "SYSTEMATIC_TIMING_OFFSET"
    elif delta_tol >= 0.25:
        hint = "TIMING_TOLERANCE_SENSITIVE"
    elif max(delta_off, delta_scale, delta_comb, delta_tempo_meta) >= 0.15:
        hint = "PARTIAL_ALIGNMENT_ISSUE"
    elif max(delta_off, delta_scale, delta_comb, delta_tempo_meta) < 0.05 and delta_tol < 0.08:
        hint = "GENUINE_TRANSCRIPTION_FAILURE"

    # Piano roll after tempo-meta reinterpret if strong
    if tempo_reinterpret and tempo_reinterpret["delta_f1_reference_reinterpret"] >= 0.2:
        ref_fix = scale_notes(
            ref_notes,
            tempo_reinterpret["scale_reference_by_meta_over_expected"],
            anchor_sec=0.0,
        )
        p = write_piano_roll(
            out_dir / "pianoroll_tempo_meta_reinterpret.png",
            reference=ref_fix,
            predicted=pred_notes,
            title=f"{case.case_id} — ref reinterpreted by meta/expected",
        )
        rolls["tempo_meta_reinterpret"] = str(p) if p else None

    payload = {
        "case_id": case.case_id,
        "status": "ok",
        "prediction_source": pred_source,
        "reference_source": str(case.reference_raw_midi.resolve()),
        "audio": audio_info.to_dict(),
        "reference_midi_audit": ref_audit.to_dict(),
        "reference_notes": ref_info.to_dict(),
        "predicted_notes": pred_info.to_dict(),
        "durations": {
            "audio_sec": audio_dur,
            "reference_sec": ref_dur,
            "predicted_sec": pred_dur,
            "ratio_audio_reference": ratio_ar,
            "ratio_predicted_reference": ratio_pr,
            "flags": flags,
        },
        "tempo_meta": tempo_meta,
        "tempo_reinterpret_diagnostic": tempo_reinterpret,
        "silence": silence,
        "baseline_official_tolerance": baseline,
        "tolerance_sweep": tol_rows,
        "offset_search": off,
        "scale_search_first_onset_anchor": scale_first,
        "scale_search_zero_anchor": scale_zero,
        "combined_search": combined,
        "nearest_neighbor": {
            k: v for k, v in nn.items() if k != "pairs"
        },
        "nearest_neighbor_pairs": nn["pairs"],
        "correspondence": corr,
        "piano_rolls": rolls,
        "case_root_cause_hint": hint,
        "alignment_deltas": {
            "delta_f1_tol_300_vs_50": delta_tol,
            "delta_f1_best_offset": delta_off,
            "delta_f1_best_scale": delta_scale,
            "delta_f1_best_combined": delta_comb,
            "delta_f1_tempo_meta_reinterpret": delta_tempo_meta,
        },
        "conversion_method": conversion_method_doc(),
    }
    _write_json(out_dir / "alignment.json", payload)
    return payload


def classify_corpus(case_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    hints = [p.get("case_root_cause_hint") for p in case_payloads if p.get("status") == "ok"]
    unique = sorted(set(hints))

    def _mean(key: str) -> float:
        vals = [
            p["alignment_deltas"][key]
            for p in case_payloads
            if p.get("status") == "ok" and key in p.get("alignment_deltas", {})
        ]
        return sum(vals) / len(vals) if vals else 0.0

    mean_tol = _mean("delta_f1_tol_300_vs_50")
    mean_off = _mean("delta_f1_best_offset")
    mean_scale = _mean("delta_f1_best_scale")
    mean_comb = _mean("delta_f1_best_combined")
    mean_tempo = _mean("delta_f1_tempo_meta_reinterpret")

    conversion_cases = [
        p["case_id"]
        for p in case_payloads
        if p.get("case_root_cause_hint") == "TIME_BASE_OR_MIDI_CONVERSION"
    ]
    genuine_cases = [
        p["case_id"]
        for p in case_payloads
        if p.get("case_root_cause_hint") == "GENUINE_TRANSCRIPTION_FAILURE"
    ]

    mixed_with_conversion = bool(conversion_cases) and len(conversion_cases) < len(hints)
    if mixed_with_conversion or (conversion_cases and genuine_cases):
        decision = "D"
        label = "MIXED ROOT CAUSES"
        other = [
            p["case_id"]
            for p in case_payloads
            if p.get("status") == "ok" and p["case_id"] not in conversion_cases
        ]
        other_hints = {
            p["case_id"]: p.get("case_root_cause_hint")
            for p in case_payloads
            if p.get("case_id") in other
        }
        rationale = (
            f"MIDI tempo-meta conversion dominates {conversion_cases} "
            f"(mean tempo-reinterpret ΔF1={mean_tempo:.3f}); "
            f"other cases differ: {other_hints}."
        )
    elif unique == ["TIME_BASE_OR_MIDI_CONVERSION"] or (
        mean_tempo >= 0.25 and len(conversion_cases) == len(hints)
    ):
        decision = "C"
        label = "TIME-BASE / DURATION / MIDI CONVERSION PROBLEM"
        rationale = (
            f"Tempo-meta reinterpret recovers large F1 "
            f"(mean ΔF1={mean_tempo:.3f}). DAW MIDI embeds wrong tempo meta."
        )
    elif unique == ["SYSTEMATIC_TIMING_OFFSET"]:
        decision = "B"
        label = "SYSTEMATIC TIMING ALIGNMENT / LATENCY PROBLEM"
        rationale = "Constant offset recovers large F1 across cases."
    elif mean_comb >= 0.25 or mean_scale >= 0.25 or mean_off >= 0.25 or mean_tempo >= 0.25:
        if mean_tempo >= mean_off and mean_tempo >= 0.25:
            decision = "C"
            label = "TIME-BASE / DURATION / MIDI CONVERSION PROBLEM"
            rationale = f"Mean tempo-meta ΔF1={mean_tempo:.3f}"
        elif mean_scale >= mean_off and mean_scale >= 0.25:
            decision = "C"
            label = "TIME-BASE / DURATION / MIDI CONVERSION PROBLEM"
            rationale = f"Mean scale ΔF1={mean_scale:.3f}"
        elif mean_off >= 0.25:
            decision = "B"
            label = "SYSTEMATIC TIMING ALIGNMENT / LATENCY PROBLEM"
            rationale = f"Mean offset ΔF1={mean_off:.3f}"
        else:
            decision = "D"
            label = "MIXED ROOT CAUSES"
            rationale = f"Combined ΔF1={mean_comb:.3f} with mixed per-case behavior"
    elif len(unique) > 1:
        decision = "D"
        label = "MIXED ROOT CAUSES"
        rationale = f"Per-case hints differ: {unique}"
    else:
        decision = "A"
        label = "GENUINE TRANSCRIPTION FAILURE"
        rationale = (
            f"Tolerance/offset/scale/tempo-meta gains small "
            f"(tol={mean_tol:.3f}, off={mean_off:.3f}, scale={mean_scale:.3f}, "
            f"tempo_meta={mean_tempo:.3f})"
        )

    return {
        "decision": decision,
        "label": label,
        "rationale": rationale,
        "per_case_hints": {
            p["case_id"]: p.get("case_root_cause_hint")
            for p in case_payloads
            if p.get("status") == "ok"
        },
        "mean_deltas": {
            "tolerance_300_vs_50": mean_tol,
            "best_offset": mean_off,
            "best_scale": mean_scale,
            "best_combined": mean_comb,
            "tempo_meta_reinterpret": mean_tempo,
        },
    }


def aggregate_tolerance_sweep(case_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_tol: dict[float, list[dict[str, Any]]] = {}
    for p in case_payloads:
        if p.get("status") != "ok":
            continue
        for row in p.get("tolerance_sweep", []):
            by_tol.setdefault(float(row["onset_tolerance_sec"]), []).append(row)
    out = []
    for tol in sorted(by_tol):
        rows = by_tol[tol]
        n = len(rows)
        out.append(
            {
                "onset_tolerance_sec": tol,
                "onset_tolerance_ms": tol * 1000.0,
                "macro_onset_f1": sum(r["onset_f1"] for r in rows) / n,
                "macro_onset_pitch_f1": sum(r["onset_pitch_f1"] for r in rows) / n,
                "macro_precision": sum(r["onset_pitch_precision"] for r in rows) / n,
                "macro_recall": sum(r["onset_pitch_recall"] for r in rows) / n,
                "total_matched": sum(r["matched"] for r in rows),
                "total_fp": sum(r["false_positives"] for r in rows),
                "total_fn": sum(r["false_negatives"] for r in rows),
            }
        )
    return out
