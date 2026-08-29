"""Canonical Solo / Polyphonic mode aliases."""

from modes import (
    DEFAULT_MT3_MODEL,
    POLYPHONIC,
    SOLO,
    canonical_mode,
    is_polyphonic,
    parse_transcription_mode,
)


def test_aliases():
    assert parse_transcription_mode(None) == SOLO
    assert parse_transcription_mode("solo") == SOLO
    assert parse_transcription_mode("FAST") == SOLO
    assert parse_transcription_mode("polyphonic") == POLYPHONIC
    assert parse_transcription_mode("poly") == POLYPHONIC
    assert parse_transcription_mode("quality") == POLYPHONIC
    assert parse_transcription_mode("mt3") == POLYPHONIC
    assert is_polyphonic("quality") is True
    assert is_polyphonic("solo") is False
    assert canonical_mode("nope") == SOLO
    assert DEFAULT_MT3_MODEL == "yourmt3"
