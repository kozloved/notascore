"""Named baseline save and comparison with configurable regression thresholds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.defaults import BASELINE_F1_EPSILON, PRIMARY_METRIC
from evaluation.corpus import PACKAGE_DIR

BASELINES_DIR = PACKAGE_DIR / "baselines"


def baseline_path(name: str, root: Path | None = None) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.strip())
    if not safe:
        raise ValueError("Baseline name is empty")
    base = Path(root) if root is not None else BASELINES_DIR
    return base / f"{safe}.json"


def save_baseline(
    report: dict[str, Any],
    name: str,
    *,
    root: Path | None = None,
) -> Path:
    path = baseline_path(name, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "timestamp": report.get("timestamp"),
        "git": report.get("git"),
        "branch": report.get("branch"),
        "split": report.get("split"),
        "aggregate": report.get("aggregate"),
        "cases": report.get("cases"),
    }
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def load_baseline(name: str, *, root: Path | None = None) -> dict[str, Any]:
    path = baseline_path(name, root=root)
    if not path.is_file():
        raise FileNotFoundError(f"Baseline not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _case_metric(row: dict[str, Any], key: str = PRIMARY_METRIC) -> float | None:
    if key in row and isinstance(row.get(key), (int, float)):
        return float(row[key])
    notes = row.get("notes") or {}
    value = notes.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    # Alias: onset_pitch_f1 stored under notes
    if key == "onset_pitch_f1":
        value = notes.get("onset_pitch_f1") or notes.get("f1")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def classify_case(
    current: float | None,
    baseline: float | None,
    *,
    epsilon: float = BASELINE_F1_EPSILON,
) -> str:
    if baseline is None and current is None:
        return "UNCHANGED"
    if baseline is None:
        return "NEW"
    if current is None:
        return "REGRESSED"
    delta = current - baseline
    if abs(delta) <= epsilon:
        return "UNCHANGED"
    if delta > 0:
        return "IMPROVED"
    return "REGRESSED"


def compare_to_baseline(
    cases: list[dict[str, Any]],
    baseline: dict[str, Any],
    *,
    epsilon: float = BASELINE_F1_EPSILON,
    metric: str = PRIMARY_METRIC,
) -> dict[str, Any]:
    prev_rows = {
        row["id"]: row
        for row in baseline.get("cases") or []
        if row.get("status") == "ran"
    }
    comparisons: list[dict[str, Any]] = []
    improved = regressed = unchanged = new = 0
    cur_vals: list[float] = []
    base_vals: list[float] = []

    for row in cases:
        if row.get("status") != "ran":
            continue
        cid = row["id"]
        cur = _case_metric(row, metric)
        prev = prev_rows.get(cid)
        base_val = _case_metric(prev, metric) if prev else None
        status = classify_case(cur, base_val, epsilon=epsilon)
        if status == "IMPROVED":
            improved += 1
        elif status == "REGRESSED":
            regressed += 1
        elif status == "NEW":
            new += 1
        else:
            unchanged += 1
        if cur is not None:
            cur_vals.append(cur)
        if base_val is not None:
            base_vals.append(base_val)
        comparisons.append(
            {
                "id": cid,
                "split": row.get("split"),
                "status": status,
                "baseline": base_val,
                "current": cur,
                "delta": None if cur is None or base_val is None else cur - base_val,
            }
        )

    # Cases only in baseline
    for cid, prev in prev_rows.items():
        if any(c["id"] == cid for c in comparisons):
            continue
        comparisons.append(
            {
                "id": cid,
                "split": prev.get("split"),
                "status": "REGRESSED",
                "baseline": _case_metric(prev, metric),
                "current": None,
                "delta": None,
                "detail": "missing_from_current_run",
            }
        )
        regressed += 1

    base_mean = sum(base_vals) / len(base_vals) if base_vals else None
    cur_mean = sum(cur_vals) / len(cur_vals) if cur_vals else None
    return {
        "metric": metric,
        "epsilon": epsilon,
        "baseline_name": baseline.get("name"),
        "counts": {
            "IMPROVED": improved,
            "REGRESSED": regressed,
            "UNCHANGED": unchanged,
            "NEW": new,
        },
        "aggregate": {
            "baseline_mean": base_mean,
            "current_mean": cur_mean,
            "delta": None
            if base_mean is None or cur_mean is None
            else cur_mean - base_mean,
        },
        "cases": comparisons,
        "improvements": [c for c in comparisons if c["status"] == "IMPROVED"],
        "regressions": [c for c in comparisons if c["status"] == "REGRESSED"],
    }
