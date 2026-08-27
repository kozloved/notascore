"""Per-case and corpus forensic analysis orchestration."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Sequence

from benchmark.note_extract import notes_from_midi
from evaluation.forensics.cleaner import cleaner_impact
from evaluation.forensics.classify import ClassificationResult, classify_notes
from evaluation.forensics.midi_out import (
    export_stage_diagnostic_midis,
    write_single_track_midi,
)
from evaluation.forensics.offset import offset_forensics
from evaluation.forensics.stats import (
    bin_counts,
    distribution,
    duration_bin_ms,
    pitch_error_bucket,
    polyphony_bin,
    register_bin,
    summarize_bins,
    tempo_bin,
)
from evaluation.forensics.tempo import classify_tempo_ratio, tempo_note_f1_causality
from evaluation.forensics.taxonomy import REF_MISSED, NoteErrorRow
from evaluation.matching import match_notes
from evaluation.normalize import normalize_reference_midi
from mir.types import NoteEvent

STAGE_ORDER = (
    "transcription",
    "post_cleaner",
    "post_piano",
    "structured",
)

STAGE_FILES = {
    "transcription": ("transcription.mid", "prediction_raw.mid"),
    "post_cleaner": ("post_cleaner.mid", "prediction_cleaned.mid"),
    "post_piano": ("post_piano.mid", None),
    "structured": ("structured.mid", None),
}


def _load_notes(path: Path | None) -> list[NoteEvent] | None:
    if path is None or not Path(path).is_file():
        return None
    return notes_from_midi(path)


def _write_csv(rows: Sequence[NoteErrorRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(NoteErrorRow(
        case_id="", stage="", side="", classification=""
    ).to_dict().keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def _first_stage_of_failure(
    stage_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Find earliest stage where quality materially degrades vs prior stage."""
    ordered = [s for s in STAGE_ORDER if s in stage_metrics]
    if not ordered:
        return {"stage": None, "reason": "no stages"}
    first = ordered[0]
    first_f1 = float((stage_metrics[first].get("match") or {}).get("onset_pitch_f1") or 0)
    result: dict[str, Any] = {
        "pitch_onset_f1_first_low_stage": None,
        "recall_first_drop_stage": None,
        "precision_first_drop_stage": None,
        "primary_failure_stage": None,
        "reason": "",
    }
    if first_f1 < 0.85:
        result["pitch_onset_f1_first_low_stage"] = first
        result["primary_failure_stage"] = first
        result["reason"] = (
            f"Primary gap already at {first} (onset+pitch F1={first_f1:.3f})"
        )

    prev_f1 = prev_r = prev_p = None
    for stage in ordered:
        m = stage_metrics[stage].get("match") or {}
        f1 = m.get("onset_pitch_f1")
        rec = m.get("onset_pitch_recall")
        prec = m.get("onset_pitch_precision")
        if prev_f1 is not None and isinstance(f1, (int, float)):
            if f1 < prev_f1 - 0.02 and result["primary_failure_stage"] is None:
                result["primary_failure_stage"] = stage
                result["reason"] = (
                    f"First material F1 drop at {stage} "
                    f"({prev_f1:.3f} → {f1:.3f})"
                )
            if (
                isinstance(rec, (int, float))
                and isinstance(prev_r, (int, float))
                and rec < prev_r - 0.02
                and result["recall_first_drop_stage"] is None
            ):
                result["recall_first_drop_stage"] = stage
            if (
                isinstance(prec, (int, float))
                and isinstance(prev_p, (int, float))
                and prec < prev_p - 0.02
                and result["precision_first_drop_stage"] is None
            ):
                result["precision_first_drop_stage"] = stage
        if isinstance(f1, (int, float)):
            prev_f1 = float(f1)
        if isinstance(rec, (int, float)):
            prev_r = float(rec)
        if isinstance(prec, (int, float)):
            prev_p = float(prec)

    if result["primary_failure_stage"] is None:
        result["primary_failure_stage"] = first
        result["reason"] = result["reason"] or "No large stage-to-stage drop; earliest stage is primary."
    return result


