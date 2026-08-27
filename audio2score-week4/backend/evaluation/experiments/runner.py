"""CLI runner for Checkpoint 9A transcription experiments.

Usage (from audio2score-week4/backend):

  python -m evaluation.experiments.runner --list
  python -m evaluation.experiments.runner --split development --experiment basic_pitch_baseline
  python -m evaluation.experiments.runner --split development --experiment all --save-results --report
"""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.corpus import PACKAGE_DIR, discover_cases
from evaluation.defaults import SPLITS
from evaluation.experiments.config import ExperimentConfig
from evaluation.experiments.metrics import (
    CaseExperimentMetrics,
    aggregate_experiment,
    compare_to_checkpoint8_baseline,
    compute_case_metrics,
    rank_experiments,
)
from evaluation.experiments.preprocess import apply_preprocess
from evaluation.experiments.registry import (
    get_experiment,
    list_experiments,
    resolve_experiment_selection,
)
from evaluation.experiments.reports import (
    save_case_result,
    save_experiment_summary,
    save_ranking,
    save_run_manifest,
    utc_timestamp,
    write_run_report,
)
from evaluation.experiments.transcription import (
    ExperimentBasicPitchAdapter,
    basic_pitch_version,
)
from evaluation.normalize import normalize_reference_midi
from evaluation.schema import CaseSpec

RESULTS_ROOT = PACKAGE_DIR / "experiment_results"
BASELINE_NAME = "basic_pitch_baseline"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "NotaScore Checkpoint 9A transcription experiment matrix. "
            "Opt-in only — does not change production defaults."
        )
    )
    p.add_argument("--list", action="store_true", help="List registered experiments")
    p.add_argument("--split", choices=SPLITS, default="development")
    p.add_argument("--case", default=None, help="Optional single case id")
    p.add_argument(
        "--experiment",
        default=BASELINE_NAME,
        help="Experiment name or 'all'",
    )
    p.add_argument("--save-results", action="store_true", default=True)
    p.add_argument("--no-save-results", action="store_false", dest="save_results")
    p.add_argument("--report", action="store_true", default=True)
    p.add_argument("--no-report", action="store_false", dest="report")
    p.add_argument("--results-dir", type=Path, default=RESULTS_ROOT)
    p.add_argument("--run-id", default=None)
    p.add_argument("--corpus-root", type=Path, default=None)
    p.add_argument(
        "--include-tempo-diagnostic",
        action="store_true",
        default=True,
        help="Record beat-tracker tempo as metadata only (default on)",
    )
    p.add_argument(
        "--no-tempo-diagnostic",
        action="store_false",
        dest="include_tempo_diagnostic",
    )
    return p.parse_args(argv)


def _git_info() -> dict[str, str]:
    info = {"git_commit": "unknown", "git_branch": "unknown"}
    try:
        info["git_commit"] = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=BACKEND_ROOT, text=True
            ).strip()
        )
        info["git_branch"] = (
            subprocess.check_output(
                ["git", "branch", "--show-current"], cwd=BACKEND_ROOT, text=True
            ).strip()
        )
    except Exception:
        pass
    return info


def _beat_tracker_tempo(audio_path: Path) -> float | None:
    try:
        from audio_engine.beat_tracker import BeatTracker
        from audio_engine.normalizer import AudioNormalizer

        audio = AudioNormalizer().normalize(audio_path)
        tm = BeatTracker().track(audio)
        if tm is None:
            return None
        if hasattr(tm, "bpm"):
            return float(tm.bpm)
        if hasattr(tm, "points") and tm.points:
            return float(tm.bpm_at(0.0))
        return None
    except Exception:
        return None


