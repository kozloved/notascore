"""Canonical transcription modes.

Solo = Basic Pitch on this machine (CPU).
Polyphonic = latest MT3-family model on a remote GPU worker.

The GPU worker runs mt3-infer 0.2.0 (July 2026). Default model is YourMT3
(YPTF.MoE+Multi), the current production descendant of Magenta MT3.

Legacy aliases: fast → solo, quality → polyphonic.
"""

from __future__ import annotations

SOLO = "solo"
POLYPHONIC = "polyphonic"
DEFAULT_MODE = SOLO

MODE_ALIASES = {
    "solo": SOLO,
    "fast": SOLO,
    "polyphonic": POLYPHONIC,
    "poly": POLYPHONIC,
    "quality": POLYPHONIC,
    "mt3": POLYPHONIC,
}

ALLOWED_MODES = (SOLO, POLYPHONIC)

# mt3-infer 0.2.0 registry. yourmt3 is the latest polyphonic / multi-stem model.
MT3_MODELS = ("yourmt3", "mt3_pytorch", "mr_mt3")
DEFAULT_MT3_MODEL = "yourmt3"


def parse_transcription_mode(mode: str | None) -> str:
    """Return 'solo' or 'polyphonic'. Invalid values raise ValueError."""
    value = (mode or DEFAULT_MODE).strip().lower()
    if value not in MODE_ALIASES:
        raise ValueError(
            "Invalid transcription mode. Use 'solo' (Basic Pitch) or "
            "'polyphonic' (MT3). Legacy aliases: fast, quality."
        )
    return MODE_ALIASES[value]


def is_polyphonic(mode: str | None) -> bool:
    return parse_transcription_mode(mode) == POLYPHONIC


def canonical_mode(mode: str | None) -> str:
    """Best-effort canonical mode for API responses. Unknown → solo."""
    try:
        return parse_transcription_mode(mode)
    except ValueError:
        return DEFAULT_MODE