def _characteristic_analysis(
    reference: Sequence[NoteEvent],
    classification: ClassificationResult,
    *,
    reference_tempo: float | None,
) -> dict[str, Any]:
    items_tempo: list[tuple[str, str]] = []
    items_dur: list[tuple[str, str]] = []
    items_reg: list[tuple[str, str]] = []
    items_poly: list[tuple[str, str]] = []
    onset_errs: list[float] = []
    offset_errs: list[float] = []
    dur_errs: list[float] = []
    pitch_buckets: dict[str, int] = {}

    ref_class_by_index: dict[int, str] = {}
    for row in classification.rows:
        if row.side in ("pair", "reference") and row.reference_index is not None:
            ref_class_by_index[row.reference_index] = row.classification
        if row.side == "pair" and row.onset_error_ms is not None:
            onset_errs.append(float(row.onset_error_ms))
        if row.side == "pair" and row.offset_error_ms is not None:
            offset_errs.append(float(row.offset_error_ms))
        if row.side == "pair" and row.duration_error_ms is not None:
            dur_errs.append(float(row.duration_error_ms))
        if row.side == "pair" and row.pitch_error_semitones is not None:
            b = pitch_error_bucket(row.pitch_error_semitones)
            pitch_buckets[b] = pitch_buckets.get(b, 0) + 1

    for i, ref in enumerate(reference):
        cls = ref_class_by_index.get(i, REF_MISSED)
        items_tempo.append((tempo_bin(reference_tempo), cls))
        items_dur.append((duration_bin_ms(max(0.0, float(ref.end_time) - float(ref.start_time))), cls))
        items_reg.append((register_bin(int(ref.pitch)), cls))
        # local polyphony approx from classification rows
        poly = 1
        for row in classification.rows:
            if row.reference_index == i and row.local_polyphony:
                poly = int(row.local_polyphony)
                break
        items_poly.append((polyphony_bin(poly), cls))

    return {
        "by_tempo": summarize_bins(bin_counts(items_tempo)),
        "by_duration": summarize_bins(bin_counts(items_dur)),
        "by_register": summarize_bins(bin_counts(items_reg)),
        "by_polyphony": summarize_bins(bin_counts(items_poly)),
        "onset_error_ms": distribution(onset_errs),
        "offset_error_ms": distribution(offset_errs),
        "duration_error_ms": distribution(dur_errs),
        "pitch_error_buckets": pitch_buckets,
    }