def run_one_case(
    case: CaseSpec,
    config: ExperimentConfig,
    *,
    work_dir: Path,
    include_tempo_diagnostic: bool = True,
) -> CaseExperimentMetrics:
    if case.missing_audio():
        raise FileNotFoundError(f"Missing audio for case {case.case_id}")
    if case.missing_raw_reference():
        raise FileNotFoundError(f"Missing reference_raw for case {case.case_id}")

    assert case.audio_path is not None
    assert case.reference_raw_midi is not None

    case_work = work_dir / config.name / case.case_id
    case_work.mkdir(parents=True, exist_ok=True)
    wav_out = case_work / "preprocessed.wav"

    prep = apply_preprocess(case.audio_path, config.preprocess, out_path=wav_out)
    adapter = ExperimentBasicPitchAdapter()
    tx = adapter.transcribe(prep.path or wav_out, config.transcription)

    ref = normalize_reference_midi(case.reference_raw_midi)
    tempo = None
    if include_tempo_diagnostic:
        tempo = _beat_tracker_tempo(case.audio_path)

    metrics = compute_case_metrics(
        case_id=case.case_id,
        experiment=config.name,
        reference=ref.notes,
        predicted=tx.notes,
        preprocess=prep.to_dict(),
        transcription_params=tx.params,
        beat_tracker_tempo_bpm=tempo,
        expected_tempo_bpm=case.expected_tempo_bpm,
    )
    return metrics


def run_experiments(
    configs: list[ExperimentConfig],
    cases: list[CaseSpec],
    *,
    run_dir: Path,
    save_results: bool = True,
    include_tempo_diagnostic: bool = True,
) -> tuple[
    dict[str, list[CaseExperimentMetrics]],
    list[Any],
    dict[str, Any] | None,
]:
    cases_by_exp: dict[str, list[CaseExperimentMetrics]] = {}
    work_dir = run_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # Ensure baseline is available for deltas when running subsets.
    names = {c.name for c in configs}
    if BASELINE_NAME not in names and any(c.name != BASELINE_NAME for c in configs):
        # Still need baseline metrics for comparison when possible.
        pass

    for config in configs:
        if config.is_skipped:
            print(f"[experiments] skip {config.name}: {config.skip_reason}")
            continue
        print(f"[experiments] {config.name} ({config.axis}) ...", flush=True)
        case_metrics: list[CaseExperimentMetrics] = []
        for case in cases:
            print(f"  case {case.case_id} ...", flush=True)
            m = run_one_case(
                case,
                config,
                work_dir=work_dir,
                include_tempo_diagnostic=include_tempo_diagnostic,
            )
            case_metrics.append(m)
            if save_results:
                save_case_result(run_dir, m)
            print(
                f"    onset+pitch F1={m.onset_pitch_f1:.3f} "
                f"pred={m.predicted_note_count} ref={m.reference_note_count} "
                f"FP={m.false_positives} FN={m.false_negatives}"
            )
        cases_by_exp[config.name] = case_metrics

    baseline_by_case: dict[str, CaseExperimentMetrics] = {}
    if BASELINE_NAME in cases_by_exp:
        baseline_by_case = {m.case_id: m for m in cases_by_exp[BASELINE_NAME]}

    aggregates = []
    for name, cms in cases_by_exp.items():
        agg = aggregate_experiment(
            name,
            cms,
            baseline_by_case=None if name == BASELINE_NAME else baseline_by_case or None,
        )
        aggregates.append(agg)
        if save_results:
            save_experiment_summary(run_dir, name, agg, cms)

    baseline_validation = None
    if BASELINE_NAME in cases_by_exp:
        baseline_validation = compare_to_checkpoint8_baseline(
            cases_by_exp[BASELINE_NAME]
        )
        if save_results:
            from evaluation.experiments.reports import write_json

            write_json(run_dir / "baseline_validation.json", baseline_validation)

    if save_results:
        save_ranking(run_dir, aggregates)

    return cases_by_exp, aggregates, baseline_validation


