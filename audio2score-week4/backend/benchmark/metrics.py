"""Evaluation metrics for transcription, cleaning, hands, voices, and notation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from mir.types import NoteEvent


@dataclass
class NoteMetrics:
    precision: float
    recall: float
    f1: float
    onset_errors_ms: list[float]
    pitch_matches: int
    pitch_total: int


def match_notes(
    predicted: list[NoteEvent],
    reference: list[NoteEvent],
    onset_tolerance_sec: float = 0.05,
    pitch_tolerance: int = 0,
) -> NoteMetrics:
    """Match notes by pitch + onset within tolerance."""
    matched_pred = set()
    matched_ref = set()
    onset_errors: list[float] = []
    pitch_matches = 0

    for ri, ref in enumerate(reference):
        best_pi = None
        best_dt = float("inf")
        for pi, pred in enumerate(predicted):
            if pi in matched_pred:
                continue
            if abs(pred.pitch - ref.pitch) > pitch_tolerance:
                continue
            dt = abs(pred.start_time - ref.start_time)
            if dt <= onset_tolerance_sec and dt < best_dt:
                best_dt = dt
                best_pi = pi
        if best_pi is not None:
            matched_pred.add(best_pi)
            matched_ref.add(ri)
            onset_errors.append(best_dt * 1000)
            pitch_matches += 1

    tp = len(matched_pred)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(reference) if reference else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return NoteMetrics(
        precision=precision,
        recall=recall,
        f1=f1,
        onset_errors_ms=onset_errors,
        pitch_matches=pitch_matches,
        pitch_total=len(reference),
    )


def onset_f_measure(
    predicted_times: list[float],
    reference_times: list[float],
    tolerance_sec: float = 0.05,
) -> tuple[float, float, float]:
    matched = 0
    used_ref = set()
    for pt in predicted_times:
        for ri, rt in enumerate(reference_times):
            if ri in used_ref:
                continue
            if abs(pt - rt) <= tolerance_sec:
                matched += 1
                used_ref.add(ri)
                break
    p = matched / len(predicted_times) if predicted_times else 0.0
    r = matched / len(reference_times) if reference_times else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


def pitch_accuracy(metrics: NoteMetrics) -> float:
    if metrics.pitch_total <= 0:
        return 0.0
    return metrics.pitch_matches / metrics.pitch_total


def mean_onset_error_ms(metrics: NoteMetrics) -> float | None:
    if not metrics.onset_errors_ms:
        return None
    return sum(metrics.onset_errors_ms) / len(metrics.onset_errors_ms)


@dataclass
class CleaningMetrics:
    notes_before: int = 0
    notes_after: int = 0
    notes_removed: int = 0
    false_removals: int = 0
    duplicates_removed: int = 0
    octave_removals: int = 0
    reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class HandMetrics:
    accuracy: float | None = None
    total: int = 0
    correct: int = 0
    ambiguous: int = 0
    unknown: int = 0
    confusion: dict[str, int] = field(default_factory=dict)


@dataclass
class VoiceMetrics:
    predicted_count_rh: int | None = None
    expected_count_rh: int | None = None
    continuity_ok: bool | None = None
    accidental_merges: int = 0


@dataclass
class MeterMetrics:
    selected: str | None = None
    expected: str | None = None
    correct: bool | None = None


@dataclass
class NotationMetrics:
    plan_success: bool = False
    fallback_used: bool = False
    fallback_reason: str | None = None
    measure_count: int = 0
    measure_valid: bool = False
    voice_sum_ok: bool = False
    tie_count: int = 0
    rest_count: int = 0
    tuplet_count: int = 0
    complexity: float = 0.0
    xml_valid: bool = False
    xml_errors: list[str] = field(default_factory=list)


def notes_from_reference_dicts(rows: list[dict[str, Any]]) -> list[NoteEvent]:
    return [
        NoteEvent(
            pitch=int(r["pitch"]),
            start_time=float(r["start_time"]),
            end_time=float(r["end_time"]),
            velocity=int(r.get("velocity", 64)),
            confidence=1.0,
        )
        for r in rows
    ]


def cleaning_metrics(
    *,
    notes_before: int,
    notes_after: int,
    decisions: list[Any],
    reference_notes: list[dict[str, Any]],
    onset_tolerance_sec: float = 0.05,
) -> CleaningMetrics:
    reasons: dict[str, int] = {}
    false_removals = 0
    duplicates = 0
    octaves = 0
    for decision in decisions:
        action = getattr(decision, "action", None)
        action_value = action.value if hasattr(action, "value") else str(action or "")
        reason = getattr(decision, "reason", "") or ""
        reasons[reason] = reasons.get(reason, 0) + 1
        if "duplicate" in reason:
            duplicates += 1
        if "octave_ghost" in reason:
            octaves += 1
        if action_value != "suppress":
            continue
        pitch = int(getattr(decision, "pitch", -1))
        start = float(getattr(decision, "start_time", -1.0))
        for ref in reference_notes:
            if not ref.get("keep", True):
                continue
            if int(ref["pitch"]) != pitch:
                continue
            if abs(float(ref["start_time"]) - start) <= onset_tolerance_sec:
                false_removals += 1
                break
    return CleaningMetrics(
        notes_before=notes_before,
        notes_after=notes_after,
        notes_removed=max(0, notes_before - notes_after),
        false_removals=false_removals,
        duplicates_removed=duplicates,
        octave_removals=octaves,
        reasons=reasons,
    )


def hand_metrics(
    predicted: list[Any],
    reference_notes: list[dict[str, Any]],
    beat_tolerance: float = 0.12,
) -> HandMetrics:
    confusion: dict[str, int] = {}
    correct = 0
    total = 0
    ambiguous = 0
    unknown = 0
    used: set[int] = set()
    for ref in reference_notes:
        expected = str(ref.get("hand") or "unknown")
        best_i = None
        best_dt = float("inf")
        for i, ev in enumerate(predicted):
            if i in used:
                continue
            if int(getattr(ev, "pitch", -1)) != int(ref["pitch"]):
                continue
            start = float(getattr(ev, "start_beat", 0.0))
            dt = abs(start - float(ref.get("start_beat", 0.0)))
            if dt <= beat_tolerance and dt < best_dt:
                best_dt = dt
                best_i = i
        if best_i is None:
            continue
        used.add(best_i)
        got = str(getattr(predicted[best_i], "hand").value)
        total += 1
        key = f"{expected}->{got}"
        confusion[key] = confusion.get(key, 0) + 1
        if got == "ambiguous":
            ambiguous += 1
        if got == "unknown":
            unknown += 1
        if got == expected:
            correct += 1
    accuracy = (correct / total) if total else None
    return HandMetrics(
        accuracy=accuracy,
        total=total,
        correct=correct,
        ambiguous=ambiguous,
        unknown=unknown,
        confusion=confusion,
    )


def _simple_duration(duration_q: float) -> bool:
    simple = {4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 3.0, 1.5, 0.75, 0.375}
    return any(abs(duration_q - d) < 1e-6 for d in simple)


def notation_from_plan(plan) -> dict[str, Any]:
    tie_count = 0
    rest_count = 0
    tuplet_count = 0
    note_count = 0
    complex_count = 0
    voice_sum_ok = True
    for measure in getattr(plan, "measures", []) or []:
        for staff in measure.staves:
            for voice in staff.voices:
                total = sum(el.duration_q for el in voice.elements)
                if abs(total - measure.duration_beats) > 0.08:
                    voice_sum_ok = False
                for el in voice.elements:
                    name = type(el).__name__
                    if name == "PlannedRest":
                        rest_count += 1
                        continue
                    note_count += 1
                    if getattr(el, "tie", None):
                        tie_count += 1
                    dur = float(getattr(el, "duration_q", 0.0))
                    if abs(dur - (1.0 / 3.0)) < 0.04 or abs(dur - (2.0 / 3.0)) < 0.04:
                        tuplet_count += 1
                    if not _simple_duration(dur):
                        complex_count += 1
    complexity = (complex_count / note_count) if note_count else 0.0
    return {
        "measure_count": len(getattr(plan, "measures", []) or []),
        "voice_sum_ok": voice_sum_ok,
        "tie_count": tie_count,
        "rest_count": rest_count,
        "tuplet_count": tuplet_count,
        "complexity": complexity,
    }


def xml_structure_valid(xml_text: str) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not xml_text or "<" not in xml_text:
        return False, ["empty_xml"]
    try:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_text)
    except Exception as exc:
        return False, [f"parse_error:{exc}"]
    tag = root.tag.split("}")[-1].lower()
    if "score-partwise" not in tag and "score-timewise" not in tag:
        errors.append("missing_score_root")
    text = xml_text.lower()
    if "<measure" not in text:
        errors.append("missing_measure")
    if "<note" not in text:
        errors.append("missing_note")
    if "<time" not in text and "<beats>" not in text:
        errors.append("missing_time_signature")
    return (len(errors) == 0), errors


def accidental_voice_merges(plan, reference_notes: list[dict[str, Any]]) -> int:
    """Count planned chords that mix two different reference voices."""
    ref_voice: dict[tuple[int, float], int] = {}
    for ref in reference_notes:
        key = (int(ref["pitch"]), round(float(ref.get("start_beat", 0.0)), 3))
        ref_voice[key] = int(ref.get("voice", 0))
    merges = 0
    for measure in getattr(plan, "measures", []) or []:
        for staff in measure.staves:
            for voice in staff.voices:
                for el in voice.elements:
                    pitches = getattr(el, "pitches", None)
                    if not pitches or len(pitches) < 2:
                        continue
                    start = round(float(measure.start_beat + el.start_q), 3)
                    voices = {
                        ref_voice.get((int(p), start))
                        for p in pitches
                        if (int(p), start) in ref_voice
                    }
                    voices.discard(None)
                    if len(voices) > 1:
                        merges += 1
    return merges


def to_plain(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj
