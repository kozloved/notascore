"""Objective notation-complexity diagnostics. Not a musical-quality score."""

from __future__ import annotations

from typing import Any, Iterable

from mir.models import PlannedNote, PlannedRest
from mir.score_interpretation import complexity_warnings, source_identity


def _identity_key(note) -> tuple[Any, ...]:
    ident = source_identity(note)
    return (
        ident["note_id"],
        ident["pitch"],
        ident["velocity"],
        ident["start_sec"],
        ident["end_sec"],
    )


def source_identity_preserved(source_notes: Iterable | None, quantized: Iterable | None) -> bool:
    """Seconds/pitch/id stay on the source objects; quantized rows keep pitch/id/velocity."""
    source_notes = list(source_notes or [])
    if not source_notes:
        return True
    before = [_identity_key(n) for n in source_notes]
    after = [_identity_key(n) for n in source_notes]
    if before != after:
        return False
    src = {
        ident[0]: ident
        for ident in before
        if ident[0]
    }
    for ev in quantized or []:
        nid = getattr(ev, "note_id", None)
        if not nid or nid not in src:
            continue
        if int(ev.pitch) != src[nid][1]:
            return False
        if int(getattr(ev, "velocity", 0) or 0) != src[nid][2]:
            return False
    return True


def metrics_from_plan(
    plan,
    *,
    source_notes=None,
    quantized=None,
    tempo_marks: int = 0,
) -> dict[str, Any]:
    empty = {
        "measures": 0,
        "printed_notes": 0,
        "printed_chords": 0,
        "printed_rests": 0,
        "hidden_rests": 0,
        "ties": 0,
        "tuplets": 0,
        "voices_max_per_staff": 0,
        "notes_32nd_or_shorter": 0,
        "tempo_marks": int(tempo_marks),
        "bar_overflows": 0,
        "overlapping_printed_rests": 0,
        "source_note_count": len(list(source_notes or [])),
        "source_identity_preserved": source_identity_preserved(source_notes, quantized),
        "rests_per_voice_max": 0.0,
        "fragment_ties": 0,
        "tuplet_ratio": 0.0,
        "short_ratio": 0.0,
        "has_fast_pattern": False,
    }
    if plan is None or not getattr(plan, "measures", None):
        empty["tempo_marks"] = int(tempo_marks or getattr(plan, "extra", {}).get("tempo_marks", 0) if plan else 0)
        return empty

    printed_notes = 0
    printed_chords = 0
    printed_rests = 0
    hidden_rests = 0
    ties = 0
    tuplets = 0
    notes_32nd = 0
    voices_max = 0
    bar_overflows = 0
    overlapping_printed_rests = 0
    rests_per_voice = []
    fragment_ties = 0
    printed_total = 0
    even_16 = 0
    prev_onset = None
    for measure in plan.measures:
        measure_len = float(measure.duration_beats)
        for staff in measure.staves:
            voices_max = max(voices_max, len(staff.voices))
            for voice in staff.voices:
                filled = 0.0
                rest_spans: list[tuple[float, float]] = []
                voice_rests = 0
                for element in voice.elements:
                    if isinstance(element, PlannedNote):
                        filled += float(element.duration_q)
                        printed_total += 1
                        if len(element.pitches) > 1:
                            printed_chords += 1
                        else:
                            printed_notes += 1
                        if element.tie:
                            ties += 1
                            if float(element.duration_q) <= 0.125 + 1e-9:
                                fragment_ties += 1
                        if element.tuplet:
                            tuplets += 1
                        if float(element.duration_q) <= 0.125 + 1e-9:
                            notes_32nd += 1
                        onset = float(element.start_q)
                        if prev_onset is not None and abs(onset - prev_onset - 0.25) < 0.04:
                            even_16 += 1
                        prev_onset = onset
                    elif isinstance(element, PlannedRest):
                        filled += float(element.duration_q)
                        if element.hidden:
                            hidden_rests += 1
                        else:
                            printed_rests += 1
                            voice_rests += 1
                            rest_spans.append(
                                (
                                    float(element.start_q),
                                    float(element.start_q) + float(element.duration_q),
                                )
                            )
                rests_per_voice.append(voice_rests)
                if filled > measure_len + 1e-6:
                    bar_overflows += 1
                for i, (a0, a1) in enumerate(rest_spans):
                    for b0, b1 in rest_spans[i + 1 :]:
                        if a0 < b1 and b0 < a1:
                            overlapping_printed_rests += 1
    short_ratio = notes_32nd / max(1, printed_total)
    tuplet_ratio = tuplets / max(1, printed_total)
    return {
        "measures": len(plan.measures),
        "printed_notes": printed_notes,
        "printed_chords": printed_chords,
        "printed_rests": printed_rests,
        "hidden_rests": hidden_rests,
        "ties": ties,
        "tuplets": tuplets,
        "voices_max_per_staff": voices_max,
        "notes_32nd_or_shorter": notes_32nd,
        "tempo_marks": int(tempo_marks or (plan.extra or {}).get("tempo_marks") or 0),
        "bar_overflows": bar_overflows,
        "overlapping_printed_rests": overlapping_printed_rests,
        "source_note_count": len(list(source_notes or [])),
        "source_identity_preserved": source_identity_preserved(source_notes, quantized),
        "rests_per_voice_max": float(max(rests_per_voice) if rests_per_voice else 0),
        "fragment_ties": fragment_ties,
        "tuplet_ratio": round(tuplet_ratio, 4),
        "short_ratio": round(short_ratio, 4),
        "has_fast_pattern": even_16 >= 3,
    }


def warnings_from_metrics(metrics: dict[str, Any]) -> list[str]:
    return complexity_warnings(
        voices_max=int(metrics.get("voices_max_per_staff") or 0),
        rests_per_voice=float(metrics.get("rests_per_voice_max") or 0.0),
        fragment_ties=int(metrics.get("fragment_ties") or 0),
        short_ratio=float(metrics.get("short_ratio") or 0.0),
        tuplet_ratio=float(metrics.get("tuplet_ratio") or 0.0),
        has_fast_pattern=bool(metrics.get("has_fast_pattern")),
    )
