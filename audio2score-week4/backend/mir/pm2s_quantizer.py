"""Opt-in PM2S rhythm quantization (performance MIDI → beat onsets / values).

Uses RNNJointQuantisationProcessor only. Does not write a PM2S score MIDI or
call the full CRNNJointPM2S.convert() path. Pitches, velocity, and hands stay
untouched. Missing weights fall back to identity (same as quantization=off).
"""

from __future__ import annotations

from typing import Any

from mir.pm2s_hands import as_note_vector, events_to_note_seq, prepare_pm2s_runtime
from mir.types import MusicalEvent, copy_event

# Match mir.quantizer.SMALLEST_WRITABLE without importing that module.
_MIN_DURATION = 0.0625


def load_pm2s_quantisation_processor() -> Any:
    prepare_pm2s_runtime()
    from pm2s.features.quantisation import RNNJointQuantisationProcessor

    return RNNJointQuantisationProcessor()


def apply_pm2s_rhythm(
    events: list[MusicalEvent],
    processor: Any,
) -> tuple[list[MusicalEvent], list[dict]]:
    """Replace start_beat / duration_beats with PM2S onset and note-value heads."""
    if not events:
        return [], []
    note_seq, ordered = events_to_note_seq(events)
    raw = processor.process_note_seq(note_seq)
    if not isinstance(raw, (tuple, list)) or len(raw) != 2:
        raise RuntimeError(
            f"PM2S quantizer expected (onsets, values), got {type(raw)!r}"
        )
    onsets = as_note_vector(raw[0], len(ordered))
    values = as_note_vector(raw[1], len(ordered))
    if onsets is None or values is None:
        raise RuntimeError(
            f"PM2S quantizer output length mismatch for {len(ordered)} notes"
        )

    assigned: dict[int, tuple[MusicalEvent, dict]] = {}
    for ev, start, dur in zip(ordered, onsets, values):
        start_beat = max(0.0, float(start))
        duration_beats = max(_MIN_DURATION, float(dur))
        copied = copy_event(
            ev,
            start_beat=start_beat,
            duration_beats=duration_beats,
        )
        assigned[id(ev)] = (
            copied,
            {
                "note_id": ev.note_id,
                "raw_start": ev.start_beat,
                "quantized_start": start_beat,
                "raw_duration": ev.duration_beats,
                "quantized_duration": duration_beats,
                "grid": 1.0 / 24.0,
                "selected_grid": 1.0 / 24.0,
                "reason": "pm2s_quant",
            },
        )

    out: list[MusicalEvent] = []
    decisions: list[dict] = []
    for ev in events:
        copied, decision = assigned[id(ev)]
        out.append(copied)
        decisions.append(decision)
    return out, decisions
