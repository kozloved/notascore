"""Per-job immutable notes, one time map, and explicit stage results.

Notation and playback both consume `PipelineJob.notes` and `PipelineJob.time_map`.
Stages return dataclasses; `last_*` fields on the pipeline are a published
snapshot of this object, not the coordination channel.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from mir.types import NoteEvent


@dataclass(frozen=True)
class ImmutableNoteSet:
    """Frozen copy of the notes that belong to one job view.

    Callers receive `copy_notes()` if they need a mutable working list.
    The stored tuple is never mutated in place.
    """

    notes: tuple[NoteEvent, ...]
    source: str = "full_mix"

    @classmethod
    def from_notes(
        cls,
        notes: Sequence[NoteEvent] | None,
        *,
        source: str = "full_mix",
    ) -> "ImmutableNoteSet":
        frozen = tuple(replace(n) for n in (notes or ()))
        return cls(notes=frozen, source=source)

    def copy_notes(self) -> list[NoteEvent]:
        return [replace(n) for n in self.notes]

    def __len__(self) -> int:
        return len(self.notes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "note_count": len(self.notes),
            "note_ids": [n.note_id for n in self.notes],
        }


@dataclass
class QuantizationResult:
    """Explicit output of a quantizer call. Not stored as pipeline coordination."""

    events: list = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    report: Any = None
    raw_events: list = field(default_factory=list)
    mode: str = "performance"
    engine: str = "performance"
    experimental: bool = False

    def as_tuple(self) -> tuple[list, list[dict]]:
        return list(self.events), list(self.decisions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "engine": self.engine,
            "experimental": self.experimental,
            "raw_event_count": len(self.raw_events),
            "event_count": len(self.events),
            "decision_count": len(self.decisions),
            "summary": dict(self.summary or {}),
        }


@dataclass
class NotationResult:
    """Explicit notation-stage output used by export and debug."""

    plan: Any = None
    quantized_events: list = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    quantization_mode: str = "performance"
    fallback_used: bool = False
    fallback_error: str | None = None
    plan_failure: bool = False
    conversion_failure: bool = False
    export_failure: bool = False
    fit_trim_count: int = 0
    invariant_issues: list[dict] = field(default_factory=list)
    source_event_count: int = 0
    job_id: str | None = None

    def to_debug_payload(self) -> dict[str, Any]:
        plan = self.plan
        plan_ok = plan is not None and not self.plan_failure
        return {
            "notation_path": "legacy_build_score" if self.fallback_used else "notation_plan",
            "notation_mode": self.quantization_mode,
            "notation_plan_success": plan_ok and not self.conversion_failure,
            "notation_plan_failure": self.plan_failure,
            "legacy_fallback_used": self.fallback_used,
            "music21_conversion_failure": self.conversion_failure,
            "musicxml_export_failure": self.export_failure,
            "notation_fallback_error": self.fallback_error,
            "fallback_used": self.fallback_used,
            "job_id": self.job_id,
            "source_event_count": self.source_event_count,
            "quantized_event_count": len(self.quantized_events or []),
            "time_signature": getattr(plan, "time_signature", None) if plan else None,
            "measure_count": len(getattr(plan, "measures", []) or []) if plan else 0,
            "fit_trim_count": self.fit_trim_count,
            "invariant_issues": list(self.invariant_issues),
            "quantization_decisions": list(self.decisions),
            "quantization_summary": dict(self.summary),
        }


@dataclass
class PipelineJob:
    """One job's authoritative inputs plus named stage outputs.

    `mix_notes` is the full-mix baseline and never replaced by fusion.
    `notes` is the set fed to interpretation (mix, or reconciled notes).
    `time_map` is the single seconds↔beats mapping for notation and playback.
    """

    job_id: str
    notes: ImmutableNoteSet
    mix_notes: ImmutableNoteSet
    time_map: Any = None
    timing: Any = None
    transcription: ImmutableNoteSet | None = None
    validated: ImmutableNoteSet | None = None
    quantization: QuantizationResult | None = None
    notation: NotationResult | None = None
    structure: Any = None
    meter_decision: Any = None
    snapshot: Any = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        time_map = self.time_map
        return {
            "job_id": self.job_id,
            "notes": self.notes.to_dict(),
            "mix_notes": self.mix_notes.to_dict(),
            "time_map_source": getattr(time_map, "source", None),
            "time_map_beats": len(getattr(time_map, "beat_times", ()) or []),
            "quantization": self.quantization.to_dict() if self.quantization else None,
            "notation": self.notation.to_debug_payload() if self.notation else None,
        }
