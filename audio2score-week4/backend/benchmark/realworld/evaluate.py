"""Run the production Fast pipeline on one real-world case. No algorithm changes."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmark.metrics import (
    match_notes,
    mean_onset_error_ms,
    notation_from_plan,
    pitch_accuracy,
    xml_structure_valid,
)
from benchmark.note_extract import notes_from_midi
from benchmark.realworld.schema import RealWorldCase
from mir.midi_ingest import ingest_midi
from mir.pipeline import UnderstandingPipeline
from mir.types import Hand, MusicalEvent, NoteEvent


def _hand_metrics_seconds(
    predicted: list[MusicalEvent],
    reference: list[NoteEvent],
    onset_tolerance_sec: float = 0.08,
) -> dict[str, Any]:
    """Compare production hands to reference MIDI track hands (seconds, not beats)."""
    used: set[int] = set()
    correct = 0
    total = 0
    confusion: dict[str, int] = {}
    labeled = [n for n in reference if n.hand in (Hand.LEFT, Hand.RIGHT)]
    for ref in labeled:
        best_i = None
        best_dt = float("inf")
        for i, ev in enumerate(predicted):
            if i in used:
                continue
            if int(ev.pitch) != int(ref.pitch):
                continue
            pred_t = ev.start_time_sec
            if pred_t is None:
                continue
            dt = abs(float(pred_t) - float(ref.start_time))
            if dt <= onset_tolerance_sec and dt < best_dt:
                best_dt = dt
                best_i = i
        if best_i is None:
            continue
        used.add(best_i)
        got = predicted[best_i].hand.value
        expected = ref.hand.value
        total += 1
        key = f"{expected}->{got}"
        confusion[key] = confusion.get(key, 0) + 1
        if got == expected:
            correct += 1
    return {
        "accuracy": (correct / total) if total else None,
        "total": total,
        "correct": correct,
        "confusion": confusion,
        "reference_labeled": len(labeled),
    }


def _note_scores(predicted: list[NoteEvent], reference: list[NoteEvent] | None) -> dict[str, Any]:
    if reference is None:
        return {
            "precision": None,
            "recall": None,
            "f1": None,
            "onset_error_ms": None,
            "pitch_accuracy": None,
            "predicted_count": len(predicted),
            "reference_count": None,
        }
    metrics = match_notes(predicted, reference, onset_tolerance_sec=0.08)
    return {
        "precision": metrics.precision,
        "recall": metrics.recall,
        "f1": metrics.f1,
        "onset_error_ms": mean_onset_error_ms(metrics),
        "pitch_accuracy": pitch_accuracy(metrics),
        "predicted_count": len(predicted),
        "reference_count": len(reference),
    }


def _load_midi_notes(path: Path | None) -> list[NoteEvent] | None:
    if path is None or not path.is_file():
        return None
    ingested = ingest_midi(path)
    return list(ingested.notes)


@dataclass
class RealWorldEval:
    case_id: str
    status: str
    title: str | None = None
    instrumentation: str | None = None
    notes: str | None = None
    skip_reason: str | None = None
    error: str | None = None
    meter: dict[str, Any] = field(default_factory=dict)
    tempo_bpm: float | None = None
    transcription: dict[str, Any] = field(default_factory=dict)
    score_midi: dict[str, Any] = field(default_factory=dict)
    hands: dict[str, Any] = field(default_factory=dict)
    notation: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    meter_decision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "title": self.title,
            "status": self.status,
            "instrumentation": self.instrumentation,
            "notes": self.notes,
            "skip_reason": self.skip_reason,
            "error": self.error,
            "meter": self.meter,
            "tempo_bpm": self.tempo_bpm,
            "transcription": self.transcription,
            "score_midi": self.score_midi,
            "hands": self.hands,
            "notation": self.notation,
            "artifacts": self.artifacts,
            "meter_decision": self.meter_decision,
        }


def evaluate_realworld_case(
    case: RealWorldCase,
    *,
    work_root: Path,
    pipeline: UnderstandingPipeline | None = None,
) -> RealWorldEval:
    """Observe production Fast output. Never a per-song pass/fail gate."""
    row = RealWorldEval(
        case_id=case.case_id,
        status="skipped",
        title=case.title,
        instrumentation=case.instrumentation,
        notes=case.notes,
    )
    if case.audio_missing():
        row.skip_reason = "audio file not found (local corpus not present)"
        return row

    work = Path(work_root) / case.case_id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    src = work / f"input{case.audio_path.suffix.lower() or '.wav'}"
    shutil.copy2(case.audio_path, src)

    pipe = pipeline or UnderstandingPipeline(mode="fast")
    xml = ""
    try:
        xml = pipe.transcribe(src, case.case_id)
    except Exception as exc:
        row.status = "error"
        row.error = f"{type(exc).__name__}: {exc}"
        return row

    out_dir = src.parent / f"bp_{case.case_id}"
    raw_midi = out_dir / f"{case.case_id}.raw.mid"
    score_midi = out_dir / f"{case.case_id}.score.mid"
    musicxml = out_dir / f"{case.case_id}.musicxml"
    debug_json = out_dir / f"{case.case_id}.debug.json"

    predicted = notes_from_midi(raw_midi) if raw_midi.exists() else []
    performance_ref = _load_midi_notes(case.reference_performance_midi)
    score_ref = _load_midi_notes(case.reference_score_midi)
    row.transcription = _note_scores(predicted, performance_ref)
    row.score_midi = _note_scores(predicted, score_ref)

    writer = pipe.notation
    plan = writer.last_plan
    xml_ok, xml_errors = xml_structure_valid(xml)
    plan_bits = notation_from_plan(plan) if plan is not None else {}
    row.notation = {
        "plan_success": plan is not None and not writer.last_fallback_used,
        "fallback_used": bool(writer.last_fallback_used),
        "fallback_reason": writer.last_fallback_error,
        "measure_count": int(plan_bits.get("measure_count") or 0),
        "voice_sum_ok": bool(plan_bits.get("voice_sum_ok")) if plan_bits else None,
        "xml_valid": xml_ok,
        "xml_errors": xml_errors,
    }

    selected_meter = None
    if plan is not None:
        selected_meter = plan.time_signature
    elif pipe.last_debug is not None:
        selected_meter = pipe.last_debug.selected_meter
    decision = getattr(pipe, "last_meter_decision", None)
    row.meter = {
        "predicted": selected_meter,
        "expected": case.expected_meter,
        "observational_match": (
            None
            if not case.expected_meter or not selected_meter
            else (
                selected_meter in ("4/4", "2/4")
                if case.expected_meter == "4/4"
                else selected_meter == case.expected_meter
            )
        ),
    }
    row.meter_decision = decision.to_dict() if decision is not None else None

    tempo = None
    if pipe.last_debug is not None:
        tempo = float(pipe.last_debug.selected_tempo_bpm)
    elif pipe.last_structure is not None and pipe.last_structure.tempo_map is not None:
        tempo = float(pipe.last_structure.tempo_map.bpm_at(0.0))
    row.tempo_bpm = tempo

    production_hands = {}
    events = list(pipe.last_structure.events) if pipe.last_structure is not None else []
    if events:
        production_hands = {
            "left": sum(1 for e in events if e.hand == Hand.LEFT),
            "right": sum(1 for e in events if e.hand == Hand.RIGHT),
            "unknown": sum(1 for e in events if e.hand == Hand.UNKNOWN),
            "ambiguous": sum(1 for e in events if e.hand == Hand.AMBIGUOUS),
        }
    hand_compare = {}
    if performance_ref:
        hand_compare = _hand_metrics_seconds(events, performance_ref)
    row.hands = {
        "assignments": production_hands,
        "versus_reference": hand_compare,
    }

    row.artifacts = {
        "audio": str(src),
        "musicxml": str(musicxml) if musicxml.exists() else None,
        "raw_midi": str(raw_midi) if raw_midi.exists() else None,
        "score_midi": str(score_midi) if score_midi.exists() else None,
        "debug_json": str(debug_json) if debug_json.exists() else None,
        "reference_performance_midi": (
            str(case.reference_performance_midi)
            if case.reference_performance_midi and case.reference_performance_midi.is_file()
            else None
        ),
        "reference_score_midi": (
            str(case.reference_score_midi)
            if case.reference_score_midi and case.reference_score_midi.is_file()
            else None
        ),
    }
    row.status = "ran"
    return row
