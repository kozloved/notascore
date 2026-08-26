"""Aggregate JSON and Markdown evaluation reports."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evaluation.metrics import NOT_EVALUATED


def git_info(repo: Path) -> dict[str, str]:
    def _run(args: list[str]) -> str:
        try:
            return (
                subprocess.check_output(
                    args, cwd=str(repo), stderr=subprocess.DEVNULL
                )
                .decode()
                .strip()
            )
        except Exception:
            return "unknown"

    return {
        "commit": _run(["git", "rev-parse", "--short", "HEAD"]),
        "commit_full": _run(["git", "rev-parse", "HEAD"]),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def build_report(
    *,
    cases: list[dict[str, Any]],
    repo: Path,
    split: str | None,
    run_id: str,
    pipeline_config: dict[str, Any] | None = None,
    leakage_warnings: list[str] | None = None,
    baseline_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ran = [c for c in cases if c.get("status") == "ran"]
    skipped = [c for c in cases if c.get("status") == "skipped"]
    errors = [c for c in cases if c.get("status") == "error"]
    def _metric(case: dict[str, Any], namespace: str, key: str) -> float | None:
        block = (case.get("metrics") or {}).get(namespace) or {}
        value = block.get(key)
        if isinstance(value, (int, float)):
            return float(value)
        notes = case.get("notes") or {}
        if namespace == "raw" and isinstance(notes.get(key), (int, float)):
            return float(notes[key])
        return None

    f1s = [
        v
        for c in ran
        if (v := _metric(c, "raw", "onset_pitch_f1")) is not None
    ]
    onset_f1s = [
        v for c in ran if (v := _metric(c, "raw", "onset_f1")) is not None
    ]
    offset_f1s = [
        v
        for c in ran
        if (v := _metric(c, "raw", "onset_pitch_offset_f1")) is not None
    ]
    total_fp = sum(
        int(_metric(c, "raw", "false_positives") or 0) for c in ran
    )
    total_fn = sum(
        int(_metric(c, "raw", "false_negatives") or 0) for c in ran
    )
    cleaner_deltas = [
        float(((c.get("metrics") or {}).get("cleaner_delta") or {}).get("onset_pitch_f1"))
        for c in ran
        if isinstance(
            ((c.get("metrics") or {}).get("cleaner_delta") or {}).get("onset_pitch_f1"),
            (int, float),
        )
    ]
    score_f1s = [
        float(((c.get("metrics") or {}).get("score") or {}).get("quantized_note_f1"))
        for c in ran
        if ((c.get("metrics") or {}).get("score") or {}).get("status") == "evaluated"
        and isinstance(
            ((c.get("metrics") or {}).get("score") or {}).get("quantized_note_f1"),
            (int, float),
        )
    ]
    git = git_info(repo)
    return {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git["commit"],
        "git_full": git["commit_full"],
        "branch": git["branch"],
        "split": split or "all",
        "holdout_marked": (split == "holdout")
        or any(c.get("split") == "holdout" for c in cases),
        "pipeline_configuration": pipeline_config
        or {"mode": "fast", "backend": "basic_pitch"},
        "case_count": len(cases),
        "ran": len(ran),
        "skipped": len(skipped),
        "errors": len(errors),
        "aggregate": {
            "mean_onset_f1": _mean(onset_f1s),
            "mean_onset_pitch_f1": _mean(f1s),
            "mean_raw_onset_f1": _mean(onset_f1s),
            "mean_raw_onset_pitch_f1": _mean(f1s),
            "mean_raw_onset_pitch_offset_f1": _mean(offset_f1s),
            "total_false_positives": total_fp,
            "total_false_negatives": total_fn,
            "mean_cleaner_delta_onset_pitch_f1": _mean(cleaner_deltas),
            "mean_score_quantized_note_f1": _mean(score_f1s),
            "meter_correct": sum(
                1
                for c in ran
                if (c.get("meter") or {}).get("status") == "correct"
            ),
            "meter_incorrect": sum(
                1
                for c in ran
                if (c.get("meter") or {}).get("status") == "incorrect"
            ),
            "meter_not_evaluated": sum(
                1
                for c in ran
                if (c.get("meter") or {}).get("status") == NOT_EVALUATED
            ),
        },
        "leakage_warnings": leakage_warnings or [],
        "baseline_comparison": baseline_comparison,
        "cases": cases,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _status_cell(row: dict[str, Any]) -> str:
    if row.get("status") != "ran":
        return row.get("status") or "—"
    return "ok"


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    split = report.get("split")
    if split == "holdout" or report.get("holdout_marked"):
        lines += [
            "# HOLDOUT EVALUATION",
            "",
            "Do not repeatedly tune the production implementation against "
            "individual holdout cases.",
            "",
        ]
    lines += [
        "# NotaScore evaluation report",
        "",
        f"- run_id: `{report.get('run_id')}`",
        f"- timestamp: `{report.get('timestamp')}`",
        f"- git commit: `{report.get('git')}`",
        f"- git branch: `{report.get('branch')}`",
        f"- split: `{report.get('split')}`",
        f"- pipeline: `{report.get('pipeline_configuration')}`",
        f"- ran: {report.get('ran')}, skipped: {report.get('skipped')}, "
        f"errors: {report.get('errors')}",
        "",
        "## Aggregate metrics",
        "",
        f"- mean raw onset F1: {_fmt((report.get('aggregate') or {}).get('mean_raw_onset_f1') or (report.get('aggregate') or {}).get('mean_onset_f1'))}",
        f"- mean raw onset+pitch F1: {_fmt((report.get('aggregate') or {}).get('mean_raw_onset_pitch_f1') or (report.get('aggregate') or {}).get('mean_onset_pitch_f1'))}",
        f"- mean raw onset+pitch+offset F1: {_fmt((report.get('aggregate') or {}).get('mean_raw_onset_pitch_offset_f1'))}",
        f"- total false positives / negatives: "
        f"{(report.get('aggregate') or {}).get('total_false_positives')} / "
        f"{(report.get('aggregate') or {}).get('total_false_negatives')}",
        f"- mean cleaner Δ onset+pitch F1: {_fmt((report.get('aggregate') or {}).get('mean_cleaner_delta_onset_pitch_f1'))}",
        f"- mean score quantized note F1: {_fmt((report.get('aggregate') or {}).get('mean_score_quantized_note_f1'))}",
        f"- meter correct / incorrect / not evaluated: "
        f"{(report.get('aggregate') or {}).get('meter_correct')} / "
        f"{(report.get('aggregate') or {}).get('meter_incorrect')} / "
        f"{(report.get('aggregate') or {}).get('meter_not_evaluated')}",
        "",
        "## Per-case table",
        "",
        "| Case | Split | Raw F1 | Cleaner F1 | Score F1 | Meter | Status |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report.get("cases") or []:
        notes = row.get("notes") or {}
        metrics = row.get("metrics") or {}
        raw_m = metrics.get("raw") or {}
        cleaner_m = metrics.get("cleaner") or {}
        score_m = metrics.get("score") or {}
        meter = row.get("meter") or {}
        meter_s = meter.get("status") or NOT_EVALUATED
        if meter.get("predicted") and meter_s != NOT_EVALUATED:
            meter_s = f"{meter.get('predicted')} ({meter_s})"
        score_cell = "unavailable"
        if score_m.get("status") == "evaluated":
            score_cell = _fmt(score_m.get("quantized_note_f1"))
        elif score_m.get("status") == "unavailable":
            score_cell = "unavailable"
        lines.append(
            "| {case} | {split} | {raw} | {cleaner} | {score} | {meter} | {status} |".format(
                case=row.get("id"),
                split=row.get("split"),
                raw=_fmt(raw_m.get("onset_pitch_f1") or notes.get("onset_pitch_f1")),
                cleaner=_fmt(cleaner_m.get("onset_pitch_f1")),
                score=score_cell,
                meter=meter_s,
                status=_status_cell(row),
            )
        )

    for warning in report.get("leakage_warnings") or []:
        lines += ["", f"> Warning: {warning}"]

    comparison = report.get("baseline_comparison")
    if comparison:
        agg = comparison.get("aggregate") or {}
        counts = comparison.get("counts") or {}
        lines += [
            "",
            "## Baseline comparison",
            "",
            f"- baseline: `{comparison.get('baseline_name')}`",
            f"- metric: `{comparison.get('metric')}` (epsilon={comparison.get('epsilon')})",
            "",
            f"Onset+Pitch F1",
            f"Baseline: {_fmt(agg.get('baseline_mean'))}",
            f"Current:  {_fmt(agg.get('current_mean'))}",
            f"Delta:   {_fmt_delta(agg.get('delta'))}",
            "",
            f"- IMPROVED: {counts.get('IMPROVED', 0)}",
            f"- REGRESSED: {counts.get('REGRESSED', 0)}",
            f"- UNCHANGED: {counts.get('UNCHANGED', 0)}",
            f"- NEW: {counts.get('NEW', 0)}",
            "",
            "### Improvements",
            "",
        ]
        for row in comparison.get("improvements") or []:
            lines.append(
                f"- `{row['id']}`: {_fmt(row.get('baseline'))} → {_fmt(row.get('current'))} "
                f"({_fmt_delta(row.get('delta'))})"
            )
        if not comparison.get("improvements"):
            lines.append("- none")
        lines += ["", "### Regressions", ""]
        for row in comparison.get("regressions") or []:
            lines.append(
                f"- `{row['id']}`: {_fmt(row.get('baseline'))} → {_fmt(row.get('current'))} "
                f"({_fmt_delta(row.get('delta'))})"
            )
        if not comparison.get("regressions"):
            lines.append("- none")

    lines += ["", "## Per-case stage diagnostics", ""]
    for row in report.get("cases") or []:
        if row.get("status") != "ran":
            continue
        stages = row.get("stages") or {}
        lines += [
            f"### `{row.get('id')}`",
            "",
            "```",
            (stages.get("conclusion") or "").strip() or "(no conclusion)",
            "```",
            "",
        ]
    return "\n".join(lines) + "\n"


def _fmt_delta(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, (int, float)):
        sign = "+" if value >= 0 else ""
        return f"{sign}{value:.3f}"
    return str(value)


def write_reports(report: dict[str, Any], results_dir: Path) -> dict[str, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / "results.json"
    md_path = results_dir / "report.md"
    json_path.write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
