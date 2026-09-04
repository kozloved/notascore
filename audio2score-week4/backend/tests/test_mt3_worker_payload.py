"""Parse RunPod job payloads without loading YourMT3."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2].parent / "mt3-worker"
sys.path.insert(0, str(ROOT))

from payload import audio_base64_from_job, job_input  # noqa: E402


def test_run_sync_shape():
    raw, name = audio_base64_from_job(
        {
            "id": "abc",
            "input": {
                "audio_base64": "QUJD",
                "filename": "clip.wav",
            },
        }
    )
    assert raw == "QUJD"
    assert name == "clip.wav"


def test_console_unwrapped_shape():
    raw, name = audio_base64_from_job(
        {"audio_base64": "QUJD", "filename": "a.wav"}
    )
    assert raw == "QUJD"
    assert name == "a.wav"


def test_double_wrapped_console_shape():
    raw, name = audio_base64_from_job(
        {
            "id": "abc",
            "input": {
                "input": {
                    "audio_base64": "QUJD",
                    "filename": "clip.wav",
                }
            },
        }
    )
    assert raw == "QUJD"
    assert name == "clip.wav"
    assert job_input({"input": {}}) == {}


def test_placeholder_still_detected_as_present():
    raw, _ = audio_base64_from_job(
        {"input": {"audio_base64": "<base64 of a short wav>"}}
    )
    assert raw == "<base64 of a short wav>"


def test_missing():
    raw, name = audio_base64_from_job({"input": {"filename": "x.wav"}})
    assert raw is None