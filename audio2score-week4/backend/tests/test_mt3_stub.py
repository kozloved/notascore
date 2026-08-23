"""MT3 backend stub tests."""

import pytest

from adapters.mt3_backend import MT3Backend


def test_mt3_not_implemented(tmp_path):
    backend = MT3Backend()
    with pytest.raises(NotImplementedError, match="MT3"):
        backend.transcribe_notes(tmp_path / "audio.wav")
