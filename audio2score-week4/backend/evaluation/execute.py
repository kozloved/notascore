"""Execute one evaluation case through the production pipeline."""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evaluation.metrics import (
    NOT_EVALUATED,
    compare_stage_notes,
    hand_metrics,
    meter_metrics,
    notation_metrics,
    tempo_metrics,
)
from evaluation.normalize import NormalizedReference, normalize_reference_midi
from evaluation.preservation import stage_preservation_bundle
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
    notation: dict[str, Any] = field(default_factory=dict)
    reference: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    preservation: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    original_vs_reference: dict[str, Any] = field(default_factory=dict)
    validation_delta: dict[str, Any] = field(default_factory=dict)
    hashes: dict[str, Any] = field(default_factory=dict)

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
            "notation": self.notation,
            "reference": self.reference,
            "artifacts": self.artifacts,
            "tags": self.tags,
            "preservation": self.preservation,
            "execution": self.execution,
            "original_vs_reference": self.original_vs_reference,
            "validation_delta": self.validation_delta,
            "hashes": self.hashes,
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
    execution_path: str = "isolated",
    mode: str = "solo",
    pipeline_mode_name: str | None = None,
    validation_mode: str | None = None,
) -> CaseResult:
    """Run one case.

    `isolated` uses UnderstandingPipeline directly (stage tests).
    `production` uses engine.job_runner.run_job, the application entry point.
    A shared `pipeline` instance is only reused when the caller passes one.
    """
    result = CaseResult(
        case_id=case.case_id,
        split=case.split,
        status="skipped",
        title=case.title,
        tags=list(case.tags),
    )
    path = (execution_path or "isolated").strip().lower()
    if path not in {"isolated", "production"}:
        path = "isolated"
    requested_mode = mode or "solo"
    from modes import POLYPHONIC, parse_transcription_mode

    try:
        canonical_mode = parse_transcription_mode(requested_mode)
    except ValueError:
        canonical_mode = requested_mode
    result.execution = {
        "path": path,
        "requested_mode": requested_mode,
        "canonical_mode": canonical_mode,
        "requested_pipeline_mode": pipeline_mode_name,
        "validation_mode": validation_mode,
    }

    if case.missing_audio():
        result.skip_reason = "missing input audio"
        return result
    if case.missing_reference():
        result.skip_reason = "missing reference MIDI"
        return result

    needs_mt3 = False
    try:
        from modes import is_polyphonic

        needs_mt3 = is_polyphonic(requested_mode)
    except ValueError:
        needs_mt3 = requested_mode in {"polyphonic", "quality", "mt3"}
    if needs_mt3 and pipeline is None:
        from adapters.mt3_backend import mt3_available

        if not mt3_available():
            result.skip_reason = (
                "live MT3 infrastructure is not configured "
                "(set MT3_ENDPOINT or MT3_TRANSCRIBE_COMMAND)"
            )
            result.execution["missing_infrastructure"] = "mt3"
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

    started = time.perf_counter()
    pipe: UnderstandingPipeline | None = None
    xml = ""
    previous_pipeline_mode = os.environ.get("NEXTGEN_PIPELINE_MODE")
    actual_pipeline_mode = pipeline_mode_name or previous_pipeline_mode
    try:
        if path == "production":
            if pipeline_mode_name:
                os.environ["NEXTGEN_PIPELINE_MODE"] = pipeline_mode_name
            from engine.flags import pipeline_mode
            from engine.job_runner import run_job

            actual_pipeline_mode = pipeline_mode()
            xml = run_job(
                audio_copy,
                case.case_id,
                mode=canonical_mode,
                filename=audio_copy.name,
            )
        else:
            if pipeline is not None:
                pipe = pipeline
            elif canonical_mode == POLYPHONIC:
                pipe = UnderstandingPipeline(
                    backend_name="mt3",
                    mode=POLYPHONIC,
                    validation_mode=validation_mode,
                )
            else:
                pipe = UnderstandingPipeline(
                    mode=canonical_mode,
                    validation_mode=validation_mode,
                )
            xml = pipe.transcribe(audio_copy, case.case_id)
    except Exception as exc:
        result.status = "error"
        result.error = f"{type(exc).__name__}: {exc}"
        result.execution["wall_ms"] = (time.perf_counter() - started) * 1000.0
        result.execution["actual_pipeline_mode"] = actual_pipeline_mode
        _restore_pipeline_mode(previous_pipeline_mode, pipeline_mode_name)
        _write_case_files(out, result, diagnostics_text=result.error or "")
        return result
    _restore_pipeline_mode(previous_pipeline_mode, pipeline_mode_name)
    result.execution["wall_ms"] = (time.perf_counter() - started) * 1000.0
    result.execution["actual_pipeline_mode"] = actual_pipeline_mode

    job_dir = audio_copy.parent / f"bp_{case.case_id}"
    raw_midi = job_dir / f"{case.case_id}.raw.mid"
    validated_midi = job_dir / f"{case.case_id}.validated.mid"
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

    writer = getattr(pipe, "notation", None) if pipe is not None else None
    plan = getattr(writer, "last_plan", None) if writer is not None else None
    debug = getattr(pipe, "last_debug", None) if pipe is not None else None
    structure = getattr(pipe, "last_structure", None) if pipe is not None else None
    decision = getattr(pipe, "last_meter_decision", None) if pipe is not None else None
    debug_payload = {}
    if debug_json.exists():
        try:
            debug_payload = json.loads(debug_json.read_text(encoding="utf-8"))
        except Exception:
            debug_payload = {}
    trans_payload = {}
    trans_json = job_dir / f"{case.case_id}.transcription.json"
    if trans_json.exists():
        try:
            trans_payload = json.loads(trans_json.read_text(encoding="utf-8"))
        except Exception:
            trans_payload = {}

    predicted_meter = None
    if plan is not None:
        predicted_meter = plan.time_signature
    elif debug is not None:
        predicted_meter = debug.selected_meter
    elif debug_payload:
        predicted_meter = debug_payload.get("selected_meter")

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
    elif debug_payload.get("selected_tempo_bpm") is not None:
        predicted_tempo = float(debug_payload["selected_tempo_bpm"])
    result.tempo = tempo_metrics(
        predicted_bpm=predicted_tempo,
        reference_bpm=_resolve_expected_tempo(case, ref),
    )

    events = list(structure.events) if structure is not None else []
    result.hands = hand_metrics(events, ref.notes)
    result.notation = notation_metrics(plan)

    quantized_events = list(getattr(pipe, "last_quantized_events", None) or [])

    # Final note metrics: prefer structured events (seconds), else pipeline raw.mid
    from evaluation.stages import events_to_notes
    from benchmark.note_extract import notes_from_midi
    from mir.raw_identity import hash_file, sha256_hex

    raw_notes = getattr(pipe, "last_raw_notes", None)
    cleaned_notes = getattr(pipe, "last_cleaned_notes", None)
    post_piano_notes = getattr(pipe, "last_post_piano_notes", None)
    validated_notes = getattr(pipe, "last_validated_notes", None)
    if raw_notes is None and raw_midi.exists():
        raw_notes = notes_from_midi(raw_midi)
    if cleaned_notes is None and validated_midi.exists():
        cleaned_notes = notes_from_midi(validated_midi)
        validated_notes = list(cleaned_notes)
    if post_piano_notes is None:
        post_piano_notes = list(cleaned_notes or [])

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
    result.original_vs_reference = compare_stage_notes(raw_notes or [], ref.notes)
    result.validation_delta = {
        "filter": (
            getattr(pipe, "last_filter_report", None).to_dict()
            if getattr(getattr(pipe, "last_filter_report", None), "to_dict", None)
            else (debug_payload.get("extra") or {}).get("filter")
        ),
        "raw_note_count": len(raw_notes or []),
        "filtered_note_count": (
            len(getattr(pipe, "last_filtered_notes", None) or [])
            if getattr(pipe, "last_filtered_notes", None) is not None
            else None
        ),
        "validated_note_count": len(validated_notes or []),
    }

    extra_debug = {}
    if debug is not None:
        extra_debug = dict(debug.extra or {})
    elif isinstance(debug_payload.get("extra"), dict):
        extra_debug = dict(debug_payload.get("extra") or {})

    diagnostics = capture_transcription_stages(
        out_dir=out,
        reference_notes=ref.notes,
        raw_notes=raw_notes,
        cleaned_notes=cleaned_notes,
        post_piano_notes=post_piano_notes,
        structured_events=events,
        tempo_map=structure.tempo_map if structure is not None else None,
        tempo_bpm=predicted_tempo or ref.tempo_bpm or 120.0,
        clean_decisions=getattr(pipe, "last_clean_decisions", None),
        quantized_events=quantized_events or None,
        pipeline_info={
            "raw_note_count": len(raw_notes) if raw_notes is not None else None,
            "cleaned_note_count": (
                len(cleaned_notes) if cleaned_notes is not None else None
            ),
            "post_piano_note_count": (
                len(post_piano_notes) if post_piano_notes is not None else None
            ),
            "structured_note_count": len(events),
            "quantized_note_count": len(quantized_events),
            "validated_note_count": (
                len(validated_notes) if validated_notes is not None else None
            ),
            "stage_source": (
                "pipeline_snapshots" if pipe is not None else "production_artifacts"
            ),
            "validation_mode": (
                pipe.config.validation_mode.value
                if pipe is not None and getattr(pipe, "config", None) is not None
                else extra_debug.get("validation_mode")
            ),
            "gemini_enabled": bool(getattr(pipe, "last_gemini_enabled", False)),
            "gemini_applied": int(getattr(pipe, "last_gemini_applied", 0)),
        },
    )
    result.stages = diagnostics.to_dict()

    result.preservation = stage_preservation_bundle(
        raw_notes=raw_notes,
        validated_notes=validated_notes,
        structured_events=events,
        quantized_events=quantized_events,
        tempo_map=structure.tempo_map if structure is not None else None,
        fallback_bpm=predicted_tempo or 120.0,
    )
    trans_result = getattr(pipe, "last_transcription_result", None)
    actual_backend = (
        getattr(trans_result, "actual_backend", None)
        or extra_debug.get("backend")
        or trans_payload.get("actual_backend")
        or (debug.source_backend if debug is not None else None)
    )
    requested_backend = (
        getattr(trans_result, "requested_backend", None)
        or trans_payload.get("requested_backend")
        or actual_backend
    )
    result.pipeline = {
        "raw_note_count": len(raw_notes) if raw_notes is not None else None,
        "cleaned_note_count": len(cleaned_notes) if cleaned_notes is not None else None,
        "post_piano_note_count": (
            len(post_piano_notes) if post_piano_notes is not None else None
        ),
        "structured_note_count": len(events),
        "quantized_note_count": len(quantized_events),
        "validated_note_count": (
            len(validated_notes) if validated_notes is not None else None
        ),
        "notation_plan_success": plan is not None and not bool(
            getattr(writer, "last_fallback_used", False)
        ),
        "fallback_used": bool(
            getattr(writer, "last_fallback_used", False)
            or getattr(trans_result, "used_fallback", False)
            or trans_payload.get("fallback_reason")
        ),
        "fallback_reason": (
            getattr(writer, "last_fallback_error", None)
            or getattr(trans_result, "fallback_reason", None)
            or trans_payload.get("fallback_reason")
        ),
        "notation_path": extra_debug.get("notation_path"),
        "cleaner_suppressions": len(
            [
                d
                for d in (getattr(pipe, "last_clean_decisions", None) or [])
                if getattr(getattr(d, "action", None), "value", d) == "suppress"
                or getattr(d, "action", None) == "suppress"
            ]
        ),
        "musicxml_success": musicxml_ok and bool(xml),
        "source_backend": actual_backend,
        "requested_backend": requested_backend,
        "actual_backend": actual_backend,
        "validation_mode": (
            pipe.config.validation_mode.value
            if pipe is not None and getattr(pipe, "config", None) is not None
            else extra_debug.get("validation_mode")
        ),
        "gemini_enabled": bool(getattr(pipe, "last_gemini_enabled", False)),
        "gemini_applied": int(getattr(pipe, "last_gemini_applied", 0)),
        "quantized_events_changed": extra_debug.get("quantized_events_changed"),
        "raw_event_preservation_rate": (
            (result.preservation.get("raw_vs_validated") or {}).get(
                "raw_event_preservation_rate"
            )
            if result.preservation
            else None
        ),
        "transcription_fallback_reason": trans_payload.get("fallback_reason")
        or getattr(trans_result, "fallback_reason", None),
        "settings": dict(getattr(trans_result, "settings", None) or trans_payload.get("settings") or {}),
        "timings": dict(getattr(trans_result, "timings", None) or trans_payload.get("timings") or {}),
    }

    alias = {
        "transcription": "raw_vs_reference_F1",
        "post_cleaner": "validated_vs_reference_F1",
        "structured": "structured_vs_reference_F1",
        "quantized": "quantized_vs_reference_F1",
    }
    for stage in diagnostics.stages:
        key = alias.get(stage.name)
        if not key:
            continue
        f1 = (stage.metrics or {}).get("onset_pitch_f1")
        if isinstance(f1, (int, float)):
            result.pipeline[key] = float(f1)

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
        "pipeline_validated_midi": str(validated_midi) if validated_midi.exists() else None,
        "pipeline_score_midi": str(score_midi) if score_midi.exists() else None,
        "pipeline_debug_json": str(debug_json) if debug_json.exists() else None,
        "results_dir": str(out),
    }
    result.hashes = {
        "input_audio_sha256": hash_file(audio_copy) if audio_copy.exists() else None,
        "reference_midi_sha256": hash_file(ref_copy) if ref_copy.exists() else None,
        "raw_midi_sha256": hash_file(raw_midi) if raw_midi.exists() else None,
        "validated_midi_sha256": hash_file(validated_midi) if validated_midi.exists() else None,
        "output_musicxml_sha256": (
            sha256_hex((out / "output.musicxml").read_bytes())
            if (out / "output.musicxml").exists()
            else None
        ),
    }
    result.execution.update(
        {
            "actual_mode": canonical_mode,
            "actual_pipeline_mode": result.execution.get("actual_pipeline_mode"),
            "actual_backend": actual_backend,
            "requested_backend": requested_backend,
            "independent_instance": pipeline is None,
        }
    )
    result.status = "ran"
    _write_case_files(out, result, diagnostics_text=diagnostics.conclusion)
    return result


