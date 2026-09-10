"""Notation quantization facade.

Raw transcribed events are copied into `last_raw_events` and never mutated.
Adaptive / strict modes build a separate notation representation via
`mir.adaptive_quantizer`. Off and PM2S keep their existing behaviour.

Writable-duration helpers used by NotationPlanner also live here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from mir.models import MeterHypothesis, staff_for_hand
from mir.pipeline_config import QuantizationMode, parse_quantization_mode, pm2s_required
from mir.types import MusicalEvent, copy_event


# Whole, dotted half, half, dotted quarter, quarter, dotted eighth,
# quarter-note triplet, eighth, dotted sixteenth, eighth-note triplet,
# sixteenth. No complex tuplets.
DURATION_CANDIDATES = (
    4.0,
    3.0,
    2.0,
    1.5,
    1.0,
    0.75,
    2.0 / 3.0,
    0.5,
    0.375,
    1.0 / 3.0,
    0.25,
    0.125,
)

SIMPLE_DURATIONS = {4.0, 2.0, 1.0, 0.5, 0.25, 0.125}
DOTTED_DURATIONS = {3.0, 1.5, 0.75, 0.375}
TUPLET_DURATIONS = {2.0 / 3.0, 1.0 / 3.0}

# MusicXML needs named note types. Off-mode spelling uses these values (no
# tuplets, no 32nd-grid snap). 64th = 0.0625 ql is the smallest unit.
WRITABLE_DURATIONS = (
    4.0,
    3.0,
    2.0,
    1.5,
    1.0,
    0.75,
    0.5,
    0.375,
    0.25,
    0.1875,
    0.125,
    0.09375,
    0.0625,
)
SMALLEST_WRITABLE = 0.0625

VOICE_SUM_TOLERANCE = 0.08


@dataclass
class QuantizerConfig:
    absorb_rest_ql: float = 0.12
    max_timing_error: float = 0.18
    complexity_weight: float = 0.35
    tuplet_weight: float = 0.55
    tie_weight: float = 0.2
    rest_weight: float = 0.7
    # Notes this close to the next barline (in beats) that round to it on a
    # 16th grid belong to the next measure. Stops a 2 ms-early downbeat from
    # being clamped to the last 16th of the previous bar.
    barline_pull_beats: float = 0.125
    chord_window_beats: float = 0.08
    max_onset_move: float = 0.22


def snap_writable_length(quarter_length: float, *, allow_empty: bool = False) -> float:
    """Round a duration to the nearest 64th, the smallest MusicXML unit we spell."""
    ql = float(quarter_length)
    if ql <= 1e-9:
        return 0.0
    steps = int(round(ql / SMALLEST_WRITABLE))
    if steps <= 0:
        return 0.0 if allow_empty else SMALLEST_WRITABLE
    return steps * SMALLEST_WRITABLE


def duration_pieces(
    quarter_length: float,
    *,
    allow_empty: bool = False,
    max_total: float | None = None,
) -> list[float]:
    """Split a duration into named note values that sum to a 64th-rounded length.

    Does not invent tuplets. Leftover smaller than a 64th is dropped unless
    ``allow_empty`` is false, in which case a single 64th is emitted.
    """
    snapped = snap_writable_length(quarter_length, allow_empty=allow_empty)
    if max_total is not None:
        cap_steps = int(math.floor((float(max_total) + 1e-12) / SMALLEST_WRITABLE))
        cap = max(0.0, cap_steps * SMALLEST_WRITABLE)
        snapped = min(snapped, cap)
        if snapped <= 1e-9:
            return []
    if snapped <= 1e-9:
        return []
    remaining = snapped
    pieces: list[float] = []
    for d in WRITABLE_DURATIONS:
        while remaining >= d - 1e-12:
            pieces.append(d)
            remaining -= d
        if remaining < SMALLEST_WRITABLE - 1e-12:
            break
    if remaining > 1e-9:
        pieces.append(SMALLEST_WRITABLE)
    if not pieces and not allow_empty:
        return [SMALLEST_WRITABLE]
    return pieces


def tie_chain(piece_count: int, existing: str | None) -> list[str | None]:
    """Ties for a duration split, merged with an existing barline tie."""
    if piece_count <= 0:
        return []
    if piece_count == 1:
        return [existing]
    ties: list[str | None] = ["continue"] * piece_count
    ties[0] = "start" if existing in (None, "start") else "continue"
    ties[-1] = "stop" if existing in (None, "stop") else "continue"
    return ties


def measure_index_for_onset(
    start_beat: float,
    mql: float,
    pull_beats: float = 0.125,
) -> int:
    """Assign an onset to a measure without trapping early downbeats."""
    if mql <= 0:
        return 0
    idx = max(0, int(math.floor((start_beat + 1e-9) / mql)))
    measure_start = idx * mql
    measure_end = measure_start + mql
    if (measure_end - start_beat) > pull_beats + 1e-12:
        return idx
    rel = start_beat - measure_start
    nearest_16 = round(rel / 0.25) * 0.25
    if nearest_16 >= mql - 1e-9:
        return idx + 1
    return idx


class MeasureQuantizer:
    def __init__(
        self,
        config: QuantizerConfig | None = None,
        mode: QuantizationMode | str | None = None,
        pm2s_processor=None,
    ):
        self.config = config or QuantizerConfig()
        self.mode = parse_quantization_mode(mode)
        self.last_summary: dict = {}
        self.last_events: list[MusicalEvent] = []
        self.last_raw_events: list[MusicalEvent] = []
        self.last_notation_events: list[MusicalEvent] = []
        self.last_report = None
        self._pm2s_processor = pm2s_processor
        self._pm2s_load_failed = False

    def quantize(
        self,
        events: list[MusicalEvent],
        meter: MeterHypothesis,
    ) -> tuple[list[MusicalEvent], list[dict]]:
        self.last_raw_events = [copy_event(ev) for ev in events]
        if not events and self.mode != QuantizationMode.PERFORMANCE:
            self.last_summary = _empty_quantizer_summary()
            self.last_events = []
            self.last_notation_events = []
            self.last_report = None
            return [], []
        if self.mode == QuantizationMode.OFF:
            return self._identity(events)
        if self.mode == QuantizationMode.PM2S:
            return self._quantize_pm2s(events)

        if self.mode == QuantizationMode.PERFORMANCE:
            from mir.performance_score import quantize_notation
        else:
            from mir.adaptive_quantizer import quantize_notation

        out, decisions, report = quantize_notation(
            self.last_raw_events,
            meter,
            config=self.config,
            mode=self.mode,
        )
        self.last_events = list(out)
        self.last_notation_events = list(out)
        self.last_report = report
        self.last_summary = dict(report.summary)
        return out, decisions

    def _identity(
        self, events: list[MusicalEvent]
    ) -> tuple[list[MusicalEvent], list[dict]]:
        """Keep transcribed onsets and durations.

        MusicXML still needs named note types. That spelling (tied 64th-based
        values, not a 32nd onset grid) happens in NotationPlanner, not here.
        """
        out: list[MusicalEvent] = []
        decisions: list[dict] = []
        for ev in events:
            copied = copy_event(ev)
            out.append(copied)
            decisions.append(
                {
                    "note_id": ev.note_id,
                    "raw_start": ev.start_beat,
                    "quantized_start": ev.start_beat,
                    "raw_duration": ev.duration_beats,
                    "quantized_duration": ev.duration_beats,
                    "grid": None,
                    "selected_grid": None,
                    "reason": "off_identity",
                }
            )
        self.last_events = list(out)
        self.last_notation_events = list(out)
        self.last_summary = summarize_quantization(events, out, decisions)
        return out, decisions

    def _quantize_pm2s(
        self, events: list[MusicalEvent]
    ) -> tuple[list[MusicalEvent], list[dict]]:
        try:
            processor = self._load_pm2s_processor()
            if processor is None:
                if pm2s_required():
                    raise RuntimeError(
                        "PM2S quantizer unavailable and TRANSCRIPTION_PM2S_REQUIRED=1. "
                        "Run scripts/setup_pm2s.sh or set TRANSCRIPTION_PM2S_REQUIRED=0."
                    )
                print("[PM2S] quantizer unavailable; keeping transcribed timing")
                return self._identity(events)
            from mir.pm2s_quantizer import apply_pm2s_rhythm

            out, decisions = apply_pm2s_rhythm(events, processor)
        except Exception as exc:
            if pm2s_required():
                raise RuntimeError(
                    f"PM2S quantizer failed ({exc}). "
                    "Set TRANSCRIPTION_PM2S_REQUIRED=0 to keep transcribed timing."
                ) from exc
            print(f"[PM2S] quantizer failed ({exc}); keeping transcribed timing")
            return self._identity(events)
        self.last_events = list(out)
        self.last_notation_events = list(out)
        self.last_summary = summarize_quantization(events, out, decisions)
        self.last_summary["engine"] = "pm2s"
        return out, decisions

    def _load_pm2s_processor(self):
        if self._pm2s_processor is not None:
            return self._pm2s_processor
        if self._pm2s_load_failed:
            return None
        try:
            from mir.pm2s_quantizer import load_pm2s_quantisation_processor

            self._pm2s_processor = load_pm2s_quantisation_processor()
            return self._pm2s_processor
        except Exception as exc:
            print(f"[PM2S] quantizer model unavailable ({exc})")
            self._pm2s_load_failed = True
            if pm2s_required():
                raise
            return None

    @staticmethod
    def _restore_missing(
        original: list[MusicalEvent],
        quantized: list[MusicalEvent],
        decisions: list[dict],
    ) -> tuple[list[MusicalEvent], list[dict]]:
        """Quantization must not drop events. Restore any missing by note_id."""
        if len(quantized) >= len(original):
            return quantized, decisions
        q_ids = {e.note_id for e in quantized if e.note_id}
        if not q_ids:
            return quantized, decisions
        restored = list(quantized)
        extra_decisions = list(decisions)
        for ev in original:
            if not ev.note_id or ev.note_id in q_ids:
                continue
            restored.append(copy_event(ev))
            extra_decisions.append(
                {
                    "note_id": ev.note_id,
                    "pitch": ev.pitch,
                    "raw_start": ev.start_beat,
                    "quantized_start": ev.start_beat,
                    "raw_duration": ev.duration_beats,
                    "quantized_duration": ev.duration_beats,
                    "grid": None,
                    "timing_error": 0.0,
                    "hand": ev.hand.value,
                    "voice": ev.voice,
                    "staff": staff_for_hand(ev.hand, ev.pitch),
                    "cost": 0.0,
                    "removed": False,
                    "reason": "restored_after_quantizer_drop",
                }
            )
        restored.sort(key=lambda e: (e.start_beat, e.pitch, e.voice))
        return restored, extra_decisions


def _empty_quantizer_summary() -> dict:
    return {
        "raw_events": 0,
        "quantized_events": 0,
        "events_changed": 0,
        "events_removed": 0,
        "average_onset_displacement": 0.0,
        "average_duration_displacement": 0.0,
        "triplet_decisions": 0,
        "removed_events": [],
    }


def summarize_quantization(
    original: list[MusicalEvent],
    quantized: list[MusicalEvent],
    decisions: list[dict],
) -> dict:
    onset_disp = [abs(float(d.get("quantized_start", 0)) - float(d.get("raw_start", 0))) for d in decisions]
    dur_disp = [
        abs(float(d.get("quantized_duration", 0)) - float(d.get("raw_duration", 0)))
        for d in decisions
    ]
    changed = 0
    triplets = 0
    for d in decisions:
        start_changed = abs(float(d.get("quantized_start", 0)) - float(d.get("raw_start", 0))) > 1e-6
        dur_changed = abs(float(d.get("quantized_duration", 0)) - float(d.get("raw_duration", 0))) > 1e-6
        if start_changed or dur_changed:
            changed += 1
        grid = d.get("selected_grid", d.get("grid"))
        try:
            grid_f = float(grid) if grid is not None else None
        except (TypeError, ValueError):
            grid_f = None
        if grid_f is not None and (
            abs(grid_f - (1.0 / 3.0)) < 1e-6 or abs(grid_f - (1.0 / 6.0)) < 1e-6
        ):
            triplets += 1
    orig_ids = {e.note_id for e in original if e.note_id}
    q_ids = {e.note_id for e in quantized if e.note_id}
    removed_ids = sorted(orig_ids - q_ids)
    return {
        "raw_events": len(original),
        "quantized_events": len(quantized),
        "events_changed": changed,
        "events_removed": max(0, len(original) - len(quantized)),
        "average_onset_displacement": (sum(onset_disp) / len(onset_disp)) if onset_disp else 0.0,
        "average_duration_displacement": (sum(dur_disp) / len(dur_disp)) if dur_disp else 0.0,
        "mean_onset_displacement": (sum(onset_disp) / len(onset_disp)) if onset_disp else 0.0,
        "mean_duration_displacement": (sum(dur_disp) / len(dur_disp)) if dur_disp else 0.0,
        "max_onset_displacement": max(onset_disp) if onset_disp else 0.0,
        "max_duration_displacement": max(dur_disp) if dur_disp else 0.0,
        "triplet_decisions": triplets,
        "removed_events": removed_ids,
    }
