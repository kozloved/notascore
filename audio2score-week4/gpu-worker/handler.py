"""RunPod Serverless entry for NotaScore YourMT3.

Transcription only. Returns MIDI. Does not clean, quantize, or rewrite notes.

RunPod calls handler(job). The job is:

  {"id": "...", "input": {"audio_base64": "<base64>", "filename": "recording.wav"}}

The RunPod web test wraps whatever you paste as `input`. If you paste a body
that already has `input`, audio ends up at input.input.audio_base64. This
handler accepts one or two levels of wrapping.

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
_AUDIO_KEYS = ("audio_base64", "audio", "file_base64", "wav_base64")


def _shape(obj: object, depth: int = 0) -> object:
    """Key tree only. Never include values (they may be base64)."""
    if depth > 4 or not isinstance(obj, dict):
        return type(obj).__name__
    return {str(key): _shape(value, depth + 1) for key, value in obj.items()}


def _find_audio(obj: object, depth: int = 0) -> tuple[str | None, str | None]:
    if depth > 4 or not isinstance(obj, dict):
        return None, None
    filename = obj.get("filename") if isinstance(obj.get("filename"), str) else None
    for key in _AUDIO_KEYS:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip(), filename
    inner = obj.get("input")
    if isinstance(inner, dict):
        audio, nested_name = _find_audio(inner, depth + 1)
        return audio, nested_name or filename
    return None, filename


def transcribe_event(event: object) -> dict:
    """Pure job body → result dict. Used by tests without the RunPod SDK."""
    print(f"[MT3 serverless] payload_shape={_shape(event)}", flush=True)
    raw, filename = _find_audio(event)
    if not raw:
        raise ValueError("Missing input.audio_base64")
    try:
        audio_bytes = base64.b64decode(raw, validate=False)
    except Exception as exc:
        raise ValueError("input.audio_base64 is not valid base64") from exc
    if not audio_bytes:
        raise ValueError("input.audio_base64 is empty")

    name = filename or "recording.wav"
    suffix = Path(name).suffix.lower() or ".wav"
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


def handler(job: dict) -> dict:
    return transcribe_event(job)


def main() -> None:
    print(f"[MT3 serverless] warming {MODEL_NAME}", flush=True)
    get_model()
    print("[MT3 serverless] ready", flush=True)
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
