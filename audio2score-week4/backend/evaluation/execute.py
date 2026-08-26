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
    metrics: dict[str, Any] = field(default_factory=dict)
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
            "metrics": self.metrics,
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


def _resolve_expected_meter(case: CaseSpec, ref: NormalizedReference | None) -> str | None:
    if case.expected_meter:
        return case.expected_meter
    return ref.time_signature if ref is not None else None


def _resolve_expected_tempo(
    case: CaseSpec, ref: NormalizedReference | None
) -> float | None:
    if case.expected_tempo_bpm is not None:
        return float(case.expected_tempo_bpm)
    return ref.tempo_bpm if ref is not None else None


def _stage_metrics(stages: dict[str, Any], name: str) -> dict[str, Any]:
    for stage in (stages or {}).get("stages") or []:
        if stage.get("name") == name:
            return dict(stage.get("metrics") or {})
    return {}


def _namespace_from_match(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "onset_precision": match.get("onset_precision"),
        "onset_recall": match.get("onset_recall"),
        "onset_f1": match.get("onset_f1"),
        "onset_pitch_f1": match.get("onset_pitch_f1"),
        "onset_pitch_offset_f1": match.get("onset_pitch_offset_f1"),
        "false_positives": match.get("false_positives"),
        "false_negatives": match.get("false_negatives"),
        "reference_count": match.get("reference_count"),
        "predicted_count": match.get("predicted_count"),
        "matched": match.get("matched"),
        "mean_onset_error_ms": match.get("mean_onset_error_ms"),
        "median_onset_error_ms": match.get("median_onset_error_ms"),
        "mean_duration_error_ms": match.get("mean_duration_error_ms"),
    }


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
        result.skip_reason = "missing reference MIDI (need reference_raw.mid, reference_score.mid, or reference.mid)"
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

    resolution = case.reference_resolution
    raw_path = case.reference_raw_midi
    score_path = case.reference_score_midi

    raw_ref: NormalizedReference | None = None
    score_ref: NormalizedReference | None = None

    # Normalize references in memory only — never mutate source files
    if raw_path is not None and raw_path.is_file():
        before = raw_path.read_bytes()
        raw_ref = normalize_reference_midi(raw_path)
        after = raw_path.read_bytes()
        if before != after:
            raise RuntimeError(f"Reference MIDI was mutated: {raw_path}")
        shutil.copy2(raw_path, out / "reference_raw.mid")

    if score_path is not None and score_path.is_file():
        before = score_path.read_bytes()
        score_ref = normalize_reference_midi(score_path)
        after = score_path.read_bytes()
        if before != after:
            raise RuntimeError(f"Reference MIDI was mutated: {score_path}")
        # Avoid overwriting when raw and score are the same legacy file
        dest = out / "reference_score.mid"
        if not (raw_path and score_path.resolve() == raw_path.resolve() and (out / "reference_raw.mid").exists()):
            shutil.copy2(score_path, dest)
        elif raw_path and score_path.resolve() == raw_path.resolve():
            shutil.copy2(score_path, dest)

    # Legacy alias for inspection
    if raw_path is not None:
        shutil.copy2(raw_path, out / "reference.mid")
    elif score_path is not None:
        shutil.copy2(score_path, out / "reference.mid")

    result.reference = {
        "resolution": resolution.to_dict(),
        "raw": raw_ref.to_dict() if raw_ref is not None else None,
        "score": score_ref.to_dict() if score_ref is not None else None,
        "raw_note_count": len(raw_ref.notes) if raw_ref is not None else None,
        "score_note_count": len(score_ref.notes) if score_ref is not None else None,
        "same_file": resolution.same_file,
        "raw_legacy_fallback": resolution.raw_legacy_fallback,
        "score_legacy_fallback": resolution.score_legacy_fallback,
        # Backward-compat flat fields (primary = raw when present)
        **(
            raw_ref.to_dict()
            if raw_ref is not None
            else (score_ref.to_dict() if score_ref is not None else {})
        ),
    }

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

    primary_ref = raw_ref or score_ref
    expected_meter = _resolve_expected_meter(case, primary_ref)
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
        reference_bpm=_resolve_expected_tempo(case, primary_ref),
    )

    events = list(structure.events) if structure is not None else []
    hand_ref_notes = (raw_ref.notes if raw_ref is not None else []) or (
        score_ref.notes if score_ref is not None else []
    )
    result.hands = hand_metrics(events, hand_ref_notes)

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

    # Never compare raw stages to the score MIDI. Never compare score stages
    # to the raw MIDI unless they resolve to the same legacy file via fallback.
    raw_notes_for_stages = raw_ref.notes if raw_ref is not None else None
    score_notes_for_stages = score_ref.notes if score_ref is not None else None

    diagnostics = capture_transcription_stages(
        out_dir=out,
        reference_notes=raw_notes_for_stages,
        reference_score_notes=score_notes_for_stages,
        has_raw_reference=raw_ref is not None,
        has_score_reference=score_ref is not None,
        raw_notes=pipe.last_raw_notes,
        cleaned_notes=pipe.last_cleaned_notes,
        post_piano_notes=pipe.last_post_piano_notes,
        structured_events=events,
        tempo_map=structure.tempo_map if structure is not None else None,
        tempo_bpm=predicted_tempo
        or (primary_ref.tempo_bpm if primary_ref else None)
        or 120.0,
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
            "reference_raw_source": resolution.raw_source,
            "reference_score_source": resolution.score_source,
            "raw_legacy_fallback": resolution.raw_legacy_fallback,
            "score_legacy_fallback": resolution.score_legacy_fallback,
            "same_reference_file": resolution.same_file,
        },
    )
    result.stages = diagnostics.to_dict()

    transcription_m = _stage_metrics(result.stages, "transcription")
    cleaner_m = _stage_metrics(result.stages, "post_cleaner")
    score_block = dict(diagnostics.score_evaluation or {})

    raw_namespace = (
        _namespace_from_match(transcription_m)
        if transcription_m
        else {
            "status": "unavailable",
            "reason": "no raw performance reference",
        }
    )
    cleaner_namespace = (
        _namespace_from_match(cleaner_m)
        if cleaner_m
        else {
            "status": "unavailable",
            "reason": "no raw performance reference or cleaner stage missing",
        }
    )

    result.metrics = {
        "raw": raw_namespace,
        "cleaner": cleaner_namespace,
        "score": score_block,
        "cleaner_delta": {
            "onset_pitch_f1": (
                (cleaner_m.get("onset_pitch_f1") - transcription_m.get("onset_pitch_f1"))
                if isinstance(cleaner_m.get("onset_pitch_f1"), (int, float))
                and isinstance(transcription_m.get("onset_pitch_f1"), (int, float))
                else None
            ),
            "onset_f1": (
                (cleaner_m.get("onset_f1") - transcription_m.get("onset_f1"))
                if isinstance(cleaner_m.get("onset_f1"), (int, float))
                and isinstance(transcription_m.get("onset_f1"), (int, float))
                else None
            ),
        },
    }

    # Headline notes: raw transcription when raw ref exists; else score metrics.
    if raw_ref is not None and transcription_m:
        result.notes = transcription_m
    elif raw_ref is not None:
        result.notes = compare_stage_notes(final_notes, raw_ref.notes)
    elif score_ref is not None and score_block.get("status") == "evaluated":
        result.notes = {
            "onset_pitch_f1": score_block.get("onset_pitch_f1"),
            "onset_f1": score_block.get("onset_f1"),
            "onset_pitch_offset_f1": score_block.get("onset_pitch_offset_f1"),
            "reference_count": score_block.get("reference_count"),
            "predicted_count": score_block.get("predicted_count"),
            "matched": score_block.get("matched"),
            "false_positives": score_block.get("false_positives"),
            "false_negatives": score_block.get("false_negatives"),
        }
    else:
        result.notes = {}

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

    result.artifacts = {
        "case_dir": str(case.case_dir),
        "audio": str(case.audio_path),
        "reference_midi": str(case.reference_midi) if case.reference_midi else None,
        "reference_raw_midi": str(raw_path) if raw_path else None,
        "reference_score_midi": str(score_path) if score_path else None,
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
        "reference": result.reference,
        "metrics": result.metrics,
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
    metrics = result.metrics or {}
    raw_m = metrics.get("raw") or {}
    cleaner_m = metrics.get("cleaner") or {}
    score_m = metrics.get("score") or {}
    meter = result.meter or {}
    tempo = result.tempo or {}
    hands = result.hands or {}
    pipe = result.pipeline or {}
    ref = result.reference or {}
    resolution = ref.get("resolution") or {}
    lines = [
        f"# Case `{result.case_id}`",
        "",
        f"- split: `{result.split}`",
        f"- status: **{result.status}**",
        f"- title: {result.title or result.case_id}",
        "",
        "## References",
        "",
        f"- raw source: `{resolution.get('raw_source') or '—'}`"
        f"{' (legacy fallback)' if resolution.get('raw_legacy_fallback') else ''}",
        f"- score source: `{resolution.get('score_source') or '—'}`"
        f"{' (legacy fallback)' if resolution.get('score_legacy_fallback') else ''}",
        f"- same file: {resolution.get('same_file')}",
        f"- raw note count: {ref.get('raw_note_count', '—')}",
        f"- score note count: {ref.get('score_note_count', '—')}",
        "",
        "## Raw metrics (vs reference_raw)",
        "",
        f"- onset F1: {_fmt(raw_m.get('onset_f1') or notes.get('onset_f1'))}",
        f"- onset+pitch F1: {_fmt(raw_m.get('onset_pitch_f1') or notes.get('onset_pitch_f1'))}",
        f"- onset+pitch+offset F1: {_fmt(raw_m.get('onset_pitch_offset_f1') or notes.get('onset_pitch_offset_f1'))}",
        f"- FP / FN: {raw_m.get('false_positives', notes.get('false_positives', '—'))} / "
        f"{raw_m.get('false_negatives', notes.get('false_negatives', '—'))}",
        "",
        "## Cleaner metrics (vs reference_raw)",
        "",
        f"- onset+pitch F1: {_fmt(cleaner_m.get('onset_pitch_f1'))}",
        f"- onset+pitch+offset F1: {_fmt(cleaner_m.get('onset_pitch_offset_f1'))}",
        f"- delta onset+pitch F1: {_fmt((metrics.get('cleaner_delta') or {}).get('onset_pitch_f1'))}",
        "",
        "## Score metrics (vs reference_score)",
        "",
    ]
    if score_m.get("status") == "evaluated":
        lines += [
            f"- quantized note F1: {_fmt(score_m.get('quantized_note_f1'))}",
            f"- rhythm accuracy: {_fmt(score_m.get('rhythm_accuracy'))}",
            f"- duration accuracy: {_fmt(score_m.get('duration_accuracy'))}",
            f"- measure alignment: {score_m.get('measure_alignment')}",
        ]
    else:
        lines.append(
            f"- score_evaluation: **unavailable**"
            f" — {score_m.get('reason') or 'no score comparison'}"
        )
    lines += [
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
