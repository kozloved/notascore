"""Corpus discovery, split selection, and paired-render leakage checks."""

from __future__ import annotations

from pathlib import Path

from evaluation.defaults import SPLITS
from evaluation.schema import CaseSpec, parse_case_dir

PACKAGE_DIR = Path(__file__).resolve().parent


def corpus_root() -> Path:
    return PACKAGE_DIR


def split_dir(split: str) -> Path:
    if split not in SPLITS:
        raise ValueError(f"Unknown split {split!r}; expected one of {SPLITS}")
    return corpus_root() / split


def discover_cases(
    *,
    split: str | None = None,
    case_id: str | None = None,
    root: Path | None = None,
) -> list[CaseSpec]:
    """Discover cases under evaluation/{development,holdout,real_world}/."""
    base = Path(root) if root is not None else corpus_root()
    splits = [split] if split else list(SPLITS)
    found: list[CaseSpec] = []
    for name in splits:
        directory = base / name
        if not directory.is_dir():
            continue
        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name.startswith("_"):
                continue
            spec = parse_case_dir(child, name)
            if case_id is not None and spec.case_id != case_id and child.name != case_id:
                continue
            found.append(spec)
    return found


def performance_key(case: CaseSpec) -> str | None:
    """Identity used to detect development/holdout leakage of the same performance."""
    if case.performance_id:
        return f"id:{case.performance_id}"
    if case.reference_midi and case.reference_midi.is_file():
        return f"path:{case.reference_midi.resolve()}"
    return None


def check_split_leakage(cases: list[CaseSpec]) -> list[str]:
    """Return warning strings when the same performance spans development and holdout."""
    by_key: dict[str, list[CaseSpec]] = {}
    for case in cases:
        key = performance_key(case)
        if not key:
            continue
        by_key.setdefault(key, []).append(case)
    warnings: list[str] = []
    for key, group in by_key.items():
        splits = {c.split for c in group}
        if "development" in splits and "holdout" in splits:
            ids = ", ".join(sorted(c.case_id for c in group))
            warnings.append(
                f"Paired-render leakage: performance {key} appears in both "
                f"development and holdout (cases: {ids})"
            )
    return warnings
