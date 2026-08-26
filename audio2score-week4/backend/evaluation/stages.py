"""Capture per-stage note lists from a single production pipeline run.

Stages are observation snapshots taken during UnderstandingPipeline.transcribe —
this module never re-invokes Basic Pitch or the cleaner.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from evaluation.defaults import RAW_REFERENCE_STAGES
from evaluation.matching import match_notes
from mir.raw_midi import write_events_to_midi, write_notes_to_midi
from mir.types import MusicalEvent, NoteEvent, TempoMap


# Honest labels matching the production order:
# Basic Pitch → Cleaner → PianoAnalyzer → MIR structure
STAGE_ORDER = ("transcription", "post_cleaner", "post_piano", "structured")

# Backward-compatible aliases used in older reports/tests
_STAGE_ALIASES = {
    "raw": "transcription",
    "cleaned": "post_cleaner",
}


@dataclass
class StageSnapshot:
    name: str
    notes: list[NoteEvent]
    midi_path: Path | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    reference_role: str | None = None  # "raw" | "score" | None


@dataclass
class StageDiagnostics:
    stages: list[StageSnapshot] = field(default_factory=list)
    first_degradation_stage: str | None = None
    conclusion: str = ""
    pipeline: dict[str, Any] = field(default_factory=dict)
    score_evaluation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stages": [
                {
                    "name": s.name,
                    "note_count": len(s.notes),
                    "midi_path": str(s.midi_path) if s.midi_path else None,
                    "metrics": s.metrics,
                    "extra": s.extra,
                    "reference_role": s.reference_role,
                }
                for s in self.stages
            ],
            "first_degradation_stage": self.first_degradation_stage,
            "conclusion": self.conclusion,
            "pipeline": self.pipeline,
            "score_evaluation": self.score_evaluation,
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


def _score_metrics_from_match(match: dict[str, Any]) -> dict[str, Any]:
    """Map note-match metrics into an explicit score namespace."""
    return {
        "quantized_note_f1": match.get("onset_pitch_f1"),
        "onset_pitch_f1": match.get("onset_pitch_f1"),
        "onset_f1": match.get("onset_f1"),
        "onset_pitch_offset_f1": match.get("onset_pitch_offset_f1"),
        "duration_accuracy": (
            None
            if match.get("mean_duration_error_ms") is None
            else max(0.0, 1.0 - (float(match["mean_duration_error_ms"]) / 500.0))
        ),
        "mean_duration_error_ms": match.get("mean_duration_error_ms"),
        "mean_onset_error_ms": match.get("mean_onset_error_ms"),
        "reference_count": match.get("reference_count"),
        "predicted_count": match.get("predicted_count"),
        "matched": match.get("matched"),
        "false_positives": match.get("false_positives"),
        "false_negatives": match.get("false_negatives"),
        "measure_alignment": "unavailable",
        "rhythm_accuracy": match.get("onset_pitch_offset_f1"),
        "status": "evaluated",
    }


def capture_transcription_stages(
    *,
    out_dir: Path,
    reference_notes: Sequence[NoteEvent] | None,
    raw_notes: Sequence[NoteEvent] | None,
    cleaned_notes: Sequence[NoteEvent] | None,
    post_piano_notes: Sequence[NoteEvent] | None,
    structured_events: Sequence[MusicalEvent] | None,
    tempo_map: TempoMap | None,
    tempo_bpm: float,
    clean_decisions: Sequence[Any] | None = None,
    pipeline_info: dict[str, Any] | None = None,
    reference_score_notes: Sequence[NoteEvent] | None = None,
    has_score_reference: bool | None = None,
    has_raw_reference: bool | None = None,
) -> StageDiagnostics:
    """Write stage MIDIs and metrics from one pipeline run's snapshots.

    Does not call Basic Pitch or MIDICleaner. Missing snapshots are skipped.

    Raw stages (transcription / post_cleaner / post_piano) are scored against
    ``reference_notes`` (raw performance) only when a raw reference exists.
    Structured stage is scored against ``reference_score_notes`` when provided;
    otherwise score evaluation is marked unavailable (never faked against the
    raw reference, and raw stages are never scored against the score MIDI).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    suppressions = _suppression_rows(clean_decisions)
    stages: list[StageSnapshot] = []
    raw_ref = list(reference_notes) if reference_notes is not None else None
    score_ref = list(reference_score_notes) if reference_score_notes is not None else None
    if has_raw_reference is None:
        has_raw_reference = raw_ref is not None
    if has_score_reference is None:
        has_score_reference = score_ref is not None

    def _add_note_stage(
        name: str,
        notes: Sequence[NoteEvent] | None,
        filename: str,
        *,
        source: str,
        reference: Sequence[NoteEvent] | None,
        reference_role: str,
        score_against_reference: bool,
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
        if score_against_reference and reference is not None:
            metrics = match_notes(note_list, reference).to_dict()
            extra_payload = {"source": source, **(extra or {})}
        else:
            metrics = {}
            extra_payload = {
                "source": source,
                "raw_evaluation": "unavailable",
                "reason": "no raw performance reference; refusing to compare to score MIDI",
                **(extra or {}),
            }
        stages.append(
            StageSnapshot(
                name=name,
                notes=note_list,
                midi_path=midi_path,
                metrics=metrics,
                extra=extra_payload,
                reference_role=reference_role if score_against_reference else None,
            )
        )

    _add_note_stage(
        "transcription",
        raw_notes,
        "transcription.mid",
        source="pipeline.last_raw_notes",
        reference=raw_ref,
        reference_role="raw",
        score_against_reference=bool(has_raw_reference and raw_ref is not None),
    )
    _add_note_stage(
        "post_cleaner",
        cleaned_notes,
        "post_cleaner.mid",
        source="pipeline.last_cleaned_notes",
        reference=raw_ref,
        reference_role="raw",
        score_against_reference=bool(has_raw_reference and raw_ref is not None),
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
        reference=raw_ref,
        reference_role="raw",
        score_against_reference=bool(has_raw_reference and raw_ref is not None),
    )

    score_evaluation: dict[str, Any] = {
        "status": "unavailable",
        "reason": "no score reference provided",
    }

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
        if has_score_reference and score_ref is not None:
            score_match = match_notes(structured_notes, score_ref).to_dict()
            score_evaluation = _score_metrics_from_match(score_match)
            stages.append(
                StageSnapshot(
                    name="structured",
                    notes=structured_notes,
                    midi_path=structured_midi,
                    metrics=score_match,
                    extra={
                        "source": "pipeline.last_structure.events",
                        "compared_to": "reference_score",
                    },
                    reference_role="score",
                )
            )
        else:
            score_evaluation = {
                "status": "unavailable",
                "reason": (
                    "structured stage present but no distinct score reference; "
                    "refusing to compare structured notes to raw performance MIDI"
                ),
            }
            stages.append(
                StageSnapshot(
                    name="structured",
                    notes=structured_notes,
                    midi_path=structured_midi,
                    metrics={},
                    extra={
                        "source": "pipeline.last_structure.events",
                        "score_evaluation": "unavailable",
                        "reason": score_evaluation["reason"],
                    },
                    reference_role=None,
                )
            )
    elif has_score_reference:
        score_evaluation = {
            "status": "unavailable",
            "reason": "score reference present but structured stage produced no events",
        }

    raw_stages = [
        s
        for s in stages
        if s.reference_role == "raw"
        or (s.name in RAW_REFERENCE_STAGES and s.metrics)
    ]
    ref_count = len(raw_ref) if raw_ref is not None else 0
    if raw_stages:
        first_deg, conclusion = _first_degradation(
            raw_stages,
            reference_count=ref_count,
        )
    elif has_score_reference and score_evaluation.get("status") == "evaluated":
        first_deg = None
        conclusion = (
            "No raw performance reference; score-stage metrics only "
            f"(quantized_note_f1={score_evaluation.get('quantized_note_f1')})."
        )
    else:
        first_deg, conclusion = _first_degradation(
            stages,
            reference_count=ref_count,
        )
    return StageDiagnostics(
        stages=stages,
        first_degradation_stage=first_deg,
        conclusion=conclusion,
        pipeline=pipeline_info or {},
        score_evaluation=score_evaluation,
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
        "structured": "AFTER STRUCTURE / MIR",
        # aliases
        "raw": "TRANSCRIPTION (Basic Pitch)",
        "cleaned": "AFTER CLEANER",
    }
    lines = [f"REFERENCE_RAW\n{reference_count} notes", ""]
    prev_f1 = None
    first = None
    for stage in stages:
        f1 = float((stage.metrics or {}).get("onset_pitch_f1") or 0.0)
        count = int((stage.metrics or {}).get("predicted_count") or len(stage.notes))
        lines.append(labels.get(stage.name, stage.name.upper()))
        lines.append(f"{count} predicted")
        if stage.metrics:
            lines.append(f"F1 {f1:.2f}")
        else:
            lines.append("score_evaluation: unavailable")
        lines.append("")
        if not stage.metrics:
            continue
        if prev_f1 is not None and f1 + 1e-9 < prev_f1 - 0.02 and first is None:
            first = stage.name
        prev_f1 = f1

    if first == "post_cleaner" or first == "cleaned":
        conclusion = "Likely note loss introduced after transcription (cleaner)."
    elif first == "post_piano":
        conclusion = "Likely change introduced after cleaner (piano analyzer)."
    elif first == "structured":
        conclusion = "Likely quality drop introduced after piano stage (structure / MIR)."
    elif stages and stages[0].metrics and float(stages[0].metrics.get("onset_pitch_f1") or 0) < 0.85:
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

