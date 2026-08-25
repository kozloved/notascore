"""Write latest.json / latest.md and compare against a baseline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark.evaluate import MODE_LABELS

HAND_DROP = 0.05


def git_sha(repo: Path) -> str:
    try:
        import subprocess

        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=str(repo),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def compare_to_baseline(
    current_cases: list[dict[str, Any]],
    baseline: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not baseline:
        return []
    prev_rows = {
        row["id"]: row
        for row in baseline.get("cases") or []
        if not row.get("skipped")
    }
    regressions: list[dict[str, Any]] = []
    for row in current_cases:
        if row.get("skipped"):
            continue
        prev = prev_rows.get(row["id"])
        if prev is None:
            continue
        if prev.get("passed") and not row.get("passed"):
            regressions.append(
                {
                    "id": row["id"],
                    "kind": "became_invalid",
                    "detail": ",".join(row.get("flags") or []),
                }
            )
        prev_hands = (prev.get("hands") or {}).get("accuracy")
        cur_hands = (row.get("hands") or {}).get("accuracy")
        if (
            prev_hands is not None
            and cur_hands is not None
            and cur_hands < float(prev_hands) - HAND_DROP
        ):
            regressions.append(
                {
                    "id": row["id"],
                    "kind": "hand_accuracy_drop",
                    "detail": f"{prev_hands:.3f} -> {cur_hands:.3f}",
                }
            )
        prev_false = int((prev.get("cleaning") or {}).get("false_removals") or 0)
        cur_false = int((row.get("cleaning") or {}).get("false_removals") or 0)
        if cur_false > prev_false:
            regressions.append(
                {
                    "id": row["id"],
                    "kind": "more_legitimate_notes_removed",
                    "detail": f"{prev_false} -> {cur_false}",
                }
            )
        if not (prev.get("notation") or {}).get("fallback_used") and (
            row.get("notation") or {}
        ).get("fallback_used"):
            regressions.append(
                {
                    "id": row["id"],
                    "kind": "new_notation_fallback",
                    "detail": (row.get("notation") or {}).get("fallback_reason"),
                }
            )
        if (prev.get("notation") or {}).get("xml_valid") and not (
            row.get("notation") or {}
        ).get("xml_valid"):
            regressions.append(
                {
                    "id": row["id"],
                    "kind": "musicxml_became_invalid",
                    "detail": ",".join((row.get("notation") or {}).get("xml_errors") or []),
                }
            )
    return regressions


def build_report(
    *,
    mode: str,
    cases: list[dict[str, Any]],
    repo: Path,
    baseline: dict[str, Any] | None = None,
    extra_modes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    active = [c for c in cases if not c.get("skipped")]
    skipped = [c for c in cases if c.get("skipped")]
    passed = [c for c in active if c.get("passed")]
    failed = [c for c in active if not c.get("passed")]
    fallbacks = [
        c
        for c in active
        if (c.get("notation") or {}).get("fallback_used")
    ]
    regressions = compare_to_baseline(active, baseline)
    report = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git": git_sha(repo),
        "mode": mode,
        "mode_label": MODE_LABELS.get(mode, mode),
        "case_count": len(active),
        "passed": len(passed),
        "failed": len(failed),
        "skipped": len(skipped),
        "fallback_count": len(fallbacks),
        "regressions": regressions,
        "baseline_git": (baseline or {}).get("git"),
        "cases": cases,
        "extra_modes": extra_modes or [],
        "ok": len(failed) == 0 and len(regressions) == 0,
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# NotaScore benchmark",
        "",
        f"- timestamp: `{report['timestamp']}`",
        f"- git: `{report.get('git')}`",
        f"- mode: **{report.get('mode_label') or report.get('mode')}** (`{report.get('mode')}`)",
        f"- cases: {report.get('case_count')} "
        f"(pass {report.get('passed')}, fail {report.get('failed')}, "
        f"skip {report.get('skipped')})",
        f"- fallback count: {report.get('fallback_count')}",
        f"- regressions vs baseline: {len(report.get('regressions') or [])}",
    ]
    if report.get("baseline_git"):
        lines.append(f"- baseline git: `{report['baseline_git']}`")
    lines += ["", "## Results", ""]
    if report.get("ok"):
        lines.append("Overall: **PASS**")
    else:
        lines.append("Overall: **FAIL**")
    lines += [
        "",
        "| case | category | pass | hands | voices | meter | plan | fallback | F1 | flags |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in report.get("cases") or []:
        if row.get("skipped"):
            lines.append(
                f"| {row['id']} | {row['category']} | skip |  |  |  |  |  |  | {row.get('skip_reason')} |"
            )
            continue
        hands = row.get("hands") or {}
        voices = row.get("voices") or {}
        meter = row.get("meter") or {}
        notation = row.get("notation") or {}
        trans = row.get("transcription") or {}
        hand_s = (
            f"{hands['accuracy']:.2f}" if hands.get("accuracy") is not None else "-"
        )
        voice_s = (
            "ok"
            if voices.get("continuity_ok") is True
            else ("fail" if voices.get("continuity_ok") is False else "-")
        )
        meter_s = meter.get("selected") or "-"
        if meter.get("correct") is False:
            meter_s += " ✗"
        meter_eval = (row.get("counts") or {}).get("meter_eval")
        if meter_eval and meter_eval != "STRICT_METER":
            meter_s += f" [{meter_eval}]"
        f1 = trans.get("f1")
        f1_s = f"{f1:.2f}" if isinstance(f1, (int, float)) else "-"
        lines.append(
            "| {id} | {cat} | {ok} | {hands} | {voices} | {meter} | {plan} | {fb} | {f1} | {flags} |".format(
                id=row["id"],
                cat=row["category"],
                ok="PASS" if row.get("passed") else "FAIL",
                hands=hand_s,
                voices=voice_s,
                meter=meter_s,
                plan="yes" if notation.get("plan_success") else "no",
                fb="yes" if notation.get("fallback_used") else "no",
                f1=f1_s,
                flags=",".join(row.get("flags") or []) or "",
            )
        )

    if report.get("regressions"):
        lines += ["", "## Regressions", ""]
        for item in report["regressions"]:
            lines.append(f"- `{item['id']}`: {item['kind']} ({item.get('detail')})")
    else:
        lines += ["", "## Regressions", "", "None.", ""]

    lines += ["", "## Metrics", ""]
    fallbacks = [
        c
        for c in report.get("cases") or []
        if (c.get("notation") or {}).get("fallback_used")
    ]
    lines.append(f"- NotationPlan fallbacks: {len(fallbacks)}")
    if fallbacks:
        for c in fallbacks:
            reason = (c.get("notation") or {}).get("fallback_reason")
            lines.append(f"  - `{c['id']}`: {reason}")
    false_removals = sum(
        int((c.get("cleaning") or {}).get("false_removals") or 0)
        for c in report.get("cases") or []
        if not c.get("skipped")
    )
    lines.append(f"- false legitimate-note removals (sum): {false_removals}")

    for extra in report.get("extra_modes") or []:
        lines += [
            "",
            f"## Additional mode: {extra.get('mode_label') or extra.get('mode')}",
            "",
            f"- cases: {extra.get('case_count')} pass {extra.get('passed')} "
            f"fail {extra.get('failed')} skip {extra.get('skipped')}",
        ]
    lines.append("")
    return "\n".join(lines)


def write_reports(report: dict[str, Any], results_dir: Path) -> tuple[Path, Path]:
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / "latest.json"
    md_path = results_dir / "latest.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
