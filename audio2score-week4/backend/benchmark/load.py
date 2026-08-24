"""Load committed corpus cases from disk."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.schema import LoadedCase

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = BACKEND_ROOT / "benchmark" / "corpus"


def load_cases(corpus_root: Path | None = None) -> list[LoadedCase]:
    root = corpus_root or CORPUS_ROOT
    cases: list[LoadedCase] = []
    for meta_path in sorted(root.glob("*/*/metadata.json")):
        case_dir = meta_path.parent
        reference_path = case_dir / "reference.json"
        input_midi = case_dir / "input.mid"
        reference_midi = case_dir / "reference.mid"
        if not reference_path.exists() or not input_midi.exists():
            continue
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        reference = json.loads(reference_path.read_text(encoding="utf-8"))
        cases.append(
            LoadedCase(
                case_id=str(metadata.get("id") or case_dir.name),
                category=str(metadata.get("category") or case_dir.parent.name),
                description=str(metadata.get("description") or ""),
                path=case_dir,
                metadata=metadata,
                reference=reference,
                input_midi=input_midi,
                reference_midi=reference_midi,
            )
        )
    return cases


def filter_cases(
    cases: list[LoadedCase],
    *,
    subset: str = "all",
    category: str | None = None,
) -> list[LoadedCase]:
    out = cases
    if subset == "ci":
        out = [c for c in out if c.ci]
    if category:
        out = [c for c in out if c.category == category]
    return out
