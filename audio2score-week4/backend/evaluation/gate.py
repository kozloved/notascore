"""Required evaluation gate: regressions, errors, and empty runs fail."""

from __future__ import annotations

from typing import Any


def gate_decision(
    report: dict[str, Any],
    baseline_comparison: dict[str, Any] | None = None,
    *,
    fail_on_regression: bool = True,
    require_ran: bool = True,
    allow_all_skipped: bool = False,
) -> dict[str, Any]:
    """Return ok/exit_code/reasons. Never treats an all-skipped run as success unless allowed."""
    reasons: list[str] = []
    errors = int(report.get("errors") or 0)
    ran = int(report.get("ran") or 0)
    skipped = int(report.get("skipped") or 0)
    if errors:
        reasons.append("execution_errors")
    if require_ran and ran == 0:
        if skipped:
            if not allow_all_skipped:
                reasons.append("all_skipped")
        else:
            reasons.append("no_cases_ran")
    if fail_on_regression and baseline_comparison:
        counts = baseline_comparison.get("counts") or {}
        if int(counts.get("REGRESSED") or 0) > 0:
            reasons.append("baseline_regression")
        missing = [
            row
            for row in (baseline_comparison.get("regressions") or [])
            if row.get("detail") == "missing_from_current_run"
        ]
        if missing:
            reasons.append("missing_required_cases")
    passed = not reasons
    return {
        "ok": passed,
        "passed": passed,
        "exit_code": 0 if passed else 1,
        "reasons": reasons,
        "ran": ran,
        "skipped": skipped,
        "errors": errors,
    }
