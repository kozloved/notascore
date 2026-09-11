"""Wall-clock helper for stage traces."""

from __future__ import annotations

import time
from typing import Any

from engine.stages import StageName, StageResult


class StageTimer:
    def __init__(self, name: StageName):
        self.name = name
        self.started_at = time.time()
        self._t0 = time.perf_counter()

    def duration_ms(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def result(self, *, ok: bool, **kwargs: Any) -> StageResult:
        return StageResult(
            self.name,
            ok=ok,
            duration_ms=self.duration_ms(),
            started_at=self.started_at,
            finished_at=time.time(),
            **kwargs,
        )
