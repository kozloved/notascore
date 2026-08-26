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
    REFERENCE_RAW_CANDIDATES,
    REFERENCE_SCORE_CANDIDATES,
)

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


@dataclass
class ReferenceResolution:
    """How raw/score references were resolved for a case."""

    raw_path: Path | None = None
    score_path: Path | None = None
    raw_source: str | None = None  # e.g. reference_raw.mid | reference.mid | pattern
    score_source: str | None = None
    raw_legacy_fallback: bool = False
    score_legacy_fallback: bool = False
    same_file: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_path": str(self.raw_path) if self.raw_path else None,
            "score_path": str(self.score_path) if self.score_path else None,
            "raw_source": self.raw_source,
            "score_source": self.score_source,
            "raw_legacy_fallback": self.raw_legacy_fallback,
            "score_legacy_fallback": self.score_legacy_fallback,
            "same_file": self.same_file,
        }


@dataclass
class CaseSpec:
    """One evaluation case discovered on disk."""

    case_id: str
    split: str
    case_dir: Path
    audio_path: Path | None = None
    reference_midi: Path | None = None  # backward-compat: preferred raw or legacy
    reference_raw_midi: Path | None = None
    reference_score_midi: Path | None = None
    reference_resolution: ReferenceResolution = field(default_factory=ReferenceResolution)
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
        """True when neither raw nor score (nor legacy) reference exists."""
        has_raw = self.reference_raw_midi is not None and self.reference_raw_midi.is_file()
        has_score = (
            self.reference_score_midi is not None and self.reference_score_midi.is_file()
        )
        return not has_raw and not has_score

    def missing_raw_reference(self) -> bool:
        return self.reference_raw_midi is None or not self.reference_raw_midi.is_file()

    def missing_score_reference(self) -> bool:
        return (
            self.reference_score_midi is None or not self.reference_score_midi.is_file()
        )


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
    # Prefer *audio* then any audio file
    audio_globs = sorted(case_dir.glob("*audio*.wav")) + sorted(
        case_dir.glob("*audio*.mp3")
    )
    if audio_globs:
        return audio_globs[0].resolve()
    for pattern in ("*.wav", "*.mp3", "*.flac", "*.ogg", "*.m4a", "*.mid", "*.midi"):
        matches = sorted(case_dir.glob(pattern))
        if matches:
            return matches[0].resolve()
    return None


def find_reference(case_dir: Path, manifest: dict[str, Any] | None = None) -> Path | None:
    """Legacy single-reference finder (Checkpoint 7). Prefer explicit reference*.mid."""
    if manifest:
        ref = manifest.get("reference")
        if isinstance(ref, str) and ref.strip():
            return (case_dir / ref).resolve()
        if isinstance(ref, dict):
            midi = (
                ref.get("midi")
                or ref.get("path")
                or ref.get("file")
                or ref.get("raw")
                or ref.get("score")
            )
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
    for path in matches:
        if "reference" in path.name.lower() or path.name.lower().startswith("ref"):
            return path.resolve()
    for path in matches:
        if path.name.lower() not in {"input.mid", "input.midi"}:
            return path.resolve()
    return None


def _manifest_ref_path(
    case_dir: Path,
    manifest: dict[str, Any] | None,
    *,
    keys: tuple[str, ...],
) -> Path | None:
    if not manifest:
        return None
    ref = manifest.get("reference")
    if isinstance(ref, dict):
        for key in keys:
            value = ref.get(key)
            if value:
                return (case_dir / str(value)).resolve()
    for key in keys:
        value = manifest.get(key)
        if isinstance(value, str) and value.strip():
            return (case_dir / value).resolve()
    return None


def _stem_hint(path: Path, *hints: str) -> bool:
    name = path.name.lower()
    return any(h in name for h in hints)