def analyze_case(
    *,
    case_id: str,
    case_out_dir: Path,
    reference_raw_path: Path | None,
    reference_tempo: float | None = None,
    predicted_tempo: float | None = None,
    expected_tempo: float | None = None,
) -> dict[str, Any]:
    """Run full forensics for one evaluated case directory."""
    case_out_dir = Path(case_out_dir)
    diag_dir = case_out_dir / "diagnostics"
    diag_dir.mkdir(parents=True, exist_ok=True)

    # Prefer copied reference in results; never mutate corpus files
    ref_copy = case_out_dir / "reference_raw.mid"
    if not ref_copy.is_file():
        ref_copy = case_out_dir / "reference.mid"
    ref_path = reference_raw_path
    if ref_copy.is_file():
        # Use copy for analysis path reporting; load from available file
        load_path = ref_copy
    elif ref_path and Path(ref_path).is_file():
        load_path = Path(ref_path)
    else:
        return {
            "case_id": case_id,
            "status": "skipped",
            "reason": "missing reference_raw for forensics",
        }

    before_bytes = None
    if reference_raw_path and Path(reference_raw_path).is_file():
        before_bytes = Path(reference_raw_path).read_bytes()

    ref_norm = normalize_reference_midi(load_path)
    reference = list(ref_norm.notes)
    ref_tempo = expected_tempo or reference_tempo or ref_norm.tempo_bpm

    if before_bytes is not None and Path(reference_raw_path).read_bytes() != before_bytes:
        raise RuntimeError(f"Corpus reference mutated during forensics: {reference_raw_path}")

    # Write reference copy into diagnostics (from results copy, not corpus overwrite)
    write_single_track_midi(
        reference, diag_dir / "reference_raw.mid", track_name="Reference", bpm=ref_tempo or 120.0
    )

    stage_notes: dict[str, list[NoteEvent]] = {}
    stage_results: dict[str, Any] = {}
    all_rows: list[NoteErrorRow] = []

    for stage, (src_name, alias) in STAGE_FILES.items():
        src = case_out_dir / src_name
        notes = _load_notes(src)
        if notes is None:
            stage_results[stage] = {
                "status": "unavailable",
                "reason": f"missing {src_name}",
            }
            continue
        stage_notes[stage] = notes
        if alias:
            write_single_track_midi(
                notes, diag_dir / alias, track_name=stage, bpm=predicted_tempo or ref_tempo or 120.0
            )

        classification = classify_notes(
            reference,
            notes,
            stage=stage,
            case_id=case_id,
            reference_tempo=ref_tempo,
            predicted_tempo=predicted_tempo,
        )
        match = match_notes(notes, reference)
        midi_paths = export_stage_diagnostic_midis(
            out_dir=diag_dir / stage,
            reference=reference,
            predicted=notes,
            classification=classification,
            bpm=predicted_tempo or ref_tempo or 120.0,
        )
        chars = _characteristic_analysis(
            reference, classification, reference_tempo=ref_tempo
        )
        stage_results[stage] = {
            "status": "evaluated",
            "taxonomy": classification.summary.to_dict() if classification.summary else None,
            "match": match.to_dict(),
            "midi": midi_paths,
            "characteristics": chars,
            "classification": classification.to_dict(),
        }
        all_rows.extend(classification.rows)

    # Prefer transcription stage for primary exports at diagnostics root
    if "transcription" in stage_notes:
        clf = classify_notes(
            reference,
            stage_notes["transcription"],
            stage="transcription",
            case_id=case_id,
            reference_tempo=ref_tempo,
            predicted_tempo=predicted_tempo,
        )
        export_stage_diagnostic_midis(
            out_dir=diag_dir,
            reference=reference,
            predicted=stage_notes["transcription"],
            classification=clf,
            bpm=predicted_tempo or ref_tempo or 120.0,
            prefix="",
        )
        # Explicit names required by the checkpoint
        write_single_track_midi(
            stage_notes["transcription"],
            diag_dir / "prediction_raw.mid",
            track_name="PredictionRaw",
            bpm=predicted_tempo or 120.0,
        )
    if "post_cleaner" in stage_notes:
        write_single_track_midi(
            stage_notes["post_cleaner"],
            diag_dir / "prediction_cleaned.mid",
            track_name="PredictionCleaned",
            bpm=predicted_tempo or 120.0,
        )

    _write_csv(all_rows, diag_dir / "note_errors.csv")

    cleaner = None
    if "transcription" in stage_notes and "post_cleaner" in stage_notes:
        cleaner = cleaner_impact(
            reference, stage_notes["transcription"], stage_notes["post_cleaner"]
        )
        (diag_dir / "cleaner_impact.json").write_text(
            json.dumps(cleaner, indent=2) + "\n", encoding="utf-8"
        )

    offset = None
    if "transcription" in stage_notes:
        offset = offset_forensics(stage_notes["transcription"], reference)
        (diag_dir / "offset_forensics.json").write_text(
            json.dumps(offset, indent=2) + "\n", encoding="utf-8"
        )

    tempo_info = classify_tempo_ratio(ref_tempo, predicted_tempo)
    trans_match = (stage_results.get("transcription") or {}).get("match") or {}
    tempo_info["causality"] = tempo_note_f1_causality(
        tempo_status=tempo_info["status"],
        mean_onset_error_ms=trans_match.get("mean_onset_error_ms"),
        onset_pitch_f1=trans_match.get("onset_pitch_f1"),
    )

    failure = _first_stage_of_failure(stage_results)

    payload = {
        "case_id": case_id,
        "status": "ran",
        "reference_note_count": len(reference),
        "reference_tempo": ref_tempo,
        "predicted_tempo": predicted_tempo,
        "tempo": tempo_info,
        "stages": stage_results,
        "first_stage_of_failure": failure,
        "cleaner_impact": cleaner,
        "offset_forensics": offset,
        "diagnostics_dir": str(diag_dir),
    }
    (diag_dir / "forensics.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return payload


def analyze_corpus(case_payloads: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate forensic statistics across cases."""
    ran = [c for c in case_payloads if c.get("status") == "ran"]
    tax_agg = {
        "matched": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "pitch_errors": 0,
        "onset_errors": 0,
        "offset_errors": 0,
        "fragmented": 0,
        "merged": 0,
        "duplicates": 0,
        "reference_notes": 0,
        "predicted_notes": 0,
    }
    onset_all: list[float] = []
    offset_all: list[float] = []
    duration_all: list[float] = []
    pitch_buckets: dict[str, int] = {}
    cleaner_agg = {
        "harmful_removals": 0,
        "beneficial_removals": 0,
        "f1_deltas": [],
        "precision_deltas": [],
        "recall_deltas": [],
        "cases_helped": 0,
        "cases_hurt": 0,
        "cases_neutral": 0,
    }
    tempo_statuses: dict[str, int] = {}
    offset_verdicts: dict[str, int] = {}
    failure_stages: dict[str, int] = {}
    char_duration_misses: list[dict[str, Any]] = []

    for case in ran:
        tax = (
            ((case.get("stages") or {}).get("transcription") or {}).get("taxonomy")
            or {}
        )
        tax_agg["matched"] += int(tax.get("matched_pairs") or 0)
        tax_agg["false_positives"] += int(tax.get("false_positives") or 0)
        tax_agg["false_negatives"] += int(tax.get("false_negatives") or 0)
        tax_agg["pitch_errors"] += int(tax.get("pitch_errors") or 0)
        tax_agg["onset_errors"] += int(tax.get("onset_errors") or 0)
        tax_agg["offset_errors"] += int(tax.get("offset_errors") or 0)
        tax_agg["fragmented"] += int(tax.get("fragmented") or 0)
        tax_agg["merged"] += int(tax.get("merged") or 0)
        tax_agg["duplicates"] += int(tax.get("duplicates") or 0)
        tax_agg["reference_notes"] += int(tax.get("reference_count") or 0)
        tax_agg["predicted_notes"] += int(tax.get("predicted_count") or 0)

        chars = (
            ((case.get("stages") or {}).get("transcription") or {}).get(
                "characteristics"
            )
            or {}
        )
        for key, bucket in (
            ("onset_error_ms", onset_all),
            ("offset_error_ms", offset_all),
            ("duration_error_ms", duration_all),
        ):
            dist = chars.get(key) or {}
            # We don't have raw lists in aggregate payload; pull from offset_forensics when present
            pass
        for b, n in (chars.get("pitch_error_buckets") or {}).items():
            pitch_buckets[b] = pitch_buckets.get(b, 0) + int(n)
        for row in chars.get("by_duration") or []:
            char_duration_misses.append({"case_id": case.get("case_id"), **row})

        off = case.get("offset_forensics") or {}
        # Reconstruct lists are not stored; use distribution means via signed lists if present
        # Prefer reading duration_error from match
        match = ((case.get("stages") or {}).get("transcription") or {}).get("match") or {}
        # onset errors only as single mean — collect from forensics signed if available
        signed = (off.get("signed_offset_error_ms") or {})
        # Collect multi-case by re-summing counts only

        ci = case.get("cleaner_impact") or {}
        if ci:
            cleaner_agg["harmful_removals"] += int(ci.get("harmful_removals") or 0)
            cleaner_agg["beneficial_removals"] += int(ci.get("beneficial_removals") or 0)
            if isinstance(ci.get("f1_delta"), (int, float)):
                cleaner_agg["f1_deltas"].append(float(ci["f1_delta"]))
            if isinstance(ci.get("precision_delta"), (int, float)):
                cleaner_agg["precision_deltas"].append(float(ci["precision_delta"]))
            if isinstance(ci.get("recall_delta"), (int, float)):
                cleaner_agg["recall_deltas"].append(float(ci["recall_delta"]))
            if ci.get("helps"):
                cleaner_agg["cases_helped"] += 1
            elif ci.get("hurts"):
                cleaner_agg["cases_hurt"] += 1
            else:
                cleaner_agg["cases_neutral"] += 1

        ts = (case.get("tempo") or {}).get("status") or "UNKNOWN"
        tempo_statuses[ts] = tempo_statuses.get(ts, 0) + 1
        ov = ((case.get("offset_forensics") or {}).get("conclusion") or {}).get(
            "verdict"
        ) or "unknown"
        offset_verdicts[ov] = offset_verdicts.get(ov, 0) + 1
        fs = ((case.get("first_stage_of_failure") or {}).get("primary_failure_stage"))
        if fs:
            failure_stages[fs] = failure_stages.get(fs, 0) + 1

        # Pull raw error samples from stage characteristics distributions is limited;
        # re-open note_errors if needed — for aggregate means use match fields:
        if isinstance(match.get("mean_onset_error_ms"), (int, float)):
            onset_all.append(float(match["mean_onset_error_ms"]))
        if isinstance(match.get("mean_duration_error_ms"), (int, float)):
            duration_all.append(float(match["mean_duration_error_ms"]))
        if isinstance(signed.get("mean"), (int, float)):
            offset_all.append(float(signed["mean"]))

    def _mean(xs: list[float]) -> float | None:
        return sum(xs) / len(xs) if xs else None

    return {
        "case_count": len(case_payloads),
        "ran": len(ran),
        "taxonomy_transcription": tax_agg,
        "onset_error_case_means_ms": distribution(onset_all),
        "offset_error_case_means_ms": distribution(offset_all),
        "duration_error_case_means_ms": distribution(duration_all),
        "pitch_error_buckets": pitch_buckets,
        "cleaner": {
            **{k: v for k, v in cleaner_agg.items() if k != "f1_deltas"},
            "mean_f1_delta": _mean(cleaner_agg["f1_deltas"]),
            "mean_precision_delta": _mean(cleaner_agg["precision_deltas"]),
            "mean_recall_delta": _mean(cleaner_agg["recall_deltas"]),
            "f1_deltas": cleaner_agg["f1_deltas"],
        },
        "tempo_statuses": tempo_statuses,
        "offset_verdicts": offset_verdicts,
        "failure_stages": failure_stages,
        "duration_bins_observed": char_duration_misses,
        "cases": [
            {
                "case_id": c.get("case_id"),
                "status": c.get("status"),
                "primary_failure_stage": (c.get("first_stage_of_failure") or {}).get(
                    "primary_failure_stage"
                ),
                "tempo": c.get("tempo"),
                "cleaner_f1_delta": (c.get("cleaner_impact") or {}).get("f1_delta"),
                "offset_verdict": (
                    (c.get("offset_forensics") or {}).get("conclusion") or {}
                ).get("verdict"),
                "transcription_f1": (
                    ((c.get("stages") or {}).get("transcription") or {}).get("match")
                    or {}
                ).get("onset_pitch_f1"),
            }
            for c in case_payloads
        ],
    }
