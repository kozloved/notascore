"""JSON + markdown reports, including a musician-review summary.

Real-world evaluation is observational. It does not define per-song pass/fail
gates and must not be used to tune the production algorithm.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark.report import git_sha


def _fmt_pct(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.3f}"
    return "—"


def _fmt_num(value: Any, digits: int = 1) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return "—"


def build_realworld_report(
    *,
    cases: list[dict[str, Any]],
    repo: Path,
    manifest_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ran = [c for c in cases if c.get("status") == "ran"]
    skipped = [c for c in cases if c.get("status") == "skipped"]
    errors = [c for c in cases if c.get("status") == "error"]
    fallbacks = [
        c for c in ran if (c.get("notation") or {}).get("fallback_used")
    ]
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git_sha(repo),
        "kind": "realworld",
        "manifest": manifest_meta or {},
        "case_count": len(cases),
        "ran": len(ran),
        "skipped": len(skipped),
        "errors": len(errors),
        "fallback_count": len(fallbacks),
        "cases": cases,
    }


def render_metrics_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# NotaScore real-world evaluation",
        "",
        "Observational report. No per-song pass/fail gate. "
        "Do not tune the production algorithm against these recordings.",
        "",
        f"- timestamp: `{report.get('timestamp')}`",
        f"- git: `{report.get('git')}`",
        f"- ran: {report.get('ran')}, skipped: {report.get('skipped')}, "
        f"errors: {report.get('errors')}",
        f"- NotationPlan fallbacks: {report.get('fallback_count')}",
    ]
    manifest = report.get("manifest") or {}
    if manifest.get("manifest_path"):
        lines.append(f"- manifest: `{manifest.get('manifest_path')}`")
    if manifest.get("local_root"):
        lines.append(f"- local root: `{manifest.get('local_root')}`")
    if manifest.get("description"):
        lines.append(f"- {manifest.get('description')}")
    lines += [
        "",
        "| case | status | meter | expected | tempo | F1 (perf) | F1 (score) | hands | plan | fallback |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report.get("cases") or []:
        if row.get("status") != "ran":
            reason = row.get("skip_reason") or row.get("error") or ""
            lines.append(
                f"| {row.get('id')} | {row.get('status')} |  |  |  |  |  |  |  | {reason} |"
            )
            continue
        meter = row.get("meter") or {}
        trans = row.get("transcription") or {}
        score = row.get("score_midi") or {}
        hands = (row.get("hands") or {}).get("versus_reference") or {}
        notation = row.get("notation") or {}
        hand_s = _fmt_pct(hands.get("accuracy")) if hands else "—"
        lines.append(
            "| {id} | ran | {meter} | {exp} | {tempo} | {f1} | {sf1} | {hands} | {plan} | {fb} |".format(
                id=row.get("id"),
                meter=meter.get("predicted") or "—",
                exp=meter.get("expected") or "—",
                tempo=_fmt_num(row.get("tempo_bpm")),
                f1=_fmt_pct(trans.get("f1")),
                sf1=_fmt_pct(score.get("f1")),
                hands=hand_s,
                plan="yes" if notation.get("plan_success") else "no",
                fb="yes" if notation.get("fallback_used") else "no",
            )
        )
    lines.append("")
    return "\n".join(lines)


def render_musician_review(report: dict[str, Any]) -> str:
    lines = [
        "# Musician review sheet",
        "",
        "Listen to the source audio, then inspect the generated MusicXML / MIDI.",
        "These prompts are qualitative. There is no target score per piece.",
        "",
        f"- git: `{report.get('git')}`",
        f"- generated: `{report.get('timestamp')}`",
        "",
    ]
    for row in report.get("cases") or []:
        lines += [
            f"## {row.get('title') or row.get('id')}",
            "",
            f"- id: `{row.get('id')}`",
            f"- status: **{row.get('status')}**",
        ]
        if row.get("instrumentation"):
            lines.append(f"- instrumentation: {row['instrumentation']}")
        if row.get("notes"):
            lines.append(f"- notes: {row['notes']}")
        if row.get("status") != "ran":
            lines.append(f"- reason: {row.get('skip_reason') or row.get('error')}")
            lines.append("")
            continue
        meter = row.get("meter") or {}
        trans = row.get("transcription") or {}
        notation = row.get("notation") or {}
        artifacts = row.get("artifacts") or {}
        hands = row.get("hands") or {}
        decision = row.get("meter_decision") or {}
        lines += [
            f"- predicted meter: **{meter.get('predicted') or '—'}**",
            f"- expected meter (if known): {meter.get('expected') or 'not provided'}",
            f"- tempo: {_fmt_num(row.get('tempo_bpm'))} bpm",
        ]
        if decision:
            lines.append(
                f"- meter decision: {decision.get('reason')} "
                f"(conf={_fmt_pct(decision.get('confidence'))}, "
                f"override={decision.get('was_hint_overridden')})"
            )
        lines += [
            f"- note P/R/F1 vs performance MIDI: "
            f"{_fmt_pct(trans.get('precision'))} / "
            f"{_fmt_pct(trans.get('recall'))} / "
            f"{_fmt_pct(trans.get('f1'))}"
            + (
                f" (n_pred={trans.get('predicted_count')}, "
                f"n_ref={trans.get('reference_count')})"
                if trans.get("reference_count") is not None
                else " (no performance reference)"
            ),
            f"- NotationPlan: {'yes' if notation.get('plan_success') else 'no'}; "
            f"fallback: {'yes' if notation.get('fallback_used') else 'no'}"
            + (
                f" ({notation.get('fallback_reason')})"
                if notation.get("fallback_used")
                else ""
            ),
            f"- MusicXML valid: {notation.get('xml_valid')}; "
            f"measures: {notation.get('measure_count')}",
            f"- hand counts: {hands.get('assignments') or '—'}",
        ]
        versus = hands.get("versus_reference") or {}
        if versus.get("accuracy") is not None:
            lines.append(
                f"- hand accuracy vs labeled MIDI: {_fmt_pct(versus.get('accuracy'))} "
                f"({versus.get('correct')}/{versus.get('total')})"
            )
        lines += [
            "- artifacts:",
            f"  - audio: `{artifacts.get('audio')}`",
            f"  - MusicXML: `{artifacts.get('musicxml')}`",
            f"  - raw MIDI: `{artifacts.get('raw_midi')}`",
            f"  - score MIDI: `{artifacts.get('score_midi')}`",
            "",
            "Reviewer prompts:",
            "- Does the written meter / barline feel right for this recording?",
            "- Are left/right-hand assignments musically plausible?",
            "- Which missing or extra notes actually matter to a player?",
            "- Is the generated score readable, even if F1 is imperfect?",
            "",
        ]
    return "\n".join(lines)


def write_realworld_reports(
    report: dict[str, Any], results_dir: Path
) -> dict[str, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / "realworld.json"
    metrics_path = results_dir / "realworld.md"
    review_path = results_dir / "musician_review.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    metrics_path.write_text(render_metrics_markdown(report), encoding="utf-8")
    review_path.write_text(render_musician_review(report), encoding="utf-8")
    return {
        "json": json_path,
        "metrics": metrics_path,
        "review": review_path,
    }
