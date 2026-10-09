"""Future arrangement stage — extension point only.

Interpretation recovers intended notation from a performance. Arrangement is a
later, separately authorized stage that may change harmony, texture, or
instrumentation and must write a distinct derived score.

This milestone does not reharmonize, generate accompaniment, or expose a
target-style control. ``arrange()`` is identity so the production pipeline can
grow an explicit second derived-score path without mixing it into
interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

ARRANGEMENT_CONFIG_VERSION = 1


@dataclass(frozen=True)
class ArrangementConfig:
    """Intended future controls. Not wired to jobs, UI, or cache identity."""

    version: int = ARRANGEMENT_CONFIG_VERSION
    target_style: str = "unchanged"
    instrumentation: str | None = None
    difficulty: str | None = None
    melody_preservation: str = "preserve"
    harmonic_freedom: str = "none"
    accompaniment_pattern: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "target_style": self.target_style,
            "instrumentation": self.instrumentation,
            "difficulty": self.difficulty,
            "melody_preservation": self.melody_preservation,
            "harmonic_freedom": self.harmonic_freedom,
            "accompaniment_pattern": self.accompaniment_pattern,
            "implemented": False,
        }


def arrange(
    interpreted_events: Iterable,
    config: ArrangementConfig | None = None,
) -> tuple[list, dict[str, Any]]:
    """Consume an interpreted score; currently returns it unchanged.

    Callers that want arrangement later should write the result to a separate
    derived-score artifact. Never overwrite raw MIDI or the interpreted score.
    """
    events = list(interpreted_events)
    unused = config or ArrangementConfig()
    return events, {
        "status": "skipped",
        "reason": "arrangement_not_implemented",
        "config": unused.to_dict(),
        "note_count": len(events),
    }
