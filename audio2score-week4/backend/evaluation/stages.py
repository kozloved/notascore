"""Capture per-stage note lists and identify first quality degradation."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from adapters.basic_pitch_backend import BasicPitchBackend
from evaluation.matching import match_notes
from mir.midi_cleaner import MIDICleaner
from mir.raw_midi import write_events_to_midi, write_notes_to_midi
from mir.types import MusicalEvent, NoteEvent, TempoMap


STAGE_ORDER = ("raw", "cleaned", "structured")


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
) -> list[NoteEvent]:
    spb = 60.0 / float(fallback_bpm if fallback_bpm else 120.0)
    notes: list[NoteEvent] = []
    for ev in events:
        if tempo_map is not None:
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
            )
        )
    return sorted(notes, key=lambda n: (n.start_time, n.pitch))


def capture_transcription_stages(
    *,
    audio_path: Path,
    out_dir: Path,
    reference_notes: Sequence[NoteEvent],
    structured_events: Sequence[MusicalEvent] | None,
    tempo_map: TempoMap | None,
    tempo_bpm: float,
    cleaner_suppressions: list[dict[str, Any]] | None = None,
    pipeline_info: dict[str, Any] | None = None,
) -> StageDiagnostics:
    """Produce raw/cleaned/structured MIDIs and per-stage metrics vs reference.

    Uses production BasicPitchBackend + MIDICleaner without modifying them.
    Structured notes come from the pipeline's MusicalStructure events.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    backend = BasicPitchBackend()
    raw_notes = [
        n.ensure_ids(i) for i, n in enumerate(backend.transcribe_notes(audio_path))
    ]
    raw_midi = write_notes_to_midi(
        raw_notes,
        out_dir / "raw_transcription.mid",
        bpm=tempo_bpm,
        split_hands=False,
        tempo_map=tempo_map,
    )

    cleaner = MIDICleaner()
    cleaned_notes, decisions = cleaner.clean_with_report(list(raw_notes))
    suppressions = [
        {
            "note_id": d.note_id,
            "pitch": d.pitch,
            "action": d.action.value,
            "reason": d.reason,
        }
        for d in decisions
        if d.action.value == "suppress"
    ]
    if cleaner_suppressions is not None:
        # Prefer pipeline-reported suppressions when provided
        suppressions = list(cleaner_suppressions)
    cleaned_midi = write_notes_to_midi(
        cleaned_notes,
        out_dir / "cleaned.mid",
        bpm=tempo_bpm,
        split_hands=False,
        tempo_map=tempo_map,
    )

    structured_notes: list[NoteEvent] = []
    structured_midi = None
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

    stages = [
        StageSnapshot(
            name="raw",
            notes=raw_notes,
            midi_path=raw_midi,
            metrics=match_notes(raw_notes, reference_notes).to_dict(),
            extra={"source": "BasicPitchBackend"},
        ),
        StageSnapshot(
            name="cleaned",
            notes=cleaned_notes,
            midi_path=cleaned_midi,
            metrics=match_notes(cleaned_notes, reference_notes).to_dict(),
            extra={
                "source": "MIDICleaner",
                "suppressions": suppressions,
                "suppression_count": len(suppressions),
            },
        ),
    ]
    if structured_notes:
        stages.append(
            StageSnapshot(
                name="structured",
                notes=structured_notes,
                midi_path=structured_midi,
                metrics=match_notes(structured_notes, reference_notes).to_dict(),
                extra={"source": "MusicalStructure.events"},
            )
        )

    first_deg, conclusion = _first_degradation(stages, reference_count=len(reference_notes))
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
    lines = [
        f"REFERENCE\n{reference_count} notes",
        "",
    ]
    prev_f1 = None
    first = None
    for stage in stages:
        f1 = float((stage.metrics or {}).get("onset_pitch_f1") or 0.0)
        count = int((stage.metrics or {}).get("predicted_count") or len(stage.notes))
        label = {
            "raw": "RAW TRANSCRIPTION",
            "cleaned": "AFTER CLEANER",
            "structured": "AFTER STRUCTURE / MIR",
        }.get(stage.name, stage.name.upper())
        lines.append(label)
        lines.append(f"{count} predicted")
        lines.append(f"F1 {f1:.2f}")
        lines.append("")
        if prev_f1 is not None and f1 + 1e-9 < prev_f1 - 0.02 and first is None:
            first = stage.name
        prev_f1 = f1

    if first == "cleaned":
        conclusion = "Likely note loss introduced after raw transcription (cleaner)."
    elif first == "structured":
        conclusion = "Likely quality drop introduced after cleaning (structure / MIR)."
    elif stages and float(stages[0].metrics.get("onset_pitch_f1") or 0) < 0.85:
        conclusion = "Primary quality gap appears at raw transcription."
        first = first or "raw"
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
