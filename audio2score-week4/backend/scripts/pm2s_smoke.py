#!/usr/bin/env python3
"""Load real PM2S weights and run a tiny piano texture.

Prints JSON proving hands and rhythm came from the RNNs, not fallback.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

if not os.getenv("PM2S_REPO"):
    default = BACKEND.parents[1] / "vendor" / "pm2s"
    if default.is_dir():
        os.environ["PM2S_REPO"] = str(default)
os.environ.setdefault("TRANSCRIPTION_PM2S_HAND_FLIP", "1")

from mir.meter import MeterEstimator
from mir.pm2s_hands import Pm2sHandSeparator, pm2s_status
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent


def _ev(pitch, start_beat, dur, *, start_sec, note_id):
    return MusicalEvent(
        pitch=pitch,
        start_beat=start_beat,
        duration_beats=dur,
        velocity=80,
        hand=Hand.UNKNOWN,
        note_id=note_id,
        start_time_sec=start_sec,
        end_time_sec=start_sec + dur * 0.5,
    )


def main() -> int:
    status = pm2s_status()
    if not status.get("ready"):
        print(json.dumps({"ok": False, "reason": "pm2s_not_ready", "status": status}, indent=2))
        return 1

    events = []
    for i in range(8):
        t = i * 0.5
        events.append(_ev(48, float(i), 0.9, start_sec=t, note_id=f"bass{i}"))
        events.append(_ev(72 + (i % 4), float(i) + 0.11, 0.4, start_sec=t, note_id=f"rh{i}"))

    sep = Pm2sHandSeparator()
    hands = sep.separate(list(events))
    q = MeasureQuantizer(mode="pm2s")
    quantized, decisions = q.quantize(list(hands), MeterEstimator().select(events))
    raw = {e.note_id: e for e in events}
    payload = {
        "ok": sep.last_source == "pm2s"
        and q.last_summary.get("engine") == "pm2s"
        and all(d.get("reason") == "pm2s_quant" for d in decisions),
        "status": status,
        "hand_source": sep.last_source,
        "quant_engine": q.last_summary.get("engine"),
        "hands": {e.note_id: e.hand.value for e in hands},
        "quantized": [
            {
                "note_id": e.note_id,
                "pitch": e.pitch,
                "hand": e.hand.value,
                "raw_start": raw[e.note_id].start_beat,
                "quantized_start": e.start_beat,
                "raw_duration": raw[e.note_id].duration_beats,
                "quantized_duration": e.duration_beats,
            }
            for e in quantized
        ],
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
