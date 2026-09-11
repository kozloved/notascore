"""Typed stage names and results. Fallbacks are always recorded."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StageName(str, Enum):
    INGEST = "INGEST"
    PREPROCESS = "PREPROCESS"
    ANALYZE_AUDIO = "ANALYZE_AUDIO"
    SEPARATE = "SEPARATE"
    TRANSCRIBE_GLOBAL = "TRANSCRIBE_GLOBAL"
    TRANSCRIBE_STEMS = "TRANSCRIBE_STEMS"
    RECONCILE = "RECONCILE"
    BUILD_PERFORMANCE = "BUILD_PERFORMANCE"
    ANALYZE_TIME = "ANALYZE_TIME"
    INTERPRET_SCORE = "INTERPRET_SCORE"
    EXPORT = "EXPORT"
    RENDER = "RENDER"
    COMPLETE = "COMPLETE"


def _status(*, ok: bool, skipped: bool, fallback_used: bool, error: str) -> str:
    if skipped:
        return "skipped"
    if error or not ok:
        return "failed"
    if fallback_used:
        return "fallback"
    return "success"


@dataclass
class StageResult:
    name: StageName
    ok: bool
    duration_ms: float
    model: str = ""
    model_version: str = ""
    skipped: bool = False
    skip_reason: str = ""
    fallback_used: bool = False
    fallback_of: str = ""
    warnings: list[str] = field(default_factory=list)
    confidence: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    started_at: float | None = None
    finished_at: float | None = None
    backend: str = ""
    requested_backend: str = ""
    actual_backend: str = ""
    artifacts: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def stage(self) -> StageName:
        return self.name

    @property
    def status(self) -> str:
        return _status(
            ok=self.ok,
            skipped=self.skipped,
            fallback_used=self.fallback_used,
            error=self.error,
        )

    def to_dict(self) -> dict[str, Any]:
        requested = self.requested_backend or self.backend or self.model
        actual = self.actual_backend or ("" if self.skipped or self.error else (self.backend or self.model))
        return {
            "name": self.name.value,
            "stage": self.name.value,
            "status": self.status,
            "ok": self.ok,
            "duration_ms": round(self.duration_ms, 3),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "backend": self.backend or self.model,
            "requested_backend": requested,
            "actual_backend": actual,
            "model": self.model,
            "model_version": self.model_version,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "fallback": self.fallback_used,
            "fallback_used": self.fallback_used,
            "fallback_of": self.fallback_of,
            "fallback_reason": self.fallback_of or self.skip_reason,
            "warnings": list(self.warnings),
            "confidence": self.confidence,
            "artifacts": list(self.artifacts),
            "error": self.error,
            "extra": dict(self.extra),
        }
