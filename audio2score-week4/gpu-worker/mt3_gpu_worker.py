"""MR-MT3 HTTP worker for NotaScore Quality mode.

Run this on a GPU box (RTX 4000 Ada 20GB is enough). NotaScore POSTs audio
here and expects MIDI back.

  POST /transcribe   multipart field `file`
  GET  /health

  MT3_ENDPOINT=https://<pod-host>:8090/transcribe
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import Response

MODEL_NAME = os.getenv("MT3_MODEL", "mr_mt3")
API_KEY = (os.getenv("MT3_API_KEY") or "").strip()

app = FastAPI(title="NotaScore MT3 worker")
_model = None


def _authorized(
    authorization: str | None,
    x_api_key: str | None,
) -> bool:
    if not API_KEY:
        return True
    token = (x_api_key or "").strip()
    if authorization:
        scheme, _, rest = authorization.partition(" ")
        if scheme.lower() == "bearer":
            token = rest.strip()
    return token == API_KEY


def get_model():
    """Load MR-MT3 once per process."""
    global _model
    if _model is not None:
        return _model
    try:
        import torch
        from mt3_infer import load_model
    except ImportError as exc:
        raise RuntimeError(
            "mt3-infer (and CUDA torch) must be installed on this GPU box. "
            "See gpu-worker/README.md."
        ) from exc
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[MT3 worker] loading {MODEL_NAME} on {device}", flush=True)
    _model = load_model(MODEL_NAME, device=device)
    return _model


def midi_to_bytes(midi) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as tmp:
        path = tmp.name
    try:
        if hasattr(midi, "save"):
            midi.save(path)
        elif hasattr(midi, "write"):
            midi.write(path)
        else:
            raise TypeError(f"Unsupported MIDI object: {type(midi)!r}")
        data = Path(path).read_bytes()
    finally:
        Path(path).unlink(missing_ok=True)
    if data[:4] != b"MThd":
        raise RuntimeError("Model did not write a MIDI file")
    return data


def transcribe_audio_path(audio_path: str) -> bytes:
    import librosa

    y, sr = librosa.load(audio_path, sr=16000, mono=True)
    if y.size == 0:
        raise ValueError("Audio file is empty")
    midi = get_model().transcribe(y, sr=sr)
    return midi_to_bytes(midi)


@app.get("/")
@app.get("/health")
def health():
    payload = {
        "status": "ok",
        "model": MODEL_NAME,
        "loaded": _model is not None,
        "cuda": False,
        "device_name": "unknown",
    }
    try:
        import torch

        payload["cuda"] = bool(torch.cuda.is_available())
        if payload["cuda"]:
            payload["device_name"] = torch.cuda.get_device_name(0)
            payload["vram_gb"] = round(
                torch.cuda.get_device_properties(0).total_memory / (1024**3), 1
            )
        else:
            payload["device_name"] = "cpu"
    except ImportError:
        payload["device_name"] = "torch-not-installed"
    return payload


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
):
    if not _authorized(authorization, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid API key")

    suffix = Path(file.filename or "audio.wav").suffix.lower() or ".wav"
    if suffix not in {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}:
        suffix = ".wav"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        audio_path = tmp.name
    try:
        midi_bytes = transcribe_audio_path(audio_path)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail=f"Transcription failed: {exc}"
        ) from exc
    finally:
        Path(audio_path).unlink(missing_ok=True)

    return Response(content=midi_bytes, media_type="audio/midi")
