"""RunPod Serverless handler contract (no CUDA, no RunPod SDK)."""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from unittest.mock import patch

import pretty_midi
import pytest

GPU_WORKER = Path(__file__).resolve().parents[2] / "gpu-worker"
sys.path.insert(0, str(GPU_WORKER))

import handler as serverless  # noqa: E402


def _one_note_midi_bytes(pitch: int = 64) -> bytes:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=0.0, end=0.5))
    midi.instruments.append(inst)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "n.mid"
        midi.write(str(path))
        return path.read_bytes()


def test_serverless_event_returns_midi_base64():
    midi_bytes = _one_note_midi_bytes(67)

    def fake_transcribe(_path: str) -> bytes:
        return midi_bytes

    event = {
        "input": {
            "audio_base64": base64.b64encode(b"RIFF-AUDIO").decode(),
            "filename": "recording.wav",
        }
    }
    with patch.object(serverless, "get_model", return_value=object()):
        with patch.object(serverless, "transcribe_audio_path", side_effect=fake_transcribe):
            result = serverless.transcribe_event(event)
    decoded = base64.b64decode(result["midi_base64"])
    assert decoded[:4] == b"MThd"
    assert result["model"] == "yourmt3"
    assert "inference_seconds" in result["timing"]


def test_serverless_missing_audio_base64():
    with pytest.raises(ValueError, match="Missing input.audio_base64"):
        serverless.transcribe_event({"input": {"filename": "x.wav"}})


def test_serverless_accepts_double_wrapped_input():
    midi_bytes = _one_note_midi_bytes(64)

    def fake_transcribe(_path: str) -> bytes:
        return midi_bytes

    event = {
        "id": "sync-test",
        "input": {
            "input": {
                "audio_base64": base64.b64encode(b"RIFF").decode(),
                "filename": "recording.wav",
            }
        },
    }
    with patch.object(serverless, "get_model", return_value=object()):
        with patch.object(serverless, "transcribe_audio_path", side_effect=fake_transcribe):
            result = serverless.handler(event)
    assert base64.b64decode(result["midi_base64"])[:4] == b"MThd"


def test_serverless_accepts_runpod_job_envelope():
    midi_bytes = _one_note_midi_bytes(61)

    def fake_transcribe(_path: str) -> bytes:
        return midi_bytes

    event = {
        "id": "sync-test",
        "input": {
            "audio_base64": base64.b64encode(b"RIFF").decode(),
            "filename": "clip.wav",
        },
    }
    with patch.object(serverless, "get_model", return_value=object()):
        with patch.object(serverless, "transcribe_audio_path", side_effect=fake_transcribe):
            result = serverless.handler(event)
    assert result["model"] == "yourmt3"


def test_serverless_accepts_top_level_input_fields():
    midi_bytes = _one_note_midi_bytes(60)

    def fake_transcribe(_path: str) -> bytes:
        return midi_bytes

    with patch.object(serverless, "get_model", return_value=object()):
        with patch.object(serverless, "transcribe_audio_path", side_effect=fake_transcribe):
            result = serverless.handler(
                {
                    "audio_base64": base64.b64encode(b"RIFF").decode(),
                    "filename": "clip.mp3",
                }
            )
    assert base64.b64decode(result["midi_base64"])[:4] == b"MThd"
