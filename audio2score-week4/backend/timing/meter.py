"""Meter candidates for the musical-time engine.

Scoring lives in mir.meter / mir.meter_arbitrator. This module only names the
hypothesis set the next-gen pipeline is willing to consider.
"""

from __future__ import annotations

METER_CANDIDATES = ("2/4", "3/4", "4/4", "6/8", "9/8", "12/8")
METER_AMBIGUOUS = "METER_AMBIGUOUS"


def meter_status(confidence: float | None, *, threshold: float = 0.5) -> str:
    if confidence is None or confidence < threshold:
        return METER_AMBIGUOUS
    return "ok"
