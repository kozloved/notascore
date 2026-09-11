"""Typed job artifact manifest. Existing result URLs stay compatible."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ArtifactKind(str, Enum):
    ORIGINAL_AUDIO = "audio/original"
    NORMALIZED_AUDIO = "audio/normalized"
    STEM_AUDIO = "audio/stem"
    RAW_MIDI = "midi/raw"
    VALIDATED_MIDI = "midi/validated"
    PERFORMANCE_MIDI = "midi/performance"
    SCORE_MIDI = "midi/score"
    MUSICXML = "score/musicxml"
    PDF = "score/pdf"
    SVG = "score/svg"
    PERFORMANCE_JSON = "analysis/performance"
    TRANSCRIPTION_JSON = "analysis/transcription"
    FUSION_JSON = "analysis/fusion"
    TEMPO_JSON = "analysis/tempo"
    STRUCTURE_JSON = "analysis/structure"
    SCORE_IR_JSON = "analysis/score-ir"
    PROVENANCE_JSON = "analysis/provenance"
    DEBUG_JSON = "analysis/debug"
    MANIFEST_JSON = "analysis/manifest"


@dataclass
class ArtifactRef:
    kind: ArtifactKind
    path: str
    content_type: str = ""
    stem_id: str = ""
    instrument: str = ""
    sha256: str | None = None
    bytes: int | None = None
    model: str = ""
    model_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    artifact_id: str = ""
    storage_key: str = ""
    source_stage: str = ""
    source_model: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactRef":
        payload = dict(data)
        payload["kind"] = ArtifactKind(payload["kind"])
        payload.setdefault("extra", {})
        payload = {k: v for k, v in payload.items() if k in cls.__dataclass_fields__}
        return cls(**payload)


@dataclass
class ArtifactManifest:
    job_id: str
    schema_version: int = 1
    artifacts: list[ArtifactRef] = field(default_factory=list)

    def add(self, ref: ArtifactRef) -> None:
        self.artifacts.append(ref)

    def find(self, kind: ArtifactKind, stem_id: str = "") -> list[ArtifactRef]:
        return [
            a
            for a in self.artifacts
            if a.kind == kind and (not stem_id or a.stem_id == stem_id)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "schema_version": self.schema_version,
            "artifacts": [a.to_dict() for a in self.artifacts],
        }

    def write_json(self, path: str | Path) -> Path:
        dest = Path(path)
        dest.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return dest

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactManifest":
        artifacts: list[ArtifactRef] = []
        for row in data.get("artifacts") or []:
            if not isinstance(row, dict):
                continue
            try:
                artifacts.append(ArtifactRef.from_dict(row))
            except (KeyError, TypeError, ValueError):
                continue
        return cls(
            job_id=str(data.get("job_id") or ""),
            schema_version=int(data.get("schema_version") or 1),
            artifacts=artifacts,
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "ArtifactManifest":
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("artifact manifest JSON must be an object")
        return cls.from_dict(data)

    @classmethod
    def read_json(cls, path: str | Path) -> "ArtifactManifest":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


def hash_file(path: str | Path) -> tuple[str, int]:
    import hashlib

    data = Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest(), len(data)


def ref_for_file(
    kind: ArtifactKind,
    path: str | Path,
    *,
    content_type: str = "",
    stem_id: str = "",
    instrument: str = "",
    model: str = "",
    model_version: str = "",
    storage_key: str = "",
    source_stage: str = "",
    source_model: str = "",
    artifact_id: str = "",
) -> ArtifactRef:
    dest = Path(path)
    digest, size = hash_file(dest)
    source_model = source_model or model
    ident = artifact_id or _artifact_id(kind, stem_id, digest)
    return ArtifactRef(
        kind=kind,
        path=str(dest),
        content_type=content_type,
        stem_id=stem_id,
        instrument=instrument,
        sha256=digest,
        bytes=size,
        model=model,
        model_version=model_version,
        artifact_id=ident,
        storage_key=storage_key or dest.name,
        source_stage=source_stage,
        source_model=source_model,
    )


def _artifact_id(kind: ArtifactKind, stem_id: str, digest: str) -> str:
    stem = stem_id or "default"
    return f"{kind.value}:{stem}:{digest[:12]}"
