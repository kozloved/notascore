"""Stage-to-stage raw-event preservation metrics.

Answers: how many original transcription events survived, and what changed.

Matching prefers ``note_id``. When ids are missing, greedy match by pitch
then closest onset. This module never mutates production notes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from mir.types import MusicalEvent, NoteEvent, TempoMap

# "Changed" vs RAW uses a tight tolerance: STRICT_SAFE should be bit-identical
# except for documented invalid-MIDI repairs.
ONSET_CHANGED_SEC = 0.0005
DURATION_CHANGED_SEC = 0.0005
# Quantization "moved" uses 1 ms so float noise on the beat grid is ignored.
QUANTIZE_MOVED_SEC = 0.001


@dataclass
class _Timed:
    note_id: str
    pitch: int
    start: float
    end: float
    velocity: int
    source: Any = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class PreservationReport:
    raw_count: int
    later_count: int
    matched: int
    deleted_from_raw: int
    added_vs_raw: int
    pitch_changed_vs_raw: int
    onset_changed_vs_raw: int
    duration_changed_vs_raw: int
    velocity_changed_vs_raw: int
    raw_event_preservation_rate: float
    unmodified_from_raw: int
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_count": self.raw_count,
            "later_count": self.later_count,
            "matched": self.matched,
            "deleted_from_raw": self.deleted_from_raw,
            "added_vs_raw": self.added_vs_raw,
            "pitch_changed_vs_raw": self.pitch_changed_vs_raw,
            "onset_changed_vs_raw": self.onset_changed_vs_raw,
            "duration_changed_vs_raw": self.duration_changed_vs_raw,
            "velocity_changed_vs_raw": self.velocity_changed_vs_raw,
            "raw_event_preservation_rate": self.raw_event_preservation_rate,
            "unmodified_from_raw": self.unmodified_from_raw,
            **self.extra,
        }


@dataclass
class QuantizationReport:
    quantized_event_count: int
    source_event_count: int
    events_moved: int
    events_unchanged: int
    average_onset_shift_ms: float
    max_onset_shift_ms: float
    average_duration_change_ms: float
    notes_added: int
    notes_deleted: int
    percent_events_changed: float
    count_drop_warning: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "quantized_event_count": self.quantized_event_count,
            "source_event_count": self.source_event_count,
            "events_moved": self.events_moved,
            "events_unchanged": self.events_unchanged,
            "average_onset_shift_ms": self.average_onset_shift_ms,
            "max_onset_shift_ms": self.max_onset_shift_ms,
            "average_duration_change_ms": self.average_duration_change_ms,
            "notes_added": self.notes_added,
            "notes_deleted": self.notes_deleted,
            "percent_events_changed": self.percent_events_changed,
            "count_drop_warning": self.count_drop_warning,
        }


def note_to_timed(note: NoteEvent) -> _Timed:
    return _Timed(
        note_id=str(note.note_id or ""),
        pitch=int(note.pitch),
        start=float(note.start_time),
        end=float(note.end_time),
        velocity=int(note.velocity),
        source=note,
    )


def event_to_timed(
    event: MusicalEvent,
    *,
    tempo_map: TempoMap | None = None,
    fallback_bpm: float = 120.0,
    timing: str = "performance",
) -> _Timed:
    spb = 60.0 / float(fallback_bpm if fallback_bpm else 120.0)
    if (
        timing == "performance"
        and event.start_time_sec is not None
        and event.end_time_sec is not None
    ):
        start = float(event.start_time_sec)
        end = float(event.end_time_sec)
    elif tempo_map is not None:
        start = float(tempo_map.beats_to_seconds(event.start_beat))
        end = float(tempo_map.beats_to_seconds(event.start_beat + event.duration_beats))
    elif event.start_time_sec is not None and event.end_time_sec is not None:
        start = float(event.start_time_sec)
        end = float(event.end_time_sec)
    else:
        start = float(event.start_beat) * spb
        end = start + float(event.duration_beats) * spb
    return _Timed(
        note_id=str(event.note_id or ""),
        pitch=int(event.pitch),
        start=start,
        end=end,
        velocity=int(event.velocity),
        source=event,
    )


def _as_timed(items: Sequence[Any], **event_kwargs: Any) -> list[_Timed]:
    out: list[_Timed] = []
    for item in items:
        if isinstance(item, NoteEvent):
            out.append(note_to_timed(item))
        elif isinstance(item, MusicalEvent):
            out.append(event_to_timed(item, **event_kwargs))
        elif isinstance(item, _Timed):
            out.append(item)
        else:
            raise TypeError(f"Unsupported event type: {type(item)!r}")
    return out


def _match_pairs(
    raw: list[_Timed], later: list[_Timed]
) -> tuple[list[tuple[_Timed, _Timed]], list[_Timed], list[_Timed]]:
    used_later: set[int] = set()
    pairs: list[tuple[_Timed, _Timed]] = []
    later_by_id: dict[str, list[int]] = {}
    for i, item in enumerate(later):
        if item.note_id:
            later_by_id.setdefault(item.note_id, []).append(i)

    unmatched_raw: list[_Timed] = []
    for src in raw:
        hit = None
        if src.note_id and src.note_id in later_by_id:
            for idx in later_by_id[src.note_id]:
                if idx not in used_later:
                    hit = idx
                    break
        if hit is None:
            best_i = None
            best_dt = None
            for i, dst in enumerate(later):
                if i in used_later:
                    continue
                if dst.note_id and src.note_id and dst.note_id != src.note_id:
                    continue
                if int(dst.pitch) != int(src.pitch):
                    continue
                dt = abs(dst.start - src.start)
                if best_dt is None or dt < best_dt:
                    best_dt = dt
                    best_i = i
            # Un-id'd greedy match must still be the same musical attack.
            if best_i is not None and best_dt is not None and best_dt <= 0.25:
                hit = best_i
        if hit is None:
            unmatched_raw.append(src)
            continue
        used_later.add(hit)
        pairs.append((src, later[hit]))

    unmatched_later = [item for i, item in enumerate(later) if i not in used_later]
    return pairs, unmatched_raw, unmatched_later


def compare_to_raw(
    raw_items: Sequence[Any],
    later_items: Sequence[Any],
    *,
    onset_tol: float = ONSET_CHANGED_SEC,
    duration_tol: float = DURATION_CHANGED_SEC,
    tempo_map: TempoMap | None = None,
    fallback_bpm: float = 120.0,
    later_timing: str = "performance",
) -> PreservationReport:
    raw = _as_timed(raw_items)
    later = _as_timed(
        later_items,
        tempo_map=tempo_map,
        fallback_bpm=fallback_bpm,
        timing=later_timing,
    )
    pairs, deleted, added = _match_pairs(raw, later)
    pitch_changed = 0
    onset_changed = 0
    duration_changed = 0
    velocity_changed = 0
    unmodified = 0
    for src, dst in pairs:
        p_ch = int(src.pitch) != int(dst.pitch)
        o_ch = abs(src.start - dst.start) > onset_tol
        d_ch = abs(src.duration - dst.duration) > duration_tol
        v_ch = int(src.velocity) != int(dst.velocity)
        if p_ch:
            pitch_changed += 1
        if o_ch:
            onset_changed += 1
        if d_ch:
            duration_changed += 1
        if v_ch:
            velocity_changed += 1
        if not (p_ch or o_ch or d_ch):
            unmodified += 1
    raw_count = len(raw)
    preserved = raw_count - len(deleted)
    rate = (preserved / raw_count) if raw_count else 1.0
    return PreservationReport(
        raw_count=raw_count,
        later_count=len(later),
        matched=len(pairs),
        deleted_from_raw=len(deleted),
        added_vs_raw=len(added),
        pitch_changed_vs_raw=pitch_changed,
        onset_changed_vs_raw=onset_changed,
        duration_changed_vs_raw=duration_changed,
        velocity_changed_vs_raw=velocity_changed,
        raw_event_preservation_rate=rate,
        unmodified_from_raw=unmodified,
    )


def quantization_report(
    source_events: Sequence[MusicalEvent],
    quantized_events: Sequence[MusicalEvent],
    *,
    tempo_map: TempoMap | None = None,
    fallback_bpm: float = 120.0,
    moved_sec: float = QUANTIZE_MOVED_SEC,
) -> QuantizationReport:
    """Compare notation timing (beat grid), not performance start_time_sec."""
    src = [
        event_to_timed(
            e, tempo_map=tempo_map, fallback_bpm=fallback_bpm, timing="notation"
        )
        for e in source_events
    ]
    q = [
        event_to_timed(
            e, tempo_map=tempo_map, fallback_bpm=fallback_bpm, timing="notation"
        )
        for e in quantized_events
    ]
    pairs, deleted, added = _match_pairs(src, q)
    onset_shifts: list[float] = []
    dur_shifts: list[float] = []
    moved = 0
    unchanged = 0
    for a, b in pairs:
        onset_ms = abs(a.start - b.start) * 1000.0
        dur_ms = abs(a.duration - b.duration) * 1000.0
        onset_shifts.append(onset_ms)
        dur_shifts.append(dur_ms)
        if abs(a.start - b.start) > moved_sec or abs(a.duration - b.duration) > moved_sec:
            moved += 1
        else:
            unchanged += 1
    src_count = len(src)
    q_count = len(q)
    return QuantizationReport(
        quantized_event_count=q_count,
        source_event_count=src_count,
        events_moved=moved,
        events_unchanged=unchanged,
        average_onset_shift_ms=(sum(onset_shifts) / len(onset_shifts)) if onset_shifts else 0.0,
        max_onset_shift_ms=max(onset_shifts) if onset_shifts else 0.0,
        average_duration_change_ms=(sum(dur_shifts) / len(dur_shifts)) if dur_shifts else 0.0,
        notes_added=len(added),
        notes_deleted=len(deleted),
        percent_events_changed=(100.0 * moved / len(pairs)) if pairs else 0.0,
        count_drop_warning=q_count < src_count,
    )


def stage_preservation_bundle(
    *,
    raw_notes: Sequence[NoteEvent] | None,
    validated_notes: Sequence[NoteEvent] | None,
    structured_events: Sequence[MusicalEvent] | None,
    quantized_events: Sequence[MusicalEvent] | None,
    tempo_map: TempoMap | None = None,
    fallback_bpm: float = 120.0,
) -> dict[str, Any]:
    raw = list(raw_notes or [])
    validated = list(validated_notes or [])
    structured = list(structured_events or [])
    quantized = list(quantized_events or [])
    return {
        "raw_note_count": len(raw),
        "validated_note_count": len(validated),
        "structured_note_count": len(structured),
        "quantized_note_count": len(quantized),
        "raw_vs_validated": compare_to_raw(raw, validated).to_dict(),
        "validated_vs_structured": compare_to_raw(
            validated,
            structured,
            tempo_map=tempo_map,
            fallback_bpm=fallback_bpm,
            later_timing="performance",
        ).to_dict(),
        "raw_vs_structured": compare_to_raw(
            raw,
            structured,
            tempo_map=tempo_map,
            fallback_bpm=fallback_bpm,
            later_timing="performance",
        ).to_dict(),
        "raw_vs_quantized": compare_to_raw(
            raw,
            quantized,
            tempo_map=tempo_map,
            fallback_bpm=fallback_bpm,
            later_timing="notation",
        ).to_dict(),
        "quantization": quantization_report(
            structured,
            quantized,
            tempo_map=tempo_map,
            fallback_bpm=fallback_bpm,
        ).to_dict(),
    }
