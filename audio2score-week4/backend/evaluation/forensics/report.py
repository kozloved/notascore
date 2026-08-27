"""Markdown report writer for Checkpoint 8 forensics aggregates."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _fmt(v: Any, digits: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{digits}f}"
    return str(v)


def write_forensics_report(
    aggregate: dict[str, Any],
    cases: list[dict[str, Any]],
    run_dir: Path,
) -> Path:
    tax = aggregate.get("taxonomy_transcription") or {}
    cleaner = aggregate.get("cleaner") or {}
    lines: list[str] = [
        "# Checkpoint 8 — Transcription forensics report",
        "",
        f"- cases ran: {aggregate.get('ran')} / {aggregate.get('case_count')}",
        "",
        "## Aggregate taxonomy (transcription vs reference_raw)",
        "",
        f"- reference notes: {tax.get('reference_notes')}",
        f"- predicted notes: {tax.get('predicted_notes')}",
        f"- matched: {tax.get('matched')}",
        f"- false positives: {tax.get('false_positives')}",
        f"- false negatives: {tax.get('false_negatives')}",
        f"- pitch errors: {tax.get('pitch_errors')}",
        f"- onset errors: {tax.get('onset_errors')}",
        f"- offset errors: {tax.get('offset_errors')}",
        f"- fragmented: {tax.get('fragmented')}",
        f"- merged: {tax.get('merged')}",
        f"- duplicates/extra fragments: {tax.get('duplicates')}",
        "",
        "## Cleaner impact",
        "",
        f"- harmful removals: {cleaner.get('harmful_removals')}",
        f"- beneficial removals: {cleaner.get('beneficial_removals')}",
        f"- mean F1 Δ: {_fmt(cleaner.get('mean_f1_delta'))}",
        f"- mean precision Δ: {_fmt(cleaner.get('mean_precision_delta'))}",
        f"- mean recall Δ: {_fmt(cleaner.get('mean_recall_delta'))}",
        f"- cases helped / hurt / neutral: "
        f"{cleaner.get('cases_helped')} / {cleaner.get('cases_hurt')} / "
        f"{cleaner.get('cases_neutral')}",
        "",
        "## Tempo statuses",
        "",
    ]
    for k, v in sorted((aggregate.get("tempo_statuses") or {}).items()):
        lines.append(f"- {k}: {v}")
    lines += ["", "## Offset verdicts", ""]
    for k, v in sorted((aggregate.get("offset_verdicts") or {}).items()):
        lines.append(f"- {k}: {v}")
    lines += ["", "## Primary failure stages", ""]
    for k, v in sorted((aggregate.get("failure_stages") or {}).items()):
        lines.append(f"- {k}: {v}")
    lines += [
        "",
        "## Per-case",
        "",
        "| Case | Trans F1 | Failure stage | Tempo | Cleaner ΔF1 | Offset verdict |",
        "|---|---|---|---|---|---|",
    ]
    for c in cases:
        if c.get("status") != "ran":
            lines.append(
                f"| {c.get('case_id')} | — | — | — | — | {c.get('status')} |"
            )
            continue
        tempo = c.get("tempo") or {}
        lines.append(
            "| {id} | {f1} | {fail} | {tempo} | {d} | {off} |".format(
                id=c.get("case_id"),
                f1=_fmt(
                    (
                        ((c.get("stages") or {}).get("transcription") or {}).get(
                            "match"
                        )
                        or {}
                    ).get("onset_pitch_f1")
                ),
                fail=(c.get("first_stage_of_failure") or {}).get(
                    "primary_failure_stage"
                ),
                tempo=f"{tempo.get('status')} ({_fmt(tempo.get('ratio'))})",
                d=_fmt((c.get("cleaner_impact") or {}).get("f1_delta")),
                off=(
                    (c.get("offset_forensics") or {}).get("conclusion") or {}
                ).get("verdict"),
            )
        )
    lines.append("")
    path = Path(run_dir) / "forensics_report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
