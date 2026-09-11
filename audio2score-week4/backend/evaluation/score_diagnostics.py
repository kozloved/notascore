"""Local score-complexity diagnostics for production_smoke fixtures.

Missing audio is SKIP. Never fabricates copyrighted recordings.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_DIR.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from evaluation.production_smoke.check import sha256_file
from mir.score_metrics import metrics_from_plan, warnings_from_metrics

SMOKE_DIR = PACKAGE_DIR / "production_smoke"
RESULTS_DIR = PACKAGE_DIR / "results"
CASES_PATH = SMOKE_DIR / "cases.json"

AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aiff", ".aif"}
MIDI_SUFFIXES = {".mid", ".midi"}


def load_cases(path: Path = CASES_PATH) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_fixture(name: str, fixture_dir: Path) -> Path | None:
    direct = fixture_dir / name
    if direct.is_file():
        return direct
    stem = Path(name).stem
    for suffix in (*AUDIO_SUFFIXES, *MIDI_SUFFIXES):
        candidate = fixture_dir / f"{stem}{suffix}"
        if candidate.is_file():
            return candidate
    category = fixture_dir / stem
    if category.is_dir():
        for child in sorted(category.iterdir()):
            if child.suffix.lower() in AUDIO_SUFFIXES | MIDI_SUFFIXES:
                return child
    return None


def copy_job_artifacts(job_dir: Path, dest: Path, job_id: str) -> dict[str, bool]:
    dest.mkdir(parents=True, exist_ok=True)
    names = {
        "raw.mid": f"{job_id}.raw.mid",
        "score.mid": f"{job_id}.score.mid",
        "musicxml": f"{job_id}.musicxml",
        "performance.json": f"{job_id}.performance.json",
        "tempo.json": f"{job_id}.tempo.json",
        "debug.json": f"{job_id}.debug.json",
        "provenance.json": f"{job_id}.provenance.json",
        "candidate_scores.json": f"{job_id}.candidate_scores.json",
        "score_metrics.json": f"{job_id}.score_metrics.json",
    }
    present = {}
    for label, filename in names.items():
        src = job_dir / filename
        present[label] = src.is_file()
        if src.is_file():
            shutil.copy2(src, dest / label if label != "musicxml" else dest / "score.musicxml")
            if label == "musicxml":
                shutil.copy2(src, dest / "musicxml")
    return present


def write_metrics_from_pipeline(pipeline, dest: Path) -> dict:
    plan = getattr(pipeline.notation, "last_plan", None)
    metrics = metrics_from_plan(
        plan,
        source_notes=pipeline.last_raw_notes,
        quantized=pipeline.last_quantized_events,
    )
    metrics["warnings"] = warnings_from_metrics(metrics)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "score_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    if pipeline.last_candidate_scores is not None:
        payload = {
            "interpretation_choice": dict(pipeline.last_interpretation_choice or {}),
            "candidates": list(pipeline.last_candidate_scores),
        }
        (dest / "candidate_scores.json").write_text(
            json.dumps(payload, indent=2) + "\n"
        )
    return metrics


def run_local_midi_case(midi_path: Path, dest: Path, job_id: str = "diag") -> dict:
    from mir.pipeline import UnderstandingPipeline

    dest.mkdir(parents=True, exist_ok=True)
    work = dest / "_work"
    work.mkdir(parents=True, exist_ok=True)
    local = work / midi_path.name
    shutil.copy2(midi_path, local)
    pipeline = UnderstandingPipeline(backend_name="midi")
    pipeline.transcribe_midi(local, job_id)
    job_dir = local.parent / f"bp_{job_id}"
    present = copy_job_artifacts(job_dir, dest, job_id)
    metrics = write_metrics_from_pipeline(pipeline, dest)
    return {
        "status": "ok",
        "fixture": str(midi_path),
        "artifacts": present,
        "metrics": metrics,
        "raw_sha256": sha256_file(dest / "raw.mid") if (dest / "raw.mid").is_file() else None,
    }


def run_cases(*, fixture_dir: Path, results_dir: Path) -> list[dict]:
    cases = load_cases()
    rows = []
    for name, meta in cases.items():
        if name.startswith("_"):
            continue
        dest = results_dir / Path(name).stem
        found = resolve_fixture(name, fixture_dir)
        row = {"case": name, "meta": meta, "status": "SKIP", "reason": "missing fixture"}
        if found is None:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "SKIP.txt").write_text(
                f"No local fixture for {name}. Place a wav/midi beside cases.json.\n"
            )
            rows.append(row)
            continue
        try:
            if found.suffix.lower() in MIDI_SUFFIXES:
                result = run_local_midi_case(found, dest, job_id=Path(name).stem)
                row.update(result)
            else:
                row.update(
                    status="SKIP",
                    reason="audio fixtures are processed by the deployed backend, not this CLI",
                    fixture=str(found),
                )
                dest.mkdir(parents=True, exist_ok=True)
                (dest / "SKIP.txt").write_text(
                    "Audio fixtures must go through the live API. "
                    "This CLI only transcribes local MIDI.\n"
                )
        except Exception as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local score diagnostics (missing = SKIP)")
    parser.add_argument("--fixtures", type=Path, default=SMOKE_DIR)
    parser.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = parser.parse_args(argv)
    rows = run_cases(fixture_dir=args.fixtures, results_dir=args.out)
    skipped = sum(1 for r in rows if r.get("status") == "SKIP")
    failed = sum(1 for r in rows if r.get("status") == "failed")
    ok = sum(1 for r in rows if r.get("status") == "ok")
    print(f"score diagnostics: ok={ok} skip={skipped} fail={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
