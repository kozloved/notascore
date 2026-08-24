"""Corpus generators plus legacy MIDICleaner fixtures."""

from benchmark.fixtures.cleaner import (
    ALL_CLEANER_FIXTURES,
    FIXTURE_CHORD_MISALIGNED,
    FIXTURE_MELODY_PRESERVE,
    FIXTURE_RESONANCE_GARBAGE,
    notes_from_dicts,
    notes_to_dicts,
)

__all__ = [
    "ALL_CLEANER_FIXTURES",
    "FIXTURE_CHORD_MISALIGNED",
    "FIXTURE_MELODY_PRESERVE",
    "FIXTURE_RESONANCE_GARBAGE",
    "notes_from_dicts",
    "notes_to_dicts",
]
