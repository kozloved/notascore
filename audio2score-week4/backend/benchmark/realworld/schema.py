"""Manifest schema for local real-world evaluation cases.

Audio and reference MIDI live outside git. The committed manifest only stores
relative paths, optional known meter, and instrumentation notes.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_LOCAL_ROOT = PACKAGE_DIR / "local"
ENV_LOCAL_ROOT = "NOTASCORE_REALWORLD_DIR"


@dataclass
class RealWorldCase:
    """One evaluation item. Missing files are skipped, not invented."""

    case_id: str
    audio_path: Path | None = None
    reference_performance_midi: Path | None = None
    reference_score_midi: Path | None = None
    expected_meter: str | None = None
    instrumentation: str | None = None
    notes: str | None = None
    title: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def audio_missing(self) -> bool:
        return self.audio_path is None or not self.audio_path.is_file()


def default_local_root() -> Path:
    env = os.environ.get(ENV_LOCAL_ROOT, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_LOCAL_ROOT


def _optional_path(value: Any, local_root: Path) -> Path | None:
    if not value:
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = local_root / path
    return path.resolve()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def resolve_local_root(
    manifest: dict[str, Any],
    manifest_path: Path,
    override: Path | None = None,
) -> Path:
    if override is not None:
        return Path(override).expanduser().resolve()
    env = os.environ.get(ENV_LOCAL_ROOT, "").strip()
    if env:
        return Path(env).expanduser().resolve()
    declared = manifest.get("local_root")
    if declared:
        root = Path(str(declared)).expanduser()
        if not root.is_absolute():
            root = manifest_path.parent / root
        return root.resolve()
    return DEFAULT_LOCAL_ROOT


def case_from_dict(raw: dict[str, Any], local_root: Path) -> RealWorldCase:
    case_id = str(raw.get("id") or raw.get("case_id") or "").strip()
    if not case_id:
        raise ValueError("Real-world case is missing id")
    return RealWorldCase(
        case_id=case_id,
        title=_optional_str(raw.get("title")) or case_id,
        audio_path=_optional_path(raw.get("audio") or raw.get("audio_path"), local_root),
        reference_performance_midi=_optional_path(
            raw.get("reference_performance_midi") or raw.get("performance_midi"),
            local_root,
        ),
        reference_score_midi=_optional_path(
            raw.get("reference_score_midi") or raw.get("score_midi"),
            local_root,
        ),
        expected_meter=_optional_str(raw.get("expected_meter")),
        instrumentation=_optional_str(raw.get("instrumentation")),
        notes=_optional_str(raw.get("notes")),
        extra={
            k: v
            for k, v in raw.items()
            if k
            not in {
                "id",
                "case_id",
                "title",
                "audio",
                "audio_path",
                "reference_performance_midi",
                "performance_midi",
                "reference_score_midi",
                "score_midi",
                "expected_meter",
                "instrumentation",
                "notes",
            }
        },
    )


def load_manifest(
    path: str | Path,
    *,
    local_root: Path | None = None,
) -> tuple[list[RealWorldCase], dict[str, Any]]:
    manifest_path = Path(path).expanduser().resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = resolve_local_root(payload, manifest_path, override=local_root)
    cases = [case_from_dict(row, root) for row in payload.get("cases") or []]
    meta = {
        "manifest_path": str(manifest_path),
        "local_root": str(root),
        "version": payload.get("version"),
        "description": payload.get("description"),
    }
    return cases, meta
