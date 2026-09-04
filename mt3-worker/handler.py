"""RunPod Serverless handler for NotaScore's YourMT3 worker.

The RunPod console wraps pasted JSON as `input`. NotaScore /runsync also
sends `{"input": {...}}`. This handler accepts both, including a double wrap.

YourMT3 is loaded once at process start. This file does not clean, quantize,
or otherwise post-process MIDI.
"""

from __future__ import annotations

import base64
import os
import tempfile
import time
from pathlib import Path

import runpod
import soundfile as sf

from gpu_compat import refuse_unsupported_cuda
from payload import audio_base64_from_job

print("[MT3] worker boot: importing YourMT3...")
_model_load_started = time.perf_counter()

MODEL_NAME = os.getenv("MODEL_NAME", "yourmt3")
DEVICE = os.getenv("MT3_DEVICE", "cuda")
refuse_unsupported_cuda(DEVICE)

from mt3_infer import load_model  # noqa: E402

MODEL = load_model(MODEL_NAME, device=DEVICE, auto_download=False)
MODEL_LOAD_SECONDS = time.perf_counter() - _model_load_started

print(
    f"[MT3] model ready model={MODEL_NAME} device={DEVICE} "
    f"load_seconds={MODEL_LOAD_SECONDS:.2f}"
)


def _decode_audio(job: dict, workdir: Path) -> Path:
    encoded, filename_hint = audio_base64_from_job(job)
    if not encoded:
        raise ValueError("Missing input.audio_base64")
    if encoded.startswith("<") and encoded.endswith(">"):
        raise ValueError(
            "audio_base64 is still the example placeholder. "
            "Paste real base64 from a .wav file."
        )

    filename = filename_hint or "audio.wav"
    filename = Path(filename).name
    if not Path(filename).suffix:
        filename += ".wav"

    try:
        raw = base64.b64decode(encoded, validate=False)
    except Exception as exc:
        raise ValueError("input.audio_base64 is not valid base64") from exc

    if not raw:
        raise ValueError("Decoded audio is empty")

    path = workdir / filename
    path.write_bytes(raw)
    return path


def handler(job: dict):
    try:
        return _transcribe_job(job)
    except Exception as exc:
        # Returning an error payload keeps the worker process alive.
        # Raising makes RunPod mark the endpoint Unhealthy.
        print(f"[MT3] handler error {type(exc).__name__}: {exc}", flush=True)
        return {"error": str(exc)}


def _transcribe_job(job: dict):
    started = time.perf_counter()
    if not isinstance(job, dict):
        job = {}

    with tempfile.TemporaryDirectory(prefix="notascore-mt3-") as tmp:
        audio_path = _decode_audio(job, Path(tmp))
        print(f"[MT3] job={job.get('id', 'unknown')} audio={audio_path.name}")

        audio, sample_rate = sf.read(str(audio_path), always_2d=False)
        if getattr(audio, "ndim", 1) > 1:
            # YourMT3 expects a mono waveform. Average channels without changing
            # the model itself or applying any NotaScore post-processing.
            audio = audio.mean(axis=1)

        print(
            f"[MT3] decoded sample_rate={sample_rate} "
            f"samples={len(audio)}"
        )

        inference_started = time.perf_counter()
        midi = MODEL.transcribe(audio, sr=int(sample_rate))
        inference_seconds = time.perf_counter() - inference_started

        midi_path = Path(tmp) / "output.mid"
        midi.save(str(midi_path))
        midi_bytes = midi_path.read_bytes()

    total_seconds = time.perf_counter() - started
    print(
        f"[MT3] complete inference_seconds={inference_seconds:.2f} "
        f"total_seconds={total_seconds:.2f} bytes={len(midi_bytes)}"
    )

    return {
        "midi_base64": base64.b64encode(midi_bytes).decode("ascii"),
        "model": MODEL_NAME,
        "timing": {
            "model_load_seconds": round(MODEL_LOAD_SECONDS, 3),
            "inference_seconds": round(inference_seconds, 3),
            "total_seconds": round(total_seconds, 3),
        },
    }


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