def _restore_pipeline_mode(previous: str | None, requested: str | None) -> None:
    if not requested:
        return
    if previous is None:
        os.environ.pop("NEXTGEN_PIPELINE_MODE", None)
    else:
        os.environ["NEXTGEN_PIPELINE_MODE"] = previous


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
    if result.preservation:
        from evaluation.stage_diff import f1_from_case_result, format_stage_diff

        (out / "stage_diff.txt").write_text(
            format_stage_diff(
                result.preservation, f1_by_stage=f1_from_case_result(result)
            ),
            encoding="utf-8",
        )
        (out / "preservation.json").write_text(
            json.dumps(result.preservation, indent=2, default=str) + "\n",
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
        f"- raw_vs_reference_F1: {_fmt(pipe.get('raw_vs_reference_F1'))}",
        f"- validated_vs_reference_F1: {_fmt(pipe.get('validated_vs_reference_F1'))}",
        f"- structured_vs_reference_F1: {_fmt(pipe.get('structured_vs_reference_F1'))}",
        f"- quantized_vs_reference_F1: {_fmt(pipe.get('quantized_vs_reference_F1'))}",
        "",
        "## Raw preservation",
        "",
    ]
    preservation = result.preservation or {}
    rv = preservation.get("raw_vs_validated") or {}
    qn = preservation.get("quantization") or {}
    lines += [
        f"- raw / validated / structured / quantized: "
        f"{preservation.get('raw_note_count')} / "
        f"{preservation.get('validated_note_count')} / "
        f"{preservation.get('structured_note_count')} / "
        f"{preservation.get('quantized_note_count')}",
        f"- deleted_from_raw (validated): {rv.get('deleted_from_raw', '—')}",
        f"- added_vs_raw (validated): {rv.get('added_vs_raw', '—')}",
        f"- pitch/onset/duration changed vs raw: "
        f"{rv.get('pitch_changed_vs_raw', '—')} / "
        f"{rv.get('onset_changed_vs_raw', '—')} / "
        f"{rv.get('duration_changed_vs_raw', '—')}",
        f"- raw_event_preservation_rate (validated): "
        f"{_fmt(rv.get('raw_event_preservation_rate'))}",
        f"- quantized moved / unchanged: "
        f"{qn.get('events_moved', '—')} / {qn.get('events_unchanged', '—')}",
        f"- mean onset shift: {_fmt(qn.get('average_onset_shift_ms'), ' ms')}",
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
