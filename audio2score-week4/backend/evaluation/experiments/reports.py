"""Serialize experiment results and build Checkpoint 9A reports."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from evaluation.experiments.metrics import (
    CaseExperimentMetrics,
    ExperimentAggregate,
    rank_experiments,
)


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def save_case_result(run_dir: Path, metrics: CaseExperimentMetrics) -> Path:
    out = run_dir / metrics.experiment / metrics.case_id / "metrics.json"
    return write_json(out, metrics.to_dict())


def save_experiment_summary(
    run_dir: Path,
    experiment: str,
    aggregate: ExperimentAggregate,
    cases: Sequence[CaseExperimentMetrics],
) -> Path:
    payload = {
        "aggregate": aggregate.to_dict(),
        "cases": [c.to_dict() for c in cases],
    }
    return write_json(run_dir / experiment / "summary.json", payload)


def save_run_manifest(run_dir: Path, manifest: dict[str, Any]) -> Path:
    return write_json(run_dir / "run_manifest.json", manifest)


def save_ranking(run_dir: Path, aggregates: Sequence[ExperimentAggregate]) -> Path:
    ranked = rank_experiments(aggregates)
    rows = []
    for i, a in enumerate(ranked, start=1):
        rows.append(
            {
                "rank": i,
                "experiment": a.experiment,
                "mean_f1": a.experiment_mean_f1,
                "delta_f1": a.delta_mean_f1,
                "precision": a.mean_precision,
                "recall": a.mean_recall,
                "fp": a.total_fp,
                "fn": a.total_fn,
                "regressions": a.regression_count,
                "promising": a.promising,
            }
        )
    return write_json(run_dir / "ranking.json", {"ranking": rows})


def _fmt(v: float | None, digits: int = 3) -> str:
    if v is None:
        return "—"
    return f"{v:.{digits}f}"


def _fmt_delta(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:+.3f}"


def build_markdown_report(
    *,
    run_id: str,
    manifest: dict[str, Any],
    aggregates: Sequence[ExperimentAggregate],
    cases_by_experiment: dict[str, list[CaseExperimentMetrics]],
    baseline_validation: dict[str, Any] | None,
    limited_corpus: bool,
) -> str:
    ranked = rank_experiments(aggregates)
    lines: list[str] = []
    lines.append("# Checkpoint 9A — Transcription Experiments")
    lines.append("")
    lines.append(f"**Run ID:** `{run_id}`  ")
    lines.append(f"**Generated:** {manifest.get('timestamp', '')}  ")
    lines.append(f"**Git:** `{manifest.get('git_branch', '')}` @ `{manifest.get('git_commit', '')}`  ")
    lines.append(f"**Basic Pitch:** `{manifest.get('basic_pitch_version', 'unknown')}`  ")
    lines.append("")
    if limited_corpus:
        lines.append("> **LIMITED DEVELOPMENT CORPUS** — only a handful of real cases.")
        lines.append("> Do not overfit. Treat rankings as directional evidence for Checkpoint 9B.")
        lines.append("")

    # Executive summary
    lines.append("## Executive Summary")
    lines.append("")
    baseline = next((a for a in aggregates if a.experiment == "basic_pitch_baseline"), None)
    best = ranked[0] if ranked else None
    promising = [a for a in ranked if a.promising and a.experiment != "basic_pitch_baseline"]
    lines.append(
        f"Tested {len(aggregates)} configurations on "
        f"{manifest.get('n_cases', '?')} development cases "
        f"({', '.join(manifest.get('corpus_cases', []))})."
    )
    if baseline:
        lines.append(
            f"Baseline macro mean onset+pitch F1 = **{_fmt(baseline.experiment_mean_f1)}**."
        )
    if promising:
        names = ", ".join(a.experiment for a in promising[:3])
        lines.append(f"Promising configurations (conservative rule): {names}.")
    else:
        lines.append(
            "No configuration met the conservative robustness criteria for a production change."
        )
    if best and baseline and best.experiment != "basic_pitch_baseline":
        lines.append(
            f"Top-ranked by mean F1: `{best.experiment}` "
            f"(F1={_fmt(best.experiment_mean_f1)}, Δ={_fmt_delta(best.delta_mean_f1)})."
        )
    lines.append("")

    # Baseline validation
    lines.append("## Baseline Validation")
    lines.append("")
    if baseline_validation:
        status = (
            "YES — experiment baseline approximately reproduces Checkpoint 8"
            if baseline_validation.get("reproduces_checkpoint8")
            else "NO — material mismatch; investigate before trusting rankings"
        )
        lines.append(f"**Reproduces Checkpoint 8:** {status}")
        lines.append("")
        lines.append("| Case | F1 | Expected | Pred notes | Expected pred | Status |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for d in baseline_validation.get("details", []):
            lines.append(
                f"| {d.get('case_id')} | {_fmt(d.get('onset_pitch_f1'))} | "
                f"{_fmt(d.get('expected_onset_pitch_f1'))} | "
                f"{d.get('predicted_note_count')} | {d.get('expected_predicted_note_count')} | "
                f"{d.get('status')} |"
            )
    else:
        lines.append("Baseline validation not run.")
    lines.append("")

    # Matrix
    lines.append("## Experiment Matrix")
    lines.append("")
    for cfg in manifest.get("configurations", []):
        skip = cfg.get("skip_reason")
        mark = f" _(skipped: {skip})_" if skip else ""
        lines.append(
            f"- `{cfg['name']}` [{cfg.get('axis')}] — {cfg.get('description', '')}{mark}"
        )
    lines.append("")

    # Ranking
    lines.append("## Aggregate Ranking")
    lines.append("")
    lines.append(
        "| Rank | Experiment | Mean F1 | Δ F1 | Precision | Recall | FP | FN | Regressions |"
    )
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for i, a in enumerate(ranked, start=1):
        lines.append(
            f"| {i} | `{a.experiment}` | {_fmt(a.experiment_mean_f1)} | "
            f"{_fmt_delta(a.delta_mean_f1)} | {_fmt(a.mean_precision)} | "
            f"{_fmt(a.mean_recall)} | {a.total_fp} | {a.total_fn} | {a.regression_count} |"
        )
    lines.append("")

    # Per-case
    lines.append("## Per-Case Results")
    lines.append("")
    case_ids = sorted(
        {
            c.case_id
            for cases in cases_by_experiment.values()
            for c in cases
        }
    )
    for case_id in case_ids:
        lines.append(f"### {case_id}")
        lines.append("")
        lines.append(
            "| Experiment | Pred | Ref | Onset F1 | Onset+Pitch F1 | P | R | FP | FN | Pitch err | Frag | Merge | Dup | ΔF1 |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        base_f1 = None
        base_cases = cases_by_experiment.get("basic_pitch_baseline", [])
        for bc in base_cases:
            if bc.case_id == case_id:
                base_f1 = bc.onset_pitch_f1
                break
        for a in ranked:
            cases = cases_by_experiment.get(a.experiment, [])
            m = next((c for c in cases if c.case_id == case_id), None)
            if m is None:
                continue
            delta = None if base_f1 is None else m.onset_pitch_f1 - base_f1
            lines.append(
                f"| `{m.experiment}` | {m.predicted_note_count} | {m.reference_note_count} | "
                f"{_fmt(m.onset_f1)} | {_fmt(m.onset_pitch_f1)} | "
                f"{_fmt(m.onset_pitch_precision)} | {_fmt(m.onset_pitch_recall)} | "
                f"{m.false_positives} | {m.false_negatives} | {m.pitch_errors} | "
                f"{m.fragmented_notes} | {m.merged_notes} | {m.duplicate_notes} | "
                f"{_fmt_delta(delta)} |"
            )
        lines.append("")

    # Axis sections
    def _axis_section(title: str, axis_prefix: tuple[str, ...]) -> None:
        lines.append(f"## {title}")
        lines.append("")
        subset = [a for a in ranked if a.experiment.startswith(axis_prefix)]
        if not subset:
            lines.append("No experiments in this axis.")
            lines.append("")
            return
        for a in subset:
            lines.append(
                f"- `{a.experiment}`: mean F1={_fmt(a.experiment_mean_f1)} "
                f"(Δ={_fmt_delta(a.delta_mean_f1)}), promising={a.promising} — {a.promising_reason}"
            )
        lines.append("")

    _axis_section("Audio Preprocessing Results", ("A",))
    _axis_section("Basic Pitch Parameter Results", ("B",))
    _axis_section("Combined Experiments", ("C",))

    # Error taxonomy
    lines.append("## Error Taxonomy Changes")
    lines.append("")
    lines.append(
        "| Experiment | ΔFN | ΔFP | ΔPitch | ΔFrag | ΔMerge | ΔDup |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for a in ranked:
        if a.experiment == "basic_pitch_baseline":
            continue
        td = a.taxonomy_delta
        lines.append(
            f"| `{a.experiment}` | {td.get('false_negatives', 0):+d} | "
            f"{td.get('false_positives', 0):+d} | {td.get('pitch_errors', 0):+d} | "
            f"{td.get('fragmented', 0):+d} | {td.get('merged', 0):+d} | "
            f"{td.get('duplicates', 0):+d} |"
        )
    lines.append("")

    # Best candidate
    lines.append("## Best Candidate")
    lines.append("")
    if promising:
        top = promising[0]
        lines.append(
            f"`{top.experiment}` is the strongest candidate under the robustness rule "
            f"(mean F1={_fmt(top.experiment_mean_f1)}, Δ={_fmt_delta(top.delta_mean_f1)}, "
            f"regressions={top.regression_count})."
        )
        lines.append("")
        lines.append(
            "Even so, with a LIMITED DEVELOPMENT CORPUS this is evidence for Checkpoint 9B, "
            "not an automatic production flip."
        )
    else:
        lines.append("**NO CONFIGURATION CHANGE JUSTIFIED** based on robust multi-case improvement.")
        if best and best.experiment != "basic_pitch_baseline":
            lines.append(
                f"Highest mean F1 was `{best.experiment}` "
                f"(Δ={_fmt_delta(best.delta_mean_f1)}), but it failed the robustness criteria: "
                f"{best.promising_reason}."
            )
    lines.append("")

    lines.append("## No-Winner Scenario")
    lines.append("")
    if not promising:
        lines.append("NO CONFIGURATION CHANGE JUSTIFIED")
    else:
        lines.append(
            "A candidate exists, but corpus size remains a blocker for high-confidence adoption."
        )
    lines.append("")

    lines.append("## Recommended Checkpoint 9B")
    lines.append("")
    recommendation = manifest.get("recommendation", "B")
    labels = {
        "A": "Adopt best configuration into production",
        "B": "Expand development corpus first",
        "C": "Test alternative transcription backend",
        "D": "Investigate audio/source characteristics",
    }
    lines.append(f"**Choice: {recommendation} — {labels.get(recommendation, '')}**")
    lines.append("")
    lines.append(manifest.get("recommendation_rationale", ""))
    lines.append("")

    lines.append("## Reproducibility")
    lines.append("")
    lines.append("```")
    lines.append(json.dumps({k: manifest[k] for k in (
        "run_id", "timestamp", "git_commit", "git_branch", "split",
        "corpus_cases", "basic_pitch_version", "python_version",
    ) if k in manifest}, indent=2))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def write_run_report(
    run_dir: Path,
    *,
    run_id: str,
    manifest: dict[str, Any],
    aggregates: Sequence[ExperimentAggregate],
    cases_by_experiment: dict[str, list[CaseExperimentMetrics]],
    baseline_validation: dict[str, Any] | None,
    limited_corpus: bool,
) -> Path:
    md = build_markdown_report(
        run_id=run_id,
        manifest=manifest,
        aggregates=aggregates,
        cases_by_experiment=cases_by_experiment,
        baseline_validation=baseline_validation,
        limited_corpus=limited_corpus,
    )
    path = run_dir / "report.md"
    path.write_text(md, encoding="utf-8")
    return path


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
