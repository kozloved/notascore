"""Handler must connect to RunPod before CUDA/YourMT3 load."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2].parent / "mt3-worker"
sys.path.insert(0, str(ROOT))


def test_handler_source_does_not_load_model_before_start():
    text = (ROOT / "handler.py").read_text()
    assert "connecting to RunPod" in text
    assert "runpod.serverless.start" in text
    # Checkpoint load stays inside _ensure_model, not at import time.
    ensure_at = text.index("def _ensure_model")
    load_at = text.index("MODEL = load_model(")
    main_at = text.index('if __name__ == "__main__"')
    start_at = text.index("runpod.serverless.start")
    assert ensure_at < load_at < main_at
    assert start_at > main_at


def test_importing_handler_does_not_call_load_model(monkeypatch):
    sys.modules.pop("handler", None)
    fake_mt3 = MagicMock()
    monkeypatch.setitem(sys.modules, "mt3_infer", fake_mt3)
    monkeypatch.setitem(sys.modules, "runpod", MagicMock())
    monkeypatch.setitem(sys.modules, "soundfile", MagicMock())

    import handler as worker_handler

    importlib.reload(worker_handler)
    fake_mt3.load_model.assert_not_called()
    assert worker_handler.MODEL is None


def test_first_warmup_job_loads_model_once(monkeypatch):
    sys.modules.pop("handler", None)
    fake_model = MagicMock()
    fake_mt3 = MagicMock()
    fake_mt3.load_model.return_value = fake_model
    monkeypatch.setitem(sys.modules, "mt3_infer", fake_mt3)
    monkeypatch.setitem(sys.modules, "runpod", MagicMock())
    monkeypatch.setitem(sys.modules, "soundfile", MagicMock())

    import handler as worker_handler

    importlib.reload(worker_handler)
    monkeypatch.setattr(worker_handler, "refuse_unsupported_cuda", lambda _device: None)

    first = worker_handler.handler({"input": {"warmup": True}})
    second = worker_handler.handler({"id": "j2", "input": {"warmup": True}})

    assert first["warmup"] is True
    assert second["warmup"] is True
    fake_mt3.load_model.assert_called_once()
    fake_model.transcribe.assert_not_called()


def test_real_job_runs_inference_after_load(monkeypatch, tmp_path):
    sys.modules.pop("handler", None)
    midi = MagicMock()
    midi.save = lambda path: Path(path).write_bytes(b"MThd\x00\x00\x00\x06\x00\x01\x00\x01\x00\x60")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = midi
    fake_mt3 = MagicMock()
    fake_mt3.load_model.return_value = fake_model
    fake_sf = MagicMock()
    fake_sf.read.return_value = ([0.0, 0.1, 0.0], 22050)
    monkeypatch.setitem(sys.modules, "mt3_infer", fake_mt3)
    monkeypatch.setitem(sys.modules, "runpod", MagicMock())
    monkeypatch.setitem(sys.modules, "soundfile", fake_sf)

    import handler as worker_handler

    importlib.reload(worker_handler)
    monkeypatch.setattr(worker_handler, "refuse_unsupported_cuda", lambda _device: None)

    import base64

    payload = worker_handler.handler(
        {
            "id": "job-1",
            "input": {
                "audio_base64": base64.b64encode(b"RIFF").decode(),
                "filename": "clip.wav",
            },
        }
    )
    assert "midi_base64" in payload
    fake_model.transcribe.assert_called_once()
    fake_mt3.load_model.assert_called_once()
