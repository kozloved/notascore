"""Run one corpus case through MIDI / Fast / Quality and collect metrics."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchmark.fixtures.audio import render_notes_wav
from benchmark.metrics import (
    CleaningMetrics,
    HandMetrics,
    MeterMetrics,
    NoteMetrics,
    NotationMetrics,
    VoiceMetrics,
    accidental_voice_merges,
    cleaning_metrics,
    hand_metrics,
    match_notes,
    mean_onset_error_ms,
    notation_from_plan,
    notes_from_reference_dicts,
    pitch_accuracy,
    xml_structure_valid,
)
from benchmark.note_extract import notes_from_midi
from benchmark.schema import LoadedCase
from mir.hand_separator import HandSeparator
from mir.meter import MeterEstimator
from mir.midi_cleaner import MIDICleaner
from mir.midi_ingest import ingest_midi
from mir.pipeline import UnderstandingPipeline
from mir.types import Hand, MusicalEvent, ScoreMeta
from mir.voice_separator import VoiceSeparator
from notation_engine.plan import NotationPlanner
from notation_engine.writer import NotationWriter


MODE_LABELS = {
    "midi": "MIDI ingest",
    "solo": "Solo (Basic Pitch)",
    "fast": "Solo (Basic Pitch)",
    "polyphonic": "Polyphonic (MT3)",
    "quality": "Polyphonic (MT3)",
}


@dataclass
class CaseEval:
    case_id: str
    category: str
    mode: str
    passed: bool
    flags: list[str] = field(default_factory=list)
    transcription: dict[str, Any] = field(default_factory=dict)
    cleaning: dict[str, Any] = field(default_factory=dict)
    hands: dict[str, Any] = field(default_factory=dict)
    voices: dict[str, Any] = field(default_factory=dict)
    meter: dict[str, Any] = field(default_factory=dict)
    notation: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "category": self.category,
            "mode": self.mode,
            "mode_label": MODE_LABELS.get(self.mode, self.mode),
            "passed": self.passed,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "flags": self.flags,
            "transcription": self.transcription,
            "cleaning": self.cleaning,
            "hands": self.hands,
            "voices": self.voices,
            "meter": self.meter,
            "notation": self.notation,
            "counts": self.counts,
        }


def _events_from_notes(case: LoadedCase, *, use_reference_hands: bool) -> list[MusicalEvent]:
    events: list[MusicalEvent] = []
    for row in case.reference_notes:
        hand = Hand.UNKNOWN
        if use_reference_hands:
            raw = str(row.get("hand") or "unknown")
            try:
                hand = Hand(raw)
            except ValueError:
                hand = Hand.UNKNOWN
        events.append(
            MusicalEvent(
                pitch=int(row["pitch"]),
                start_beat=float(row["start_beat"]),
                duration_beats=float(row["duration_beats"]),
                velocity=int(row.get("velocity") or 80),
                voice=0,
                hand=hand,
                role=row.get("role"),
            )
        )
    return events


def _meter_ok(selected: str | None, expected: str | None) -> bool | None:
    if not expected:
        return None
    if not selected:
        return False
    if expected == "4/4":
        return selected in ("4/4", "2/4")
    return selected == expected


def evaluate_structure(case: LoadedCase) -> tuple[HandMetrics, VoiceMetrics, MeterMetrics, dict]:
    unlabeled = _events_from_notes(case, use_reference_hands=False)
    separated = HandSeparator().separate(list(unlabeled))
    hands = hand_metrics(separated, case.reference_notes)

    labeled = _events_from_notes(case, use_reference_hands=True)
    voiced = VoiceSeparator().separate(list(labeled))
    rh = [e for e in voiced if e.hand in (Hand.RIGHT, Hand.UNKNOWN, Hand.AMBIGUOUS)]
    predicted_rh = len({e.voice for e in rh}) if rh else 0
    expected_rh = case.expected_voice_count_rh
    continuity = None if expected_rh is None else predicted_rh == expected_rh
    meta = ScoreMeta(
        display_tempo_bpm=int(case.tempo_bpm),
        time_sig_hint=case.time_signature,
        key_hint=case.key,
    )
    plan, _ = NotationPlanner().build(voiced, meta=meta)
    merges = accidental_voice_merges(plan, case.reference_notes)
    voices = VoiceMetrics(
        predicted_count_rh=predicted_rh,
        expected_count_rh=expected_rh,
        continuity_ok=continuity,
        accidental_merges=merges,
    )
    selected = MeterEstimator().select(voiced).time_signature
    meter = MeterMetrics(
        selected=selected,
        expected=case.expected_meter,
        correct=_meter_ok(selected, case.expected_meter),
    )
    return hands, voices, meter, notation_from_plan(plan)


def _cleaning_for_midi(case: LoadedCase) -> CleaningMetrics:
    ingested = ingest_midi(case.input_midi)
    cleaned, decisions = MIDICleaner().clean_with_report(list(ingested.notes))
    return cleaning_metrics(
        notes_before=len(ingested.notes),
        notes_after=len(cleaned),
        decisions=decisions,
        reference_notes=case.reference_notes,
    )


def _pipeline_for_mode(mode: str) -> UnderstandingPipeline | None:
    from modes import POLYPHONIC, SOLO, is_polyphonic, parse_transcription_mode

    if mode == "midi":
        return UnderstandingPipeline(mode=SOLO)
    resolved = parse_transcription_mode(mode)
    if resolved == POLYPHONIC or is_polyphonic(resolved):
        from adapters.mt3_backend import MT3Backend, mt3_available

        if not mt3_available():
            return None
        return UnderstandingPipeline(backend_name=MT3Backend.name, mode=POLYPHONIC)
    return UnderstandingPipeline(mode=SOLO)


def evaluate_case(
    case: LoadedCase,
    *,
    mode: str,
    work_root: Path,
) -> CaseEval:
    flags: list[str] = []
    work = work_root / mode / case.case_id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    from modes import is_polyphonic

    if mode != "midi" and is_polyphonic(mode):
        from adapters.mt3_backend import mt3_available

        if not mt3_available():
            return CaseEval(
                case_id=case.case_id,
                category=case.category,
                mode=mode,
                passed=True,
                skipped=True,
                skip_reason="Polyphonic worker unavailable (MT3_ENDPOINT / MT3_TRANSCRIBE_COMMAND unset)",
            )

    pipeline = _pipeline_for_mode(mode)
    assert pipeline is not None

    xml = ""
    predicted_notes = []
    cleaning = CleaningMetrics()
    events_before = len(case.reference_notes)
    pipeline_error = None
    try:
        if mode == "midi":
            src = work / "input.mid"
            shutil.copy2(case.input_midi, src)
            xml = pipeline.transcribe(src, case.case_id)
            raw_midi = work / f"bp_{case.case_id}" / f"{case.case_id}.raw.mid"
            predicted_notes = notes_from_midi(
                raw_midi if raw_midi.exists() else case.input_midi
            )
            cleaning = _cleaning_for_midi(case)
            events_before = len(ingest_midi(case.input_midi).notes)
        else:
            wav = work / "input.wav"
            render_notes_wav(case.reference_notes, wav, sample_rate=22050)
            xml = pipeline.transcribe(wav, case.case_id)
            raw_midi = work / f"bp_{case.case_id}" / f"{case.case_id}.raw.mid"
            if raw_midi.exists():
                predicted_notes = notes_from_midi(raw_midi)
            debug = pipeline.last_debug
            events_before = debug.raw_note_count if debug else len(predicted_notes)
            removed = list(debug.removed_notes) if debug else []
            cleaning = CleaningMetrics(
                notes_before=events_before,
                notes_after=debug.cleaned_note_count if debug else len(predicted_notes),
                notes_removed=len(removed),
                false_removals=0,
                duplicates_removed=sum(
                    1 for r in removed if "duplicate" in str(r.get("reason", ""))
                ),
                octave_removals=sum(
                    1 for r in removed if "octave" in str(r.get("reason", ""))
                ),
            )
            for row in removed:
                pitch = int(row.get("pitch") or -1)
                for ref in case.reference_notes:
                    if not ref.get("keep", True):
                        continue
                    if int(ref["pitch"]) == pitch:
                        cleaning.false_removals += 1
                        break
    except Exception as exc:
        pipeline_error = f"{type(exc).__name__}: {exc}"
        flags.append("pipeline_error")

    reference_notes = notes_from_reference_dicts(case.reference_notes)
    note_m = match_notes(predicted_notes, reference_notes, onset_tolerance_sec=0.08)
    hands, voices, meter_est, _ = evaluate_structure(case)

    writer: NotationWriter = pipeline.notation
    plan = writer.last_plan
    fallback_used = bool(writer.last_fallback_used)
    fallback_reason = writer.last_fallback_error
    plan_success = plan is not None and not fallback_used
    xml_ok, xml_errors = xml_structure_valid(xml)
    plan_bits = notation_from_plan(plan) if plan is not None else {
        "measure_count": 0,
        "voice_sum_ok": False,
        "tie_count": 0,
        "rest_count": 0,
        "tuplet_count": 0,
        "complexity": 0.0,
    }
    # Prefer the written MIDI time signature / hint over the estimator for
    # production-path meter, when the planner actually ran.
    selected_meter = None
    if plan is not None:
        selected_meter = plan.time_signature
    elif pipeline.last_debug is not None:
        selected_meter = pipeline.last_debug.selected_meter
    meter = MeterMetrics(
        selected=selected_meter or meter_est.selected,
        expected=case.expected_meter,
        correct=_meter_ok(selected_meter or meter_est.selected, case.expected_meter),
    )

    events_after = None
    production_hands = {}
    if pipeline.last_structure is not None:
        events_after = len(pipeline.last_structure.events)
        production_hands = {
            "left": sum(1 for e in pipeline.last_structure.events if e.hand == Hand.LEFT),
            "right": sum(1 for e in pipeline.last_structure.events if e.hand == Hand.RIGHT),
            "unknown": sum(1 for e in pipeline.last_structure.events if e.hand == Hand.UNKNOWN),
            "ambiguous": sum(
                1 for e in pipeline.last_structure.events if e.hand == Hand.AMBIGUOUS
            ),
        }

    if pipeline_error:
        notation = NotationMetrics(
            plan_success=False,
            fallback_used=False,
            fallback_reason=pipeline_error,
            xml_valid=False,
            xml_errors=[pipeline_error],
        )
    else:
        notation = NotationMetrics(
            plan_success=plan_success,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            measure_count=int(plan_bits["measure_count"]),
            measure_valid=bool(plan_bits["voice_sum_ok"]) and xml_ok,
            voice_sum_ok=bool(plan_bits["voice_sum_ok"]),
            tie_count=int(plan_bits["tie_count"]),
            rest_count=int(plan_bits["rest_count"]),
            tuplet_count=int(plan_bits["tuplet_count"]),
            complexity=float(plan_bits["complexity"]),
            xml_valid=xml_ok,
            xml_errors=xml_errors,
        )

    if case.keep_all_octaves and cleaning.false_removals:
        flags.append("octave_false_removal")
    if case.notation_plan_required and not notation.plan_success:
        flags.append("notation_plan_fallback")
    if not notation.xml_valid:
        flags.append("invalid_musicxml")
    if xml and not notation.voice_sum_ok:
        flags.append("voice_sum_invalid")
    if mode not in ("fast", "solo"):
        if case.check_hands and hands.accuracy is not None and hands.accuracy < 0.85:
            flags.append("hand_accuracy_low")
        if voices.continuity_ok is False:
            flags.append("voice_merge_or_split")
        if voices.accidental_merges:
            flags.append("accidental_voice_merge")
    if case.meter_eval == "STRICT_METER" and meter.correct is False:
        flags.append("meter_mismatch")
    if case.keep_all_octaves:
        ref_pitches = {int(n["pitch"]) for n in case.reference_notes if n.get("keep", True)}
        cleaned_for_octaves = MIDICleaner().clean(
            ingest_midi(case.input_midi).notes
        )
        kept = {n.pitch for n in cleaned_for_octaves}
        if not ref_pitches <= kept:
            flags.append("octave_false_removal")
            cleaning.false_removals = max(
                cleaning.false_removals, len(ref_pitches - kept)
            )

    flags = list(dict.fromkeys(flags))
    passed = not flags
    eval_row = CaseEval(
        case_id=case.case_id,
        category=case.category,
        mode=mode,
        passed=passed,
        flags=flags,
        transcription={
            "precision": note_m.precision,
            "recall": note_m.recall,
            "f1": note_m.f1,
            "onset_error_ms": mean_onset_error_ms(note_m),
            "pitch_accuracy": pitch_accuracy(note_m),
        },
        cleaning=cleaning.__dict__,
        hands=hands.__dict__,
        voices=voices.__dict__,
        meter=meter.__dict__,
        notation=notation.__dict__,
        counts={
            "events_before_cleaning": events_before,
            "events_after_cleaning": cleaning.notes_after,
            "event_count_structure": events_after,
            "hand_assignments": (
                pipeline.last_debug.hand_assignments if pipeline.last_debug else production_hands
            ),
            "production_hands": production_hands,
            "voice_count": voices.predicted_count_rh,
            "measure_count": notation.measure_count,
            "meter_eval": case.meter_eval,
        },
    )
    (work / "eval.json").write_text(
        json.dumps(eval_row.to_dict(), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return eval_row
