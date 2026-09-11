"""Select a separator. Default stays skipped; HTTP is the production adapter."""

from __future__ import annotations

from engine.flags import (
    separation_backend,
    separation_enabled,
    separation_endpoint,
)
from separation.base import SeparationResult
from separation.http import HttpSeparator
from separation.roformer import RoFormerSeparator


class DisabledSeparator:
    name = "disabled"

    def separate(
        self,
        audio_path: str,
        *,
        job_id: str = "",
        output_dir: str | None = None,
        requested_stems: list[str] | None = None,
    ) -> SeparationResult:
        return SeparationResult(
            stems=[],
            model=self.name,
            skipped=True,
            skip_reason="NEXTGEN_SEPARATION is off; refusing to invent stems.",
            requested_backend=self.name,
            actual_backend="",
        )


def get_separator():
    if not separation_enabled():
        return DisabledSeparator()
    backend = separation_backend()
    endpoint = separation_endpoint()
    if backend == "http" or (backend in ("auto", "") and endpoint):
        return HttpSeparator(endpoint=endpoint)
    if backend == "skip":
        return DisabledSeparator()
    if backend == "roformer":
        return RoFormerSeparator()
    if endpoint:
        return HttpSeparator(endpoint=endpoint)
    return RoFormerSeparator()
