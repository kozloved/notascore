"""Parse RunPod Serverless job input without touching YourMT3.

RunPod HTTP /runsync body:

  {"input": {"audio_base64": "...", "filename": "clip.wav"}}

The handler then receives:

  {"id": "...", "input": {"audio_base64": "...", "filename": "clip.wav"}}

The RunPod web console wraps whatever you paste as `input`. If you paste a
body that already has `input`, audio sits at input.input.audio_base64.
"""

from __future__ import annotations

_AUDIO_KEYS = ("audio_base64", "audio", "file_base64", "wav_base64")


def job_input(job: object) -> dict:
    """Return the dict that actually holds audio_base64 / filename."""
    if not isinstance(job, dict):
        return {}
    current: dict = job
    for _ in range(4):
        if any(
            isinstance(current.get(key), str) and current.get(key).strip()
            for key in _AUDIO_KEYS
        ):
            return current
        inner = current.get("input")
        if isinstance(inner, dict):
            current = inner
            continue
        break
    return current if isinstance(current, dict) else {}


def audio_base64_from_job(job: object) -> tuple[str | None, str | None]:
    payload = job_input(job)
    raw = None
    for key in _AUDIO_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            raw = value.strip()
            break
    filename = payload.get("filename")
    if not isinstance(filename, str) or not filename.strip():
        filename = None
    return raw, filename
