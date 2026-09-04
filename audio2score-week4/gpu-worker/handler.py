"""RunPod Serverless entry for NotaScore YourMT3.

Transcription only. Returns MIDI. Does not clean, quantize, or rewrite notes.

RunPod calls this process. The HTTP FastAPI server in mt3_gpu_worker.py is
for Vast.ai / GPU pods, not for Serverless /runsync.

Expected job input:

  {"input": {"audio_base64": "<base64>", "filename": "recording.wav"}}

Successful return (RunPod wraps this in output):

  {"midi_base64": "<base64 MIDI>", "model": "yourmt3", "timing": {...}}
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
import tempfile

from mt3_gpu_worker import MODEL_NAME, get_model, transcribe_audio_path

_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}


def _input_dict(event: object) -> dict:
    if not isinstance(event, dict):
        return {}
    inner = event.get("input")
    if isinstance(inner, dict):
        return inner
    return event


def transcribe_event(event: object) -> dict:
    """Pure job body → result dict. Used by tests without the RunPod SDK."""
    inp = _input_dict(event)
    raw = inp.get("audio_base64")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Missing input.audio_base64")
    try:
        audio_bytes = base64.b64decode(raw.strip(), validate=False)
    except Exception as exc:
        raise ValueError("input.audio_base64 is not valid base64") from exc
    if not audio_bytes:
        raise ValueError("input.audio_base64 is empty")

    filename = str(inp.get("filename") or "recording.wav")
    suffix = Path(filename).suffix.lower() or ".wav"
    if suffix not in _AUDIO_SUFFIXES:
        suffix = ".wav"

    load_started = time.perf_counter()
    get_model()
    model_load_seconds = time.perf_counter() - load_started

    infer_started = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        audio_path = tmp.name
    try:
        midi_bytes = transcribe_audio_path(audio_path)
    finally:
        Path(audio_path).unlink(missing_ok=True)
    inference_seconds = time.perf_counter() - infer_started

    if not midi_bytes or midi_bytes[:4] != b"MThd":
        raise RuntimeError("Model did not return MIDI")

    total_seconds = model_load_seconds + inference_seconds
    print(
        f"[MT3 serverless] model={MODEL_NAME} midi_bytes={len(midi_bytes)} "
        f"inference_seconds={inference_seconds:.2f}",
        flush=True,
    )
    return {
        "midi_base64": base64.b64encode(midi_bytes).decode("ascii"),
        "model": MODEL_NAME,
        "timing": {
            "model_load_seconds": round(model_load_seconds, 3),
            "inference_seconds": round(inference_seconds, 3),
            "total_seconds": round(total_seconds, 3),
        },
    }


def handler(event: dict) -> dict:
    return transcribe_event(event)


def main() -> None:
    print(f"[MT3 serverless] warming {MODEL_NAME}", flush=True)
    get_model()
    print("[MT3 serverless] ready", flush=True)
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
