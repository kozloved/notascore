"""Capture per-stage note lists from a single production pipeline run.

Stages are observation snapshots taken during UnderstandingPipeline.transcribe —
this module never re-invokes Basic Pitch or the cleaner.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from evaluation.matching import match_notes
from mir.raw_midi import write_events_to_midi, write_notes_to_midi
from mir.types import MusicalEvent, NoteEvent, TempoMap


# Honest labels matching the production order:
# transcription → validated (cleaner) → piano → structured → quantized
STAGE_ORDER = (
    "transcription",
    "post_cleaner",
    "post_piano",
    "structured",
    "quantized",
)

# Backward-compatible aliases used in older reports/tests
_STAGE_ALIASES = {
    "raw": "transcription",
    "cleaned": "post_cleaner",
    "validated": "post_cleaner",
}


@dataclass
class StageSnapshot:
    name: str
    notes: list[NoteEvent]
    midi_path: Path | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StageDiagnostics:
    stages: list[StageSnapshot] = field(default_factory=list)
    first_degradation_stage: str | None = None
    conclusion: str = ""
    pipeline: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": [
                {
                    "name": s.name,
                    "note_count": len(s.notes),
                    "midi_path": str(s.midi_path) if s.midi_path else None,
                    "metrics": s.metrics,
                    "extra": s.extra,
                }
                for s in self.stages
            ],
            "first_degradation_stage": self.first_degradation_stage,
            "conclusion": self.conclusion,
            "pipeline": self.pipeline,
        }


def events_to_notes(
    events: Sequence[MusicalEvent],
    tempo_map: TempoMap | None = None,
    fallback_bpm: float = 120.0,
    *,
    timing: str = "notation",
) -> list[NoteEvent]:
    """Convert MusicalEvents to NoteEvents.

    timing='notation' (default) uses the beat grid via tempo_map when present.
    timing='performance' prefers start_time_sec / end_time_sec so structure
    metadata can be compared against RAW without beat-roundtrip noise.
    """
    spb = 60.0 / float(fallback_bpm if fallback_bpm else 120.0)
    notes: list[NoteEvent] = []
    use_performance = timing == "performance"
    for ev in events:
        if use_performance and ev.start_time_sec is not None and ev.end_time_sec is not None:
            start = float(ev.start_time_sec)
            end = float(ev.end_time_sec)
        elif tempo_map is not None:
            start = tempo_map.beats_to_seconds(ev.start_beat)
            end = tempo_map.beats_to_seconds(ev.start_beat + ev.duration_beats)
        elif ev.start_time_sec is not None and ev.end_time_sec is not None:
            start = float(ev.start_time_sec)
            end = float(ev.end_time_sec)
        else:
            start = float(ev.start_beat) * spb
            end = start + float(ev.duration_beats) * spb
        notes.append(
            NoteEvent(
                pitch=int(ev.pitch),
                start_time=float(start),
                end_time=max(float(start) + 0.01, float(end)),
                velocity=int(ev.velocity),
                confidence=float(ev.confidence),
                hand=ev.hand,
                note_id=ev.note_id or "",
            )
        )
    return sorted(notes, key=lambda n: (n.start_time, n.pitch))


def _suppression_rows(clean_decisions: Sequence[Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for d in clean_decisions or []:
        action = getattr(d, "action", None)
        action_val = action.value if hasattr(action, "value") else str(action or "")
        if action_val != "suppress":
            continue
        rows.append(
            {
                "note_id": getattr(d, "note_id", None),
                "pitch": getattr(d, "pitch", None),
                "action": action_val,
                "reason": getattr(d, "reason", None),
            }
        )
    return rows


def capture_transcription_stages(
    *,
    out_dir: Path,
    reference_notes: Sequence[NoteEvent],
    raw_notes: Sequence[NoteEvent] | None,
    cleaned_notes: Sequence[NoteEvent] | None,
    post_piano_notes: Sequence[NoteEvent] | None,
    structured_events: Sequence[MusicalEvent] | None,
    tempo_map: TempoMap | None,
    tempo_bpm: float,
    clean_decisions: Sequence[Any] | None = None,
    pipeline_info: dict[str, Any] | None = None,
    quantized_events: Sequence[MusicalEvent] | None = None,
) -> StageDiagnostics:
    """Write stage MIDIs and metrics from one pipeline run's snapshots.

    Does not call Basic Pitch or MIDICleaner. Missing snapshots are skipped.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suppressions = _suppression_rows(clean_decisions)
    stages: list[StageSnapshot] = []

    def _add_note_stage(
        name: str,
        notes: Sequence[NoteEvent] | None,
        filename: str,
        *,
        source: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if notes is None:
            return
        note_list = list(notes)
        midi_path = write_notes_to_midi(
            note_list,
            out_dir / filename,
            bpm=tempo_bpm,
            split_hands=False,
            tempo_map=tempo_map,
        )
        stages.append(
            StageSnapshot(
                name=name,
                notes=note_list,
                midi_path=midi_path,
                metrics=match_notes(note_list, reference_notes).to_dict(),
                extra={"source": source, **(extra or {})},
            )
        )

    _add_note_stage(
        "transcription",
        raw_notes,
        "transcription.mid",
        source="pipeline.last_raw_notes",
    )
    _add_note_stage(
        "post_cleaner",
        cleaned_notes,
        "post_cleaner.mid",
        source="pipeline.last_cleaned_notes",
        extra={
            "suppressions": suppressions,
            "suppression_count": len(suppressions),
        },
    )
    _add_note_stage(
        "post_piano",
        post_piano_notes,
        "post_piano.mid",
        source="pipeline.last_post_piano_notes",
    )

    if structured_events:
        structured_notes = events_to_notes(
            structured_events, tempo_map=tempo_map, fallback_bpm=tempo_bpm
        )
        structured_midi = write_events_to_midi(
            list(structured_events),
            out_dir / "structured.mid",
            bpm=tempo_bpm,
            tempo_map=tempo_map,
        )
        stages.append(
            StageSnapshot(
                name="structured",
                notes=structured_notes,
                midi_path=structured_midi,
                metrics=match_notes(structured_notes, reference_notes).to_dict(),
                extra={"source": "pipeline.last_structure.events"},
            )
        )

    if quantized_events:
        quantized_notes = events_to_notes(
            quantized_events, tempo_map=tempo_map, fallback_bpm=tempo_bpm
        )
        quantized_midi = write_events_to_midi(
            list(quantized_events),
            out_dir / "quantized.mid",
            bpm=tempo_bpm,
            tempo_map=tempo_map,
        )
        stages.append(
            StageSnapshot(
                name="quantized",
                notes=quantized_notes,
                midi_path=quantized_midi,
                metrics=match_notes(quantized_notes, reference_notes).to_dict(),
                extra={"source": "pipeline.last_quantized_events"},
            )
        )

    first_deg, conclusion = _first_degradation(
        stages, reference_count=len(reference_notes)
    )
    return StageDiagnostics(
        stages=stages,
        first_degradation_stage=first_deg,
        conclusion=conclusion,
        pipeline=pipeline_info or {},
    )


def _first_degradation(
    stages: list[StageSnapshot],
    *,
    reference_count: int,
) -> tuple[str | None, str]:
    if not stages:
        return None, "No stages captured."
    labels = {
        "transcription": "TRANSCRIPTION (Basic Pitch)",
        "post_cleaner": "AFTER CLEANER",
        "post_piano": "AFTER PIANO ANALYZER",
        "quantized": "AFTER NOTATION QUANTIZATION",
        "structured": "AFTER STRUCTURE / MIR",
        # aliases
        "raw": "TRANSCRIPTION (Basic Pitch)",
        "cleaned": "AFTER CLEANER",
    }
    lines = [f"REFERENCE\n{reference_count} notes", ""]
    prev_f1 = None
    first = None
    for stage in stages:
        f1 = float((stage.metrics or {}).get("onset_pitch_f1") or 0.0)
        count = int((stage.metrics or {}).get("predicted_count") or len(stage.notes))
        lines.append(labels.get(stage.name, stage.name.upper()))
        lines.append(f"{count} predicted")
        lines.append(f"F1 {f1:.2f}")
        lines.append("")
        if prev_f1 is not None and f1 + 1e-9 < prev_f1 - 0.02 and first is None:
            first = stage.name
        prev_f1 = f1

    if first == "post_cleaner" or first == "cleaned":
        conclusion = "Likely note loss introduced after transcription (cleaner)."
    elif first == "post_piano":
        conclusion = "Likely change introduced after cleaner (piano analyzer)."
    elif first == "structured":
        conclusion = "Likely quality drop introduced after piano stage (structure / MIR)."
    elif first == "quantized":
        conclusion = "Likely quality drop introduced at notation quantization."
    elif stages and float(stages[0].metrics.get("onset_pitch_f1") or 0) < 0.85:
        conclusion = "Primary quality gap appears at transcription (Basic Pitch)."
        first = first or stages[0].name
    else:
        conclusion = "No large stage-to-stage F1 drop detected."
    lines.append("CONCLUSION")
    lines.append(conclusion)
    return first, "\n".join(lines)


def copy_musicxml(src: Path | None, dest: Path) -> bool:
    if src is None or not Path(src).is_file():
        return False
    shutil.copy2(src, dest)
    return True


# Backward-compatible aliases for tests / older call sites
StageSnapshot = StageSnapshot
_first_degradation = _first_degradation