def choose_recommendation(
    aggregates: list[Any],
    *,
    limited_corpus: bool,
    baseline_ok: bool,
) -> tuple[str, str]:
    ranked = rank_experiments(aggregates)
    promising = [
        a
        for a in ranked
        if a.promising and a.experiment != BASELINE_NAME
    ]
    if limited_corpus:
        if promising:
            return (
                "B",
                "A configuration looks directionally better, but the development "
                "corpus has too few real cases to justify a production change. "
                "Expand the corpus, then re-run the matrix before adopting.",
            )
        return (
            "B",
            "No robust winner on the tiny development corpus. Expand real DAW "
            "cases first; optionally pursue alternative backends (C) after more data.",
        )
    if not baseline_ok:
        return (
            "D",
            "Baseline did not reproduce Checkpoint 8; investigate audio/source "
            "or environment drift before changing production.",
        )
    if promising:
        return (
            "A",
            f"Adopt `{promising[0].experiment}` after confirmation on an expanded set.",
        )
    return (
        "C",
        "No Basic Pitch configuration produced robust gains; test an alternative "
        "transcription backend (classical_dsp / MT3) next.",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list:
        print("Registered experiments:")
        for cfg in list_experiments(include_skipped=True):
            flag = " [SKIP]" if cfg.is_skipped else ""
            print(f"  {cfg.name:40s} [{cfg.axis}]{flag}")
            print(f"    {cfg.description}")
            if cfg.skip_reason:
                print(f"    skip: {cfg.skip_reason}")
        return 0

    root = Path(args.corpus_root).resolve() if args.corpus_root else None
    cases = discover_cases(split=args.split, case_id=args.case, root=root)
    # Transcription experiments require raw reference
    cases = [c for c in cases if not c.missing_audio() and not c.missing_raw_reference()]
    if not cases:
        print("[experiments] no runnable cases found")
        return 1

    limited_corpus = len(cases) < 5
    if limited_corpus:
        print(
            f"[experiments] LIMITED DEVELOPMENT CORPUS: {len(cases)} cases — "
            "do not overfit"
        )

    try:
        configs = resolve_experiment_selection(args.experiment)
    except KeyError as exc:
        print(f"[experiments] {exc}")
        return 2

    # When running a non-baseline single experiment, also run baseline for deltas.
    if args.experiment != "all" and args.experiment != BASELINE_NAME:
        baseline = get_experiment(BASELINE_NAME)
        configs = [baseline, *configs]

    run_id = args.run_id or utc_timestamp()
    run_dir = Path(args.results_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    git = _git_info()
    print(
        f"[experiments] run_id={run_id} experiments={len(configs)} "
        f"cases={len(cases)} commit={git['git_commit'][:12]}"
    )

    cases_by_exp, aggregates, baseline_validation = run_experiments(
        configs,
        cases,
        run_dir=run_dir,
        save_results=args.save_results,
        include_tempo_diagnostic=args.include_tempo_diagnostic,
    )

    baseline_ok = bool(
        baseline_validation and baseline_validation.get("reproduces_checkpoint8")
    )
    if baseline_validation and not baseline_ok:
        print(
            "[experiments] WARNING: baseline does not approximately reproduce "
            "Checkpoint 8 — STOP and investigate before trusting rankings."
        )
        for d in baseline_validation.get("details", []):
            print(f"  {d}")

    recommendation, rationale = choose_recommendation(
        aggregates, limited_corpus=limited_corpus, baseline_ok=baseline_ok
    )

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "timestamp": utc_timestamp(),
        "split": args.split,
        "corpus_cases": [c.case_id for c in cases],
        "n_cases": len(cases),
        "limited_development_corpus": limited_corpus,
        "configurations": [c.to_dict() for c in list_experiments(include_skipped=True)],
        "executed": list(cases_by_exp.keys()),
        "basic_pitch_version": basic_pitch_version(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "recommendation": recommendation,
        "recommendation_rationale": rationale,
        "notes": [
            "Experiments compare notes in absolute time; no half-tempo correction.",
            "Beat-tracker tempo is diagnostic metadata only.",
            "Production Basic Pitch defaults were not modified.",
        ],
        **git,
    }
    if args.save_results:
        save_run_manifest(run_dir, manifest)

    if args.report:
        report_path = write_run_report(
            run_dir,
            run_id=run_id,
            manifest=manifest,
            aggregates=aggregates,
            cases_by_experiment=cases_by_exp,
            baseline_validation=baseline_validation,
            limited_corpus=limited_corpus,
        )
        print(f"[experiments] report: {report_path}")

    ranked = rank_experiments(aggregates)
    print("[experiments] ranking (mean onset+pitch F1):")
    for i, a in enumerate(ranked, start=1):
        print(
            f"  {i:2d}. {a.experiment:40s} F1={a.experiment_mean_f1:.3f} "
            f"Δ={a.delta_mean_f1 if a.delta_mean_f1 is not None else 0:+.3f} "
            f"reg={a.regression_count} promising={a.promising}"
        )
    print(f"[experiments] recommendation: {recommendation} — {rationale}")
    return 0 if baseline_ok or BASELINE_NAME not in cases_by_exp else 0


if __name__ == "__main__":
    raise SystemExit(main())
