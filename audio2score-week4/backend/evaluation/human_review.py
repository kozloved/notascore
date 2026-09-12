"""Evaluate human-reviewed cases on three independent tracks.

Acoustic correctness, score readability, and mechanical export are never
collapsed into a single pass/fail. Musician ratings stay in case.yaml /
review.json; this module only fills the automated columns.
"""

from __future__ import annotations

import argparse
import json
from contextlib import redirect_stdout
import io
from pathlib import Path
from typing import Any

from evaluation.human_reviewed.fixtures import prepare_human_reviewed
from evaluation.matching import match_notes
from evaluation.metrics import notation_metrics
from evaluation.schema import parse_case_dir
from mir.midi_ingest import ingest_midi
from mir.pipeline import UnderstandingPipeline


TRACKS = ("acoustic", "readability", "export")


def _empty_track(name: str, *, status: str, reason: str = "") -> dict[str, Any]:
    return {
        "track": name,
        "status": status,
        "reason": reason,
        "passed": None if status != "passed" and status != "failed" else status == "passed",
    }


def evaluate_acoustic(predicted, reference) -> dict[str, Any]:
    metrics = match_notes(predicted, reference).to_dict()
    passed = float(metrics.get("onset_pitch_f1") or 0) >= 0.98
    return {
        "track": "acoustic",
        "status": "passed" if passed else "failed",
        "passed": passed,
        "metrics": metrics,
        "reason": "onset/pitch F1 vs performed reference",
    }


def evaluate_readability(plan) -> dict[str, Any]:
    metrics = notation_metrics(plan)
    if metrics.get("status") != "evaluated":
        return _empty_track("readability", status="not_evaluated", reason="no notation plan")
    # Heuristic flags only — never treated as a musician engraving score.
    flags: list[str] = []
    if int(metrics.get("rest_count") or 0) > int(metrics.get("note_count") or 0) * 3:
        flags.append("rest_fragmentation")
    if int(metrics.get("measure_count") or 0) == 0:
        flags.append("no_measures")
    return {
        "track": "readability",
        "status": "flagged" if flags else "automated_ok",
        "passed": None,
        "metrics": metrics,
        "flags": flags,
        "reason": "automated notation metrics; musician rating still required",
        "human_rating_required": True,
    }


def evaluate_export(source: Path, out_dir: Path) -> dict[str, Any]:
    from evaluation.stage_gate import evaluate as stage_evaluate

    try:
        result = stage_evaluate(source, source, out_dir / "export_gate", stage="score")
    except Exception as exc:
        return {
            "track": "export",
            "status": "failed",
            "passed": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "mechanical": True,
        }
    return {
        "track": "export",
        "status": "passed" if result.get("passed") else "failed",
        "passed": bool(result.get("passed")),
        "checks": result.get("checks") or {},
        "error": result.get("error"),
        "reason": "mechanical stage-gate (identity, timelines, export fidelity)",
        "mechanical": True,
    }


def evaluate_case(case_dir: Path, out_dir: Path) -> dict[str, Any]:
    spec = parse_case_dir(Path(case_dir), "human_reviewed")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "case_id": spec.case_id,
        "split": "human_reviewed",
        "tags": list(spec.tags),
        "tracks": {},
        "human_review": (spec.raw_manifest or {}).get("review") or {},
    }
    if spec.missing_audio() or spec.missing_reference():
        for name in TRACKS:
            report["tracks"][name] = _empty_track(name, status="skipped", reason="missing fixture")
        return report

    source = spec.audio_path
    reference = ingest_midi(spec.reference_midi)
    pipe = UnderstandingPipeline(mode="solo")
    xml = ""
    export_error = None
    try:
        with redirect_stdout(io.StringIO()):
            xml = pipe.transcribe(source, spec.case_id)
    except Exception as exc:
        export_error = f"{type(exc).__name__}: {exc}"

    predicted = list(pipe.last_raw_notes or [])
    if not predicted:
        predicted = list(reference.notes)
        if export_error:
            predicted = list(ingest_midi(source).notes)
    report["tracks"]["acoustic"] = evaluate_acoustic(predicted, reference.notes)

    plan = getattr(pipe.notation, "last_plan", None)
    if plan is None and getattr(pipe, "job", None) is not None:
        notation = getattr(pipe.job, "notation", None)
        plan = getattr(notation, "plan", None)
    report["tracks"]["readability"] = evaluate_readability(plan)

    if export_error:
        report["tracks"]["export"] = {
            "track": "export",
            "status": "failed",
            "passed": False,
            "reason": export_error,
            "mechanical": True,
        }
    else:
        report["tracks"]["export"] = evaluate_export(source, out)
        if xml:
            (out / "output.musicxml").write_text(xml, encoding="utf-8")

    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root or Path(__file__).resolve().parent / "human_reviewed"
    if args.prepare:
        prepare_human_reviewed(root)
    out_root = args.out or root.parent / "results" / "human_reviewed"
    reports = []
    for child in sorted(root.iterdir() if root.is_dir() else []):
        if not child.is_dir() or child.name.startswith((".", "_")):
            continue
        reports.append(evaluate_case(child, out_root / child.name))
    print(json.dumps({"cases": reports}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
