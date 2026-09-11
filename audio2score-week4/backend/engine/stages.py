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

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "ok": self.ok,
            "duration_ms": round(self.duration_ms, 3),
            "model": self.model,
            "model_version": self.model_version,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "fallback_used": self.fallback_used,
            "fallback_of": self.fallback_of,
            "warnings": list(self.warnings),
            "confidence": self.confidence,
            "extra": dict(self.extra),
        }
