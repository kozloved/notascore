"""Case manifest schema and loaders (YAML/JSON). Metadata is optional."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluation.defaults import (
    AUDIO_CANDIDATES,
    MANIFEST_NAMES,
    REFERENCE_CANDIDATES,
)

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class CaseSpec:
    """One evaluation case discovered on disk."""

    case_id: str
    split: str
    case_dir: Path
    audio_path: Path | None = None
    reference_midi: Path | None = None
    title: str | None = None
    instrument: str | None = None
    expected_meter: str | None = None
    expected_tempo_bpm: float | None = None
    tags: list[str] = field(default_factory=list)
    performance_id: str | None = None
    notes: str | None = None
    raw_manifest: dict[str, Any] = field(default_factory=dict)

    def missing_audio(self) -> bool:
        return self.audio_path is None or not self.audio_path.is_file()

    def missing_reference(self) -> bool:
        return self.reference_midi is None or not self.reference_midi.is_file()


def _read_manifest_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        if yaml is None:
            raise RuntimeError("PyYAML is required to parse case.yaml manifests")
        data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Manifest must be a mapping: {path}")
    return data


def find_manifest(case_dir: Path) -> Path | None:
    for name in MANIFEST_NAMES:
        path = case_dir / name
        if path.is_file():
            return path
    return None


def find_audio(case_dir: Path, manifest: dict[str, Any] | None = None) -> Path | None:
    if manifest:
        for key in ("audio", "input", "input_audio"):
            value = manifest.get(key)
            if isinstance(value, str) and value.strip():
                path = (case_dir / value).resolve()
                return path
            if isinstance(value, dict):
                nested = value.get("path") or value.get("file")
                if nested:
                    return (case_dir / str(nested)).resolve()
        audio_block = manifest.get("audio")
        if isinstance(audio_block, dict) and audio_block.get("path"):
            return (case_dir / str(audio_block["path"])).resolve()
    for name in AUDIO_CANDIDATES:
        path = case_dir / name
        if path.is_file():
            return path.resolve()
    # Any wav/mp3/flac in the directory (prefer input*)
    for pattern in ("*.wav", "*.mp3", "*.flac", "*.ogg", "*.m4a", "*.mid", "*.midi"):
        matches = sorted(case_dir.glob(pattern))
        if matches:
            return matches[0].resolve()
    return None


def find_reference(case_dir: Path, manifest: dict[str, Any] | None = None) -> Path | None:
    if manifest:
        ref = manifest.get("reference")
        if isinstance(ref, str) and ref.strip():
            return (case_dir / ref).resolve()
        if isinstance(ref, dict):
            midi = ref.get("midi") or ref.get("path") or ref.get("file")
            if midi:
                return (case_dir / str(midi)).resolve()
        for key in ("reference_midi", "reference_performance_midi"):
            value = manifest.get(key)
            if value:
                return (case_dir / str(value)).resolve()
    for name in REFERENCE_CANDIDATES:
        path = case_dir / name
        if path.is_file():
            return path.resolve()
    matches = sorted(case_dir.glob("*.mid")) + sorted(case_dir.glob("*.midi"))
    # Prefer files named reference*; else first mid that is not clearly an output
    for path in matches:
        if "reference" in path.name.lower() or path.name.lower().startswith("ref"):
            return path.resolve()
    for path in matches:
        if path.name.lower() not in {"input.mid", "input.midi"}:
            return path.resolve()
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_case_dir(case_dir: Path, split: str) -> CaseSpec:
    """Load one case directory. Missing audio/reference are allowed (reported later)."""
    case_dir = Path(case_dir).resolve()
    manifest_path = find_manifest(case_dir)
    manifest: dict[str, Any] = {}
    if manifest_path is not None:
        manifest = _read_manifest_file(manifest_path)

    case_id = _optional_str(manifest.get("id") or manifest.get("case_id")) or case_dir.name
    expected = manifest.get("expected") if isinstance(manifest.get("expected"), dict) else {}
    reference_block = manifest.get("reference") if isinstance(manifest.get("reference"), dict) else {}

    performance_id = _optional_str(
        manifest.get("performance_id")
        or reference_block.get("performance_id")
        or reference_block.get("shared_id")
    )
    tags = manifest.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    return CaseSpec(
        case_id=case_id,
        split=split,
        case_dir=case_dir,
        audio_path=find_audio(case_dir, manifest),
        reference_midi=find_reference(case_dir, manifest),
        title=_optional_str(manifest.get("title")) or case_id,
        instrument=_optional_str(manifest.get("instrument")),
        expected_meter=_optional_str(
            expected.get("meter") if expected else None
        )
        or _optional_str(manifest.get("expected_meter")),
        expected_tempo_bpm=_optional_float(
            expected.get("tempo_bpm") if expected else None
        )
        or _optional_float(manifest.get("tempo_bpm")),
        tags=[str(t) for t in tags],
        performance_id=performance_id,
        notes=_optional_str(manifest.get("notes")),
        raw_manifest=manifest,
    )
