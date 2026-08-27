"""Markdown report builder for Checkpoint 9B alignment forensics."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _fmt(v: float | None, digits: int = 3) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


def build_markdown(
    *,
    run_id: str,
    manifest: dict[str, Any],
    cases: list[dict[str, Any]],
    decision: dict[str, Any],
    tolerance_agg: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append("# Checkpoint 9B — Evaluation Alignment Forensics")
    lines.append("")
    lines.append(f"**Run ID:** `{run_id}`  ")
    lines.append(f"**Git:** `{manifest.get('git_branch')}` @ `{manifest.get('git_commit')}`  ")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(decision.get("rationale", ""))
    lines.append("")
    lines.append(f"**Root cause decision: {decision.get('decision')} — {decision.get('label')}**")
    lines.append("")
    lines.append("## Key Finding")
    lines.append("")
    lines.append(
        "This checkpoint asks whether Checkpoint 9A's low onset+pitch F1 is real "
        "transcription failure or incorrect evaluation comparison."
    )
    lines.append("")
    lines.append(f"Corpus classification: **{decision.get('label')}**.")
    lines.append("")

    # Duration table
    lines.append("## Audio / MIDI Duration Table")
    lines.append("")
    lines.append(
        "| Case | Audio Duration | Reference Duration | Predicted Duration | "
        "Ratio Audio/Reference | Ratio Predicted/Reference | Flags |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for p in cases:
        if p.get("status") != "ok":
            continue
        d = p["durations"]
        lines.append(
            f"| {p['case_id']} | {_fmt(d['audio_sec'], 3)} | {_fmt(d['reference_sec'], 3)} | "
            f"{_fmt(d['predicted_sec'], 3)} | {_fmt(d['ratio_audio_reference'], 3)} | "
            f"{_fmt(d['ratio_predicted_reference'], 3)} | "
            f"{'; '.join(d.get('flags') or []) or '—'} |"
        )
    lines.append("")

    lines.append("## MIDI Time Conversion Audit")
    lines.append("")
    lines.append("Production conversion: `pretty_midi.Note.start/end` seconds via file tempo map.")
    lines.append("No application-level tick→seconds for F1 matching.")
    lines.append("")
    lines.append("| Case | PPQ | MIDI meta BPM | Expected BPM | Meta/Expected | First ref onset | First pred onset |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for p in cases:
        if p.get("status") != "ok":
            continue
        tm = p["tempo_meta"]
        aud = p["reference_midi_audit"]
        sil = p["silence"]
        lines.append(
            f"| {p['case_id']} | {aud.get('resolution_ppq')} | "
            f"{_fmt(tm.get('midi_meta_bpm'), 1)} | {_fmt(tm.get('expected_tempo_bpm'), 1)} | "
            f"{_fmt(tm.get('meta_vs_expected_ratio'), 3)} | "
            f"{_fmt(sil.get('reference_first_note_sec'), 3)} | "
            f"{_fmt(sil.get('predicted_first_note_sec'), 3)} |"
        )
    lines.append("")

    lines.append("## Baseline at Normal Tolerance")
    lines.append("")
    lines.append("| Case | Onset F1 | Onset+Pitch F1 | P | R | Matched | FP | FN |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for p in cases:
        if p.get("status") != "ok":
            continue
        b = p["baseline_official_tolerance"]
        lines.append(
            f"| {p['case_id']} | {_fmt(b['onset_f1'])} | {_fmt(b['onset_pitch_f1'])} | "
            f"{_fmt(b['onset_pitch_precision'])} | {_fmt(b['onset_pitch_recall'])} | "
            f"{b['matched']} | {b['false_positives']} | {b['false_negatives']} |"
        )
    lines.append("")

    lines.append("## Tolerance Sweep")
    lines.append("")
    lines.append("| Tol (ms) | Macro onset F1 | Macro onset+pitch F1 | Precision | Recall | FP | FN |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|")
    for row in tolerance_agg:
        lines.append(
            f"| {row['onset_tolerance_ms']:.0f} | {_fmt(row['macro_onset_f1'])} | "
            f"{_fmt(row['macro_onset_pitch_f1'])} | {_fmt(row['macro_precision'])} | "
            f"{_fmt(row['macro_recall'])} | {row['total_fp']} | {row['total_fn']} |"
        )
    lines.append("")
    if tolerance_agg:
        base = next(r for r in tolerance_agg if abs(r["onset_tolerance_sec"] - 0.05) < 1e-9)
        wide = tolerance_agg[-1]
        delta = wide["macro_onset_pitch_f1"] - base["macro_onset_pitch_f1"]
        lines.append(
            f"Δ F1 from 50 ms → {wide['onset_tolerance_ms']:.0f} ms = **{_fmt(delta)}**. "
            + (
                "Large jump ⇒ timing alignment problem. "
                if delta >= 0.25
                else "Small jump ⇒ likely genuine transcription errors (or pitch mismatch)."
            )
        )
        lines.append("")

    lines.append("## Offset Search")
    lines.append("")
    lines.append("| Case | F1@0 | Best offset (ms) | F1@best | Δ F1 |")
    lines.append("|---|---:|---:|---:|---:|")
    for p in cases:
        if p.get("status") != "ok":
            continue
        o = p["offset_search"]
        lines.append(
            f"| {p['case_id']} | {_fmt(o['f1_at_zero_offset'])} | {o['best_offset_ms']:.0f} | "
            f"{_fmt(o['f1_at_best_offset'])} | {_fmt(o['delta_f1'])} |"
        )
    lines.append("")

    lines.append("## Time-Scale Search")
    lines.append("")
    lines.append("| Case | F1@1.0 | Best scale | F1@best | Δ F1 | Anchor |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for p in cases:
        if p.get("status") != "ok":
            continue
        s = p["scale_search_first_onset_anchor"]
        lines.append(
            f"| {p['case_id']} | {_fmt(s['f1_at_scale_1'])} | {s['best_scale']} | "
            f"{_fmt(s['f1_at_best_scale'])} | {_fmt(s['delta_f1'])} | {s['anchor_mode']} |"
        )
    lines.append("")

    lines.append("## Tempo-Meta Reinterpret Diagnostic")
    lines.append("")
    lines.append(
        "If DAW ticks were authored at expected tempo but the MIDI file embeds a "
        "different meta BPM (often 120), `pretty_midi` stretches absolute seconds. "
        "Reinterpreting reference times by `meta/expected` is a diagnostic for that "
        "export bug — it is **not** musical half/double-tempo equivalence."
    )
    lines.append("")
    lines.append("| Case | Meta BPM | Expected | Scale ref | F1 baseline | F1 after reinterpret | Δ F1 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for p in cases:
        if p.get("status") != "ok":
            continue
        tr = p.get("tempo_reinterpret_diagnostic")
        if not tr:
            lines.append(f"| {p['case_id']} | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {p['case_id']} | {_fmt(tr['midi_meta_bpm'], 1)} | "
            f"{_fmt(tr['expected_tempo_bpm'], 1)} | "
            f"{_fmt(tr['scale_reference_by_meta_over_expected'], 3)} | "
            f"{_fmt(tr['baseline_f1'])} | {_fmt(tr['f1_after_reference_reinterpret'])} | "
            f"{_fmt(tr['delta_f1_reference_reinterpret'])} |"
        )
    lines.append("")

    lines.append("## Combined Search")
    lines.append("")
    lines.append("| Case | Zero F1 | Best offset-only | Best scale-only | Best combined (scale, offset_ms, F1) |")
    lines.append("|---|---:|---|---|---|")
    for p in cases:
        if p.get("status") != "ok":
            continue
        c = p["combined_search"]
        z = c["zero_transform"]["onset_pitch_f1"]
        bo = c["best_offset_only"]
        bs = c["best_scale_only"]
        bc = c["best_combined_transform"]
        lines.append(
            f"| {p['case_id']} | {_fmt(z)} | "
            f"{bo['offset_ms']:.0f} ms → {_fmt(bo['onset_pitch_f1'])} | "
            f"×{bs['scale']} → {_fmt(bs['onset_pitch_f1'])} | "
            f"×{bc['scale']}, {bc['offset_ms']:.0f} ms → {_fmt(bc['onset_pitch_f1'])} |"
        )
    lines.append("")

    lines.append("## Per-Case Error Taxonomy")
    lines.append("")
    for p in cases:
        if p.get("status") != "ok":
            continue
        lines.append(f"### {p['case_id']} — hint: `{p.get('case_root_cause_hint')}`")
        lines.append("")
        cats = p["correspondence"]["categories"]
        lines.append("| Category | Count |")
        lines.append("|---|---:|")
        for k, v in cats.items():
            if v:
                lines.append(f"| {k} | {v} |")
        lines.append("")

    lines.append("## Nearest-Neighbor Diagnostics")
    lines.append("")
    lines.append("| Case | Median onset err (ms) | Mean | p90 abs | Pitch exact | ±1 | ±2 | octave | other |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for p in cases:
        if p.get("status") != "ok":
            continue
        nn = p["nearest_neighbor"]
        pb = nn["pitch_difference_buckets"]
        lines.append(
            f"| {p['case_id']} | {_fmt(nn.get('median_onset_error_ms'), 1)} | "
            f"{_fmt(nn.get('mean_onset_error_ms'), 1)} | "
            f"{_fmt(nn.get('p90_abs_onset_error_ms'), 1)} | "
            f"{pb.get('0', 0)} | {pb.get('1', 0)} | {pb.get('2', 0)} | "
            f"{pb.get('12', 0)} | {pb.get('other', 0)} |"
        )
    lines.append("")

    lines.append("## Piano Roll Diagnostics")
    lines.append("")
    lines.append("Generated under `evaluation/alignment_diagnostics/<run_id>/<case>/pianoroll_*.png`.")
    lines.append("")

    lines.append("## Half/Double Tempo Interpretation")
    lines.append("")
    lines.append(
        "Wrong **notation tempo** alone does not reduce raw onset+pitch F1 when timestamps "
        "are compared in absolute seconds. A **scale mismatch in absolute seconds** is a "
        "time-base / MIDI conversion problem — not musical half/double-tempo equivalence."
    )
    lines.append("")
    lines.append(
        "If scale≈0.5 or 2.0 recovers F1, treat it as duration/MIDI conversion evidence, "
        "not as 'tempo equivalence'."
    )
    lines.append("")

    lines.append("## Root Cause Decision")
    lines.append("")
    lines.append(f"**{decision.get('decision')} — {decision.get('label')}**")
    lines.append("")
    lines.append(decision.get("rationale", ""))
    lines.append("")
    lines.append("Per-case hints:")
    for cid, hint in (decision.get("per_case_hints") or {}).items():
        lines.append(f"- `{cid}`: {hint}")
    lines.append("")

    lines.append("## Recommended Next Checkpoint")
    lines.append("")
    rec = {
        "A": "Backend comparison (alternate transcription systems).",
        "B": "Fix time alignment / latency before backend comparison.",
        "C": "Audit reference generation and MIDI seconds conversion; fix corpus/export.",
        "D": "Fix evaluator/corpus issues for affected cases AND compare backends.",
    }.get(decision.get("decision"), "Investigate further.")
    lines.append(rec)
    lines.append("")
    return "\n".join(lines)


def write_report(path: Path, markdown: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path
