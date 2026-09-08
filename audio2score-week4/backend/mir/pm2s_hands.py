"""Opt-in PM2S RNN piano hand assignment.

PM2S (ISMIR 2022, cheriell/PM2S) is trained on performance MIDI. We use only
the hand-part head. Quantization, beat, key, and time-signature heads are not
called, so transcribed onsets and durations stay untouched.

Default production path stays on the Viterbi HandSeparator. Set
TRANSCRIPTION_HAND_SEPARATOR=pm2s to try this on a worker that has torch plus
the PM2S checkout. Missing weights or import errors fall back to Viterbi.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Sequence

import numpy as np

from mir.hand_separator import HandDecision, HandSeparator
from mir.pipeline_config import env_bool
from mir.types import Hand, MusicalEvent, copy_event

# Training labels in PM2S `dev/data/data_utils.py`: 0 left, 1 right.
_PM2S_HAND = {0: Hand.LEFT, 1: Hand.RIGHT}


def event_onset_sec(event: MusicalEvent) -> float:
    if event.start_time_sec is not None:
        return float(event.start_time_sec)
    return float(event.start_beat) * 0.5


def event_duration_sec(event: MusicalEvent) -> float:
    if event.start_time_sec is not None and event.end_time_sec is not None:
        return max(0.01, float(event.end_time_sec) - float(event.start_time_sec))
    return max(0.01, float(event.duration_beats) * 0.5)


def events_to_note_seq(
    events: Sequence[MusicalEvent],
) -> tuple[np.ndarray, list[MusicalEvent]]:
    """Build PM2S note_seq [pitch, onset, duration, velocity], onset then pitch."""
    ordered = sorted(
        events,
        key=lambda ev: (event_onset_sec(ev), int(ev.pitch), ev.note_id or ""),
    )
    rows = [
        [
            float(ev.pitch),
            event_onset_sec(ev),
            event_duration_sec(ev),
            float(max(1, min(127, int(ev.velocity or 64)))),
        ]
        for ev in ordered
    ]
    return np.asarray(rows, dtype=np.float64), list(ordered)


def _prepend_pm2s_repo() -> None:
    repo = os.getenv("PM2S_REPO", "").strip()
    if repo and repo not in sys.path:
        sys.path.insert(0, repo)


def pm2s_importable() -> bool:
    """True when the PM2S package can be imported. Does not load weights."""
    _prepend_pm2s_repo()
    try:
        import pm2s.features.hand_part  # noqa: F401

        return True
    except Exception:
        return False


def _as_labels(raw: Any, n: int) -> np.ndarray | None:
    try:
        arr = np.asarray(raw)
    except Exception:
        return None
    arr = np.squeeze(arr)
    if arr.ndim != 1 or arr.shape[0] != n:
        return None
    return arr


def _hand_for_label(label: int, *, flip: bool) -> Hand:
    bit = 1 if int(label) > 0 else 0
    if flip:
        bit = 1 - bit
    return _PM2S_HAND[bit]


class Pm2sHandSeparator:
    """Assign LEFT / RIGHT from the PM2S hand-part RNN; never rewrite notes."""

    def __init__(
        self,
        processor: Any | None = None,
        fallback: HandSeparator | None = None,
    ):
        self._processor = processor
        self._fallback = fallback or HandSeparator()
        self._load_failed = False
        self.last_decisions: list[HandDecision] = []
        self.last_source: str = "pm2s"

    def separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        self.last_decisions = []
        self.last_source = "pm2s"
        if not events:
            return []
        try:
            return self._separate_pm2s(events)
        except Exception as exc:
            print(f"[PM2S] hand split failed ({exc}); falling back to Viterbi")
            return self._fallback_separate(events)

    def _fallback_separate(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        self.last_source = "viterbi_fallback"
        out = self._fallback.separate(events)
        self.last_decisions = list(getattr(self._fallback, "last_decisions", []))
        return out

    def _load_processor(self) -> Any | None:
        if self._processor is not None:
            return self._processor
        if self._load_failed:
            return None
        _prepend_pm2s_repo()
        try:
            from pm2s.features.hand_part import RNNHandPartProcessor

            self._processor = RNNHandPartProcessor()
            return self._processor
        except Exception as exc:
            print(f"[PM2S] hand model unavailable ({exc}); falling back to Viterbi")
            self._load_failed = True
            return None

    def _separate_pm2s(self, events: list[MusicalEvent]) -> list[MusicalEvent]:
        processor = self._load_processor()
        if processor is None:
            return self._fallback_separate(events)

        note_seq, ordered = events_to_note_seq(events)
        raw = processor.process_note_seq(note_seq)
        labels = _as_labels(raw, len(ordered))
        if labels is None:
            raise RuntimeError(
                f"PM2S hand output length {getattr(raw, 'shape', type(raw))} "
                f"!= {len(ordered)} notes"
            )

        flip = env_bool("TRANSCRIPTION_PM2S_HAND_FLIP", default=False)
        assigned: dict[int, MusicalEvent] = {}
        decisions: list[HandDecision] = []
        for ev, label in zip(ordered, labels):
            value = float(label)
            binary = 1 if value > 0.5 else 0
            hand = _hand_for_label(binary, flip=flip)
            if 0.0 <= value <= 1.0 and value not in (0.0, 1.0):
                conf = max(0.51, min(0.99, abs(value - 0.5) * 2.0))
            else:
                conf = 0.85
            competing = Hand.RIGHT if hand == Hand.LEFT else Hand.LEFT
            assigned[id(ev)] = copy_event(
                ev,
                hand=hand,
                hand_confidence=round(conf, 3),
            )
            decisions.append(
                HandDecision(
                    note_id=ev.note_id,
                    pitch=ev.pitch,
                    start_beat=ev.start_beat,
                    selected=hand.value,
                    confidence=round(conf, 3),
                    competing_hand=competing.value,
                    competing_cost_delta=0.0,
                    factors={"source": "pm2s", "label": binary},
                )
            )

        result: list[MusicalEvent] = []
        for ev in events:
            out = assigned.get(id(ev), ev)
            if HandSeparator._is_locked(ev):
                result.append(
                    copy_event(
                        out,
                        hand=ev.hand,
                        hand_confidence=max(ev.hand_confidence, 0.95),
                    )
                )
            else:
                result.append(out)
        self.last_decisions = decisions
        self.last_source = "pm2s"
        return result
