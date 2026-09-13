"""Explicit piano layout authority for hands and voices."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mir.types import Hand, MusicalEvent


class LayoutAuthority(str, Enum):
    NONE = "none"
    LOCKED = "locked"
    PROVIDER = "provider"
    INFERRED = "inferred"
    MIXED = "mixed"


_ASSIGNED_HANDS = {Hand.LEFT, Hand.RIGHT, Hand.AMBIGUOUS}


@dataclass(frozen=True)
class LayoutResult:
    events: list[MusicalEvent]
    authority: LayoutAuthority
    voice_complete: bool
    hand_complete: bool

    @property
    def layout_source(self) -> str:
        """Quantizer summary label consumed by existing reports/tests."""
        if self.authority in (LayoutAuthority.LOCKED, LayoutAuthority.PROVIDER):
            return "pipeline"
        if self.authority is LayoutAuthority.MIXED:
            return "mixed"
        if self.authority is LayoutAuthority.INFERRED:
            return "inferred"
        return "inferred"


def hands_complete(events: list[MusicalEvent]) -> bool:
    """True when every note carries an assigned hand label (including AMBIGUOUS)."""
    if not events:
        return False
    return all(ev.hand in _ASSIGNED_HANDS for ev in events)


def voices_complete(events: list[MusicalEvent]) -> bool:
    """True when voices were explicitly assigned, including a single voice 0."""
    if not events:
        return False
    if all(getattr(ev, "voice_assigned", False) for ev in events):
        return True
    voices = {int(ev.voice) for ev in events}
    return len(voices) > 1 or any(int(ev.voice) != 0 for ev in events)


def classify_hand_authority(events: list[MusicalEvent]) -> LayoutAuthority:
    if not events or not hands_complete(events):
        return LayoutAuthority.NONE
    locked = sum(
        1
        for ev in events
        if getattr(ev, "hand_locked", False) and ev.hand in (Hand.LEFT, Hand.RIGHT)
    )
    if locked == len(events):
        return LayoutAuthority.LOCKED
    if locked:
        return LayoutAuthority.MIXED
    # Named MIDI / pipeline hands without locks still count as provider when
    # already complete; inferred assignments also land here until marked.
    return LayoutAuthority.PROVIDER
