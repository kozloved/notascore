"""Pure transcription guards. Safe for MIDI-only test collection."""

from __future__ import annotations


def fail_if_transcribe(monkeypatch) -> None:
    """Fail if a GPU transcription backend is invoked during notation work."""
    import pytest

    def boom(*_args, **_kwargs):
        pytest.fail("transcription provider called during notation regeneration")

    monkeypatch.setattr(
        "adapters.mt3_backend.MT3Backend.transcribe_notes", boom, raising=False
    )
    monkeypatch.setattr(
        "adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes",
        boom,
        raising=False,
    )