def find_reference_raw(
    case_dir: Path, manifest: dict[str, Any] | None = None
) -> tuple[Path | None, str | None, bool]:
    """Resolve the raw performance reference.

    Returns (path, source_label, used_legacy_fallback).
    """
    path = _manifest_ref_path(
        case_dir,
        manifest,
        keys=("raw", "raw_midi", "reference_raw", "reference_raw_midi"),
    )
    if path is not None and path.is_file():
        return path, f"manifest:{path.name}", False

    for name in REFERENCE_RAW_CANDIDATES:
        candidate = case_dir / name
        if candidate.is_file():
            return candidate.resolve(), name, False

    # Common DAW naming: *_raw.mid
    for path in sorted(case_dir.glob("*.mid")) + sorted(case_dir.glob("*.midi")):
        if _stem_hint(path, "_raw", "-raw", ".raw"):
            return path.resolve(), f"pattern:{path.name}", False

    for name in REFERENCE_CANDIDATES:
        candidate = case_dir / name
        if candidate.is_file():
            return candidate.resolve(), name, True

    return None, None, False


def find_reference_score(
    case_dir: Path, manifest: dict[str, Any] | None = None
) -> tuple[Path | None, str | None, bool]:
    """Resolve the quantized score reference.

    Returns (path, source_label, used_legacy_fallback).
    """
    path = _manifest_ref_path(
        case_dir,
        manifest,
        keys=("score", "score_midi", "reference_score", "reference_score_midi", "q"),
    )
    if path is not None and path.is_file():
        return path, f"manifest:{path.name}", False

    for name in REFERENCE_SCORE_CANDIDATES:
        candidate = case_dir / name
        if candidate.is_file():
            return candidate.resolve(), name, False

    # Common DAW naming: *_q.mid / *_score.mid / *_quant*.mid
    for path in sorted(case_dir.glob("*.mid")) + sorted(case_dir.glob("*.midi")):
        if _stem_hint(path, "_q.", "-q.", "_score", "-score", "_quant", "-quant"):
            return path.resolve(), f"pattern:{path.name}", False

    for name in REFERENCE_CANDIDATES:
        candidate = case_dir / name
        if candidate.is_file():
            return candidate.resolve(), name, True

    return None, None, False


def resolve_references(
    case_dir: Path, manifest: dict[str, Any] | None = None
) -> ReferenceResolution:
    """Resolve raw and score references with explicit provenance."""
    raw_path, raw_source, raw_legacy = find_reference_raw(case_dir, manifest)
    score_path, score_source, score_legacy = find_reference_score(case_dir, manifest)
    same = False
    if raw_path is not None and score_path is not None:
        try:
            same = raw_path.resolve() == score_path.resolve()
        except OSError:
            same = False
    return ReferenceResolution(
        raw_path=raw_path,
        score_path=score_path,
        raw_source=raw_source,
        score_source=score_source,
        raw_legacy_fallback=raw_legacy,
        score_legacy_fallback=score_legacy,
        same_file=same,
    )


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


def looks_like_case_dir(case_dir: Path) -> bool:
    """True if directory contains audio and/or reference MIDI (leaf case)."""
    if find_manifest(case_dir) is not None:
        return True
    if find_audio(case_dir) is not None:
        return True
    mids = list(case_dir.glob("*.mid")) + list(case_dir.glob("*.midi"))
    return bool(mids)


def parse_case_dir(case_dir: Path, split: str) -> CaseSpec:
    """Load one case directory. Missing audio/reference are allowed (reported later)."""
    case_dir = Path(case_dir).resolve()
    manifest_path = find_manifest(case_dir)
    manifest: dict[str, Any] = {}
    if manifest_path is not None:
        manifest = _read_manifest_file(manifest_path)

    case_id = _optional_str(manifest.get("id") or manifest.get("case_id")) or case_dir.name
    expected = manifest.get("expected") if isinstance(manifest.get("expected"), dict) else {}
    reference_block = (
        manifest.get("reference") if isinstance(manifest.get("reference"), dict) else {}
    )

    performance_id = _optional_str(
        manifest.get("performance_id")
        or reference_block.get("performance_id")
        or reference_block.get("shared_id")
    )
    tags = manifest.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]

    resolution = resolve_references(case_dir, manifest)
    # Backward-compat primary reference: prefer raw, else score, else legacy finder
    primary = resolution.raw_path or resolution.score_path or find_reference(
        case_dir, manifest
    )

    return CaseSpec(
        case_id=case_id,
        split=split,
        case_dir=case_dir,
        audio_path=find_audio(case_dir, manifest),
        reference_midi=primary,
        reference_raw_midi=resolution.raw_path,
        reference_score_midi=resolution.score_path,
        reference_resolution=resolution,
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
