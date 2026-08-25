"""Execute one evaluation case through the production pipeline."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluation.metrics import (
    NOT_EVALUATED,
    compare_stage_notes,
    hand_metrics,
    meter_metrics,
    tempo_metrics,
)
from evaluation.normalize import NormalizedReference, normalize_reference_midi
from evaluation.schema import CaseSpec
from evaluation.stages import capture_transcription_stages, copy_musicxml
from mir.pipeline import UnderstandingPipeline


@dataclass
class CaseResult:
    case_id: str
    split: str
    status: str
    title: str | None = None
    skip_reason: str | None = None
    error: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)
    meter: dict[str, Any] = field(default_factory=dict)
    tempo: dict[str, Any] = field(default_factory=dict)
    hands: dict[str, Any] = field(default_factory=dict)
    pipeline: dict[str, Any] = field(default_factory=dict)
    stages: dict[str, Any] = field(default_factory=dict)
    reference: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "split": self.split,
            "status": self.status,
            "title": self.title,
            "skip_reason": self.skip_reason,
            "error": self.error,
            "notes": self.notes,
            "meter": self.meter,
            "tempo": self.tempo,
            "hands": self.hands,
            "pipeline": self.pipeline,
            "stages": self.stages,
            "reference": self.reference,
            "artifacts": self.artifacts,
            "tags": self.tags,
            "onset_pitch_f1": (self.notes or {}).get("onset_pitch_f1"),
        }


def _resolve_expected_meter(case: CaseSpec, ref: NormalizedReference) -> str | None:
    return case.expected_meter or ref.time_signature


def _resolve_expected_tempo(case: CaseSpec, ref: NormalizedReference) -> float | None:
    if case.expected_tempo_bpm is not None:
        return float(case.expected_tempo_bpm)
    return ref.tempo_bpm


def evaluate_case(
    case: CaseSpec,
    *,
    case_out_dir: Path,
    pipeline: UnderstandingPipeline | None = None,
) -> CaseResult:
    """Run production Fast pipeline and compute evaluation metrics."""
    result = CaseResult(
        case_id=case.case_id,
        split=case.split,
        status="skipped",
        title=case.title,
        tags=list(case.tags),
    )

    if case.missing_audio():
        result.skip_reason = "missing input audio"
        return result
    if case.missing_reference():
        result.skip_reason = "missing reference MIDI"
        return result

    out = Path(case_out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    # Work copy so pipeline writes stay inside the results tree
    work = out / "work"
    work.mkdir(parents=True, exist_ok=True)
    suffix = case.audio_path.suffix.lower() or ".wav"
    audio_copy = work / f"input{suffix}"
    shutil.copy2(case.audio_path, audio_copy)

    # Normalize reference in memory only — never mutate the source file
    ref = normalize_reference_midi(case.reference_midi)
    # Keep an untouched copy of the reference beside outputs for inspection
    ref_copy = out / "reference.mid"
    shutil.copy2(case.reference_midi, ref_copy)
    result.reference = ref.to_dict()

    pipe = pipeline or UnderstandingPipeline(mode="fast")
    xml = ""
    try:
        xml = pipe.transcribe(audio_copy, case.case_id)
    except Exception as exc:
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"
        _write_case_files(out, result, diagnostics_text=result.error or "")
        return result

    job_dir = audio_copy.parent / f"bp_{case.case_id}"
    raw_midi = job_dir / f"{case.case_id}.raw.mid"
    score_midi = job_dir / f"{case.case_id}.score.mid"
    musicxml_src = job_dir / f"{case.case_id}.musicxml"
    debug_json = job_dir / f"{case.case_id}.debug.json"
    norm_wav = job_dir / f"{case.case_id}_norm.wav"

    musicxml_ok = copy_musicxml(
        musicxml_src if musicxml_src.exists() else None,
        out / "output.musicxml",
    )
    if xml and not musicxml_ok:
        (out / "output.musicxml").write_text(xml, encoding="utf-8")
        musicxml_ok = True

    writer = pipe.notation
    plan = writer.last_plan
    debug = pipe.last_debug
    structure = pipe.last_structure
    decision = pipe.last_meter_decision

    predicted_meter = None
    if plan is not None:
        predicted_meter = plan.time_signature
    elif debug is not None:
        predicted_meter = debug.selected_meter

    expected_meter = _resolve_expected_meter(case, ref)
    result.meter = meter_metrics(
        predicted=predicted_meter,
        expected=expected_meter,
        confidence=(
            decision.confidence
            if decision is not None
            else (debug.meter_confidence if debug else None)
        ),
        reason=(decision.reason if decision is not None else None),
    )

    predicted_tempo = None
    if debug is not None:
        predicted_tempo = float(debug.selected_tempo_bpm)
    elif structure is not None and structure.tempo_map is not None:
        predicted_tempo = float(structure.tempo_map.bpm_at(0.0))
    result.tempo = tempo_metrics(
        predicted_bpm=predicted_tempo,
        reference_bpm=_resolve_expected_tempo(case, ref),
    )

    events = list(structure.events) if structure is not None else []
    result.hands = hand_metrics(events, ref.notes)

    # Final note metrics: prefer structured events (seconds), else pipeline raw.mid
    from evaluation.stages import events_to_notes
    from benchmark.note_extract import notes_from_midi

    if events and structure is not None:
        final_notes = events_to_notes(
            events,
            tempo_map=structure.tempo_map,
            fallback_bpm=predicted_tempo or 120.0,
        )
    elif raw_midi.exists():
        final_notes = notes_from_midi(raw_midi)
    else:
        final_notes = []
    result.notes = compare_stage_notes(final_notes, ref.notes)

    diagnostics = capture_transcription_stages(
        out_dir=out,
        reference_notes=ref.notes,
        raw_notes=pipe.last_raw_notes,
        cleaned_notes=pipe.last_cleaned_notes,
        post_piano_notes=pipe.last_post_piano_notes,
        structured_events=events,
        tempo_map=structure.tempo_map if structure is not None else None,
        tempo_bpm=predicted_tempo or ref.tempo_bpm or 120.0,
        clean_decisions=pipe.last_clean_decisions,
        pipeline_info={
            "raw_note_count": (
                len(pipe.last_raw_notes) if pipe.last_raw_notes is not None else None
            ),
            "cleaned_note_count": (
                len(pipe.last_cleaned_notes)
                if pipe.last_cleaned_notes is not None
                else None
            ),
            "post_piano_note_count": (
                len(pipe.last_post_piano_notes)
                if pipe.last_post_piano_notes is not None
                else None
            ),
            "structured_note_count": len(events),
            "stage_source": "pipeline_snapshots",
        },
    )
    result.stages = diagnostics.to_dict()

    result.pipeline = {
        "raw_note_count": (
            len(pipe.last_raw_notes) if pipe.last_raw_notes is not None else None
        ),
        "cleaned_note_count": (
            len(pipe.last_cleaned_notes) if pipe.last_cleaned_notes is not None else None
        ),
        "post_piano_note_count": (
            len(pipe.last_post_piano_notes)
            if pipe.last_post_piano_notes is not None
            else None
        ),
        "structured_note_count": len(events),
        "notation_plan_success": plan is not None and not writer.last_fallback_used,
        "fallback_used": bool(writer.last_fallback_used),
        "fallback_reason": writer.last_fallback_error,
        "notation_path": (
            (debug.extra or {}).get("notation_path") if debug else None
        ),
        "cleaner_suppressions": len(pipe.last_clean_decisions or []),
        "musicxml_success": musicxml_ok and bool(xml),
        "source_backend": debug.source_backend if debug else None,
    }

    # Prefer structured-stage F1 as the headline when available
    structured_metrics = None
    for stage in diagnostics.stages:
        if stage.name == "structured":
            structured_metrics = stage.metrics
            break
    if structured_metrics:
        result.notes = structured_metrics

    result.artifacts = {
        "case_dir": str(case.case_dir),
        "audio": str(case.audio_path),
        "reference_midi": str(case.reference_midi),
        "output_musicxml": str(out / "output.musicxml") if musicxml_ok else None,
        "transcription_midi": str(out / "transcription.mid")
        if (out / "transcription.mid").exists()
        else None,
        "post_cleaner_midi": str(out / "post_cleaner.mid")
        if (out / "post_cleaner.mid").exists()
        else None,
        "post_piano_midi": str(out / "post_piano.mid")
        if (out / "post_piano.mid").exists()
        else None,
        "structured_midi": str(out / "structured.mid")
        if (out / "structured.mid").exists()
        else None,
        "pipeline_raw_midi": str(raw_midi) if raw_midi.exists() else None,
        "pipeline_score_midi": str(score_midi) if score_midi.exists() else None,
        "pipeline_debug_json": str(debug_json) if debug_json.exists() else None,
        "results_dir": str(out),
    }
    result.status = "ran"
    _write_case_files(out, result, diagnostics_text=diagnostics.conclusion)
    return result


def _write_case_files(
    out: Path,
    result: CaseResult,
    *,
    diagnostics_text: str,
) -> None:
    (out / "metrics.json").write_text(
        json.dumps(result.to_dict(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    diagnostics_payload = {
        "case_id": result.case_id,
        "status": result.status,
        "stages": result.stages,
        "pipeline": result.pipeline,
        "conclusion": diagnostics_text,
    }
    (out / "diagnostics.json").write_text(
        json.dumps(diagnostics_payload, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    (out / "report.md").write_text(
        _case_report_markdown(result, diagnostics_text),
        encoding="utf-8",
    )


def _case_report_markdown(result: CaseResult, diagnostics_text: str) -> str:
    notes = result.notes or {}
    meter = result.meter or {}
    tempo = result.tempo or {}
    hands = result.hands or {}
    pipe = result.pipeline or {}
    lines = [
        f"# Case `{result.case_id}`",
        "",
        f"- split: `{result.split}`",
        f"- status: **{result.status}**",
        f"- title: {result.title or result.case_id}",
        "",
        "## Notes",
        "",
        f"- reference: {notes.get('reference_count', '—')}",
        f"- predicted: {notes.get('predicted_count', '—')}",
        f"- matched: {notes.get('matched', '—')}",
        f"- FP / FN: {notes.get('false_positives', '—')} / {notes.get('false_negatives', '—')}",
        f"- onset F1: {_fmt(notes.get('onset_f1'))}",
        f"- onset+pitch F1: {_fmt(notes.get('onset_pitch_f1'))}",
        f"- onset+pitch+offset F1: {_fmt(notes.get('onset_pitch_offset_f1'))}",
        f"- mean onset error: {_fmt(notes.get('mean_onset_error_ms'), ' ms')}",
        f"- median onset error: {_fmt(notes.get('median_onset_error_ms'), ' ms')}",
        "",
        "## Meter",
        "",
        f"- predicted: {meter.get('predicted') or '—'}",
        f"- expected: {meter.get('expected') or '—'}",
        f"- status: {meter.get('status') or NOT_EVALUATED}",
        f"- confidence: {_fmt(meter.get('confidence'))}",
        f"- reason: {meter.get('reason') or '—'}",
        "",
        "## Tempo",
        "",
        f"- reference: {_fmt(tempo.get('reference_bpm'))} bpm",
        f"- predicted: {_fmt(tempo.get('predicted_bpm'))} bpm",
        f"- error: {_fmt(tempo.get('error_bpm'))} bpm",
        f"- status: {tempo.get('status') or NOT_EVALUATED}",
        "",
        "## Hands",
        "",
    ]
    if hands.get("status") == NOT_EVALUATED or hands.get("status") is None and not hands:
        lines.append(f"- {NOT_EVALUATED}")
    else:
        lines += [
            f"- status: {hands.get('status')}",
            f"- accuracy: {_fmt(hands.get('accuracy'))}",
            f"- LH→RH: {hands.get('lh_to_rh', 0)}",
            f"- RH→LH: {hands.get('rh_to_lh', 0)}",
        ]
    lines += [
        "",
        "## Pipeline",
        "",
        f"- raw → cleaned → structured: "
        f"{pipe.get('raw_note_count')} → {pipe.get('cleaned_note_count')} → "
        f"{pipe.get('structured_note_count')}",
        f"- NotationPlan success: {pipe.get('notation_plan_success')}",
        f"- fallback_used: {pipe.get('fallback_used')}",
        f"- notation_path: {pipe.get('notation_path')}",
        f"- cleaner suppressions: {pipe.get('cleaner_suppressions')}",
        f"- MusicXML success: {pipe.get('musicxml_success')}",
        "",
        "## Stage diagnostics",
        "",
        "```",
        diagnostics_text.strip(),
        "```",
        "",
    ]
    if result.skip_reason:
        lines.append(f"Skip reason: {result.skip_reason}")
    if result.error:
        lines.append(f"Error: {result.error}")
    return "\n".join(lines) + "\n"


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}{suffix}"
    return f"{value}{suffix}"
