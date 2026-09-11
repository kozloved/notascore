"""RoFormer-family adapter. Never fakes missing stems."""

from __future__ import annotations

from engine.flags import separation_checkpoint, separation_enabled
from separation.base import SeparationResult


class RoFormerUnavailable(RuntimeError):
    pass


class RoFormerSeparator:
    name = "roformer"

    def separate(
        self,
        audio_path: str,
        *,
        job_id: str = "",
        output_dir: str | None = None,
        requested_stems: list[str] | None = None,
    ) -> SeparationResult:
        if not separation_enabled() or not separation_checkpoint():
            return SeparationResult(
                stems=[],
                model=self.name,
                skipped=True,
                skip_reason=(
                    "Stem separation disabled until NEXTGEN_SEPARATION=1, a "
                    "licensed checkpoint path is set, and MODEL_LICENSES.md "
                    f"is satisfied (checkpoint={separation_checkpoint() or 'unset'})."
                ),
                requested_backend=self.name,
                actual_backend="",
            )
        raise RoFormerUnavailable(
            "RoFormer checkpoint is configured but in-process inference is not "
            "wired (and must not load into the API/RQ worker). Use "
            "SEPARATION_ENDPOINT / NEXTGEN_SEPARATION_BACKEND=http. "
            "Refusing to invent stems."
        )
