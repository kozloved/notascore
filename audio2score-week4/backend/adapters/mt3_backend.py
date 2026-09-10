"""Polyphonic-mode MT3 adapter — remote GPU HTTP or a local transcribe command.

Both paths must return MIDI. Notes then follow the same cleaner → CMR →
grand-staff path as Solo (Basic Pitch). This process does not run Magenta
weights.

Point MT3_ENDPOINT at:
  - a RunPod Serverless YourMT3 worker (JSON input.audio_base64 → midi_base64)
  - an mt3-infer HTTP worker (multipart file → MIDI bytes or midi_base64 JSON)
  - or set MT3_TRANSCRIBE_COMMAND to a command that writes MIDI.

The rest of NotaScore talks only to MT3Backend. Provider details stay here.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import shlex
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from mir.midi_ingest import ingest_midi
from mir.types import NoteEvent
from modes import DEFAULT_MT3_MODEL, MT3_MODELS

DEFAULT_TIMEOUT_SECONDS = 300

_POLYPHONIC_UNCONFIGURED = (
    "Polyphonic mode (MT3) is not configured. "
    "Set MT3_ENDPOINT or MT3_TRANSCRIBE_COMMAND."
)

_RUNPOD_ACTIONS = frozenset(
    {"runsync", "run", "health", "stream", "status", "cancel"}
)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(raw)


def _mt3_model_name() -> str:
    raw = (os.getenv("MT3_MODEL") or DEFAULT_MT3_MODEL).strip().lower()
    if raw in MT3_MODELS:
        return raw
    return DEFAULT_MT3_MODEL


def is_runpod_endpoint(url: str) -> bool:
    """True for RunPod Serverless v2 URLs (api.runpod.ai), not proxy pods."""
    host = urlparse((url or "").strip()).netloc.split(":")[0].lower()
    return host == "api.runpod.ai" or host.endswith(".api.runpod.ai")


def normalize_mt3_endpoint(url: str) -> str:
    """Use /runsync for RunPod Serverless. Leave other URLs unchanged.

    Accepts either:
      https://api.runpod.ai/v2/<id>
      https://api.runpod.ai/v2/<id>/runsync
    A bare /run is rewritten to /runsync so the existing job waits for MIDI.
    """
    raw = (url or "").strip()
    if not raw or not is_runpod_endpoint(raw):
        return raw
    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[0] == "v2" and parts[2] in _RUNPOD_ACTIONS:
        if parts[2] == "run":
            parts[2] = "runsync"
        path = "/" + "/".join(parts)
    elif len(parts) >= 2 and parts[0] == "v2":
        path = "/" + "/".join(parts[:2]) + "/runsync"
    return urlunparse(parsed._replace(path=path, query=""))


def mt3_provider(endpoint: str = "", command: str = "") -> str:
    if is_runpod_endpoint(endpoint):
        return "runpod"
    if (endpoint or "").strip():
        return "http"
    if (command or "").strip():
        return "command"
    return "none"


def mt3_settings() -> dict:
    endpoint = (os.getenv("MT3_ENDPOINT") or "").strip()
    command = (os.getenv("MT3_TRANSCRIBE_COMMAND") or "").strip()
    return {
        "endpoint": endpoint,
        "api_key": (os.getenv("MT3_API_KEY") or "").strip(),
        "command": command,
        "timeout": _env_int("MT3_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        "model": _mt3_model_name(),
        "toolkit": "mt3-infer",
        "toolkit_version": "0.2.0",
        "provider": mt3_provider(endpoint, command),
    }


def mt3_available() -> bool:
    settings = mt3_settings()
    return bool(settings["endpoint"] or settings["command"])


def mt3_status() -> dict:
    settings = mt3_settings()
    return {
        "available": bool(settings["endpoint"] or settings["command"]),
        "endpoint_configured": bool(settings["endpoint"]),
        "command_configured": bool(settings["command"]),
        "timeout_seconds": settings["timeout"],
        "model": settings["model"],
        "toolkit": settings["toolkit"],
        "toolkit_version": settings["toolkit_version"],
        "supported_models": list(MT3_MODELS),
        "provider": settings["provider"],
    }


def _transcription_error(message: str):
    from transcription import TranscriptionError

    return TranscriptionError(message)


def _looks_like_midi(data: bytes) -> bool:
    return data[:4] == b"MThd"


def _safe_error_detail(text: str, limit: int = 240) -> str:
    """Keep a short upstream snippet and drop anything that looks like a secret."""
    cleaned = " ".join((text or "").split())
    lowered = cleaned.lower()
    for marker in ("bearer ", "authorization:", "api_key", "api-key", "x-api-key"):
        idx = lowered.find(marker)
        if idx >= 0:
            cleaned = cleaned[:idx].rstrip(" :")
            lowered = cleaned.lower()
    cleaned = cleaned.replace("\x00", "")
    return cleaned[:limit]


def _midi_from_json(payload: object) -> bytes | None:
    if not isinstance(payload, dict):
        return None
    for key in ("midi_base64", "midi", "data"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        raw = value.strip()
        try:
            decoded = base64.b64decode(raw, validate=False)
        except Exception:
            continue
        if _looks_like_midi(decoded):
            return decoded
    return None


def _midi_source_dicts(payload: object) -> list[dict]:
    sources: list[dict] = []
    if not isinstance(payload, dict):
        return sources
    output = payload.get("output")
    if isinstance(output, dict):
        sources.append(output)
    sources.append(payload)
    return sources


def _midi_from_runpod_payload(payload: object) -> bytes:
    sources = _midi_source_dicts(payload)
    saw_midi_field = False
    for source in sources:
        value = source.get("midi_base64")
        if not isinstance(value, str) or not value.strip():
            continue
        saw_midi_field = True
        try:
            decoded = base64.b64decode(value.strip(), validate=False)
        except Exception as exc:
            raise _transcription_error("RunPod returned invalid MIDI.") from exc
        if _looks_like_midi(decoded):
            return decoded
        raise _transcription_error("RunPod returned invalid MIDI.")
    if saw_midi_field:
        raise _transcription_error("RunPod returned invalid MIDI.")
    raise _transcription_error("RunPod response did not contain midi_base64.")


def _parse_mt3_response(body: bytes, content_type: str) -> bytes:
    ctype = (content_type or "").lower()
    if "json" in ctype:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _transcription_error(
                "Polyphonic (MT3) endpoint returned invalid JSON."
            ) from exc
        midi = _midi_from_json(payload)
        if midi is None:
            raise _transcription_error(
                "Polyphonic (MT3) JSON response did not include midi_base64."
            )
        return midi
    if _looks_like_midi(body):
        return body
    # Some servers omit Content-Type; try JSON then fail.
    if body.lstrip()[:1] in (b"{", b"["):
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _transcription_error(
                "Polyphonic (MT3) endpoint returned a non-MIDI body."
            ) from exc
        midi = _midi_from_json(payload)
        if midi is not None:
            return midi
    raise _transcription_error(
        "Polyphonic (MT3) endpoint did not return MIDI bytes or midi_base64 JSON."
    )


def _notes_from_midi_bytes(data: bytes) -> list[NoteEvent]:
    if not _looks_like_midi(data):
        raise _transcription_error("Polyphonic (MT3) returned invalid MIDI.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mt3.mid"
        path.write_bytes(data)
        notes = ingest_midi(path).notes
    if not notes:
        raise _transcription_error("Polyphonic (MT3) returned a MIDI file with no notes.")
    return notes


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    return "timed out" in str(exc).lower() or "timeout" in str(reason).lower()


def _runpod_http_error(code: int, detail: str) -> Exception:
    if code in (401, 403):
        message = "RunPod authentication failed."
    elif code == 404:
        message = "RunPod endpoint not found."
    elif code == 429:
        message = "RunPod rate limit reached."
    elif code >= 500:
        message = "RunPod transcription service failed."
    else:
        message = "RunPod transcription service failed."
    extra = _safe_error_detail(detail)
    if extra:
        message = f"{message} {extra}"
    return _transcription_error(message)


def _parse_runpod_body(body: bytes) -> bytes:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _transcription_error("RunPod returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise _transcription_error("RunPod returned invalid JSON.")

    status = str(payload.get("status") or "").upper()
    if status in {"FAILED", "CANCELLED", "CANCELED", "TIMED_OUT"}:
        extra = _safe_error_detail(str(payload.get("error") or status))
        raise _transcription_error(
            f"RunPod transcription service failed.{(' ' + extra) if extra else ''}"
        )
    if status in {"IN_QUEUE", "IN_PROGRESS"}:
        raise _transcription_error("RunPod transcription service failed. Job did not finish in /runsync.")

    error = payload.get("error")
    if error and status not in {"COMPLETED", ""}:
        raise _transcription_error(
            f"RunPod transcription service failed. {_safe_error_detail(str(error))}"
        )

    output = payload.get("output")
    if isinstance(output, dict):
        nested_error = output.get("error")
        if nested_error and not output.get("midi_base64"):
            raise _transcription_error(
                f"RunPod transcription service failed. {_safe_error_detail(str(nested_error))}"
            )
        timing = output.get("timing")
        if isinstance(timing, dict):
            inference = timing.get("inference_seconds")
            total = timing.get("total_seconds")
            if inference is not None or total is not None:
                print(
                    f"[MT3] runpod_timing inference_seconds={inference} "
                    f"total_seconds={total}"
                )

    return _midi_from_runpod_payload(payload)


def _post_runpod_audio(
    url: str, audio_path: Path, api_key: str, timeout: int
) -> bytes:
    if not api_key:
        raise _transcription_error("RunPod authentication failed.")

    endpoint = normalize_mt3_endpoint(url)
    filename = audio_path.name
    audio_bytes = audio_path.read_bytes()
    body = json.dumps(
        {
            "input": {
                "audio_base64": base64.b64encode(audio_bytes).decode("ascii"),
                "filename": filename,
            }
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    print(f"[MT3] provider=runpod")
    print(f"[MT3] endpoint={endpoint}")
    print(f"[MT3] filename={filename}")
    print("[MT3] request started")
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc.reason or exc)
        raise _runpod_http_error(int(exc.code), detail) from exc
    except urllib.error.URLError as exc:
        if _is_timeout_error(exc):
            raise _transcription_error(
                f"RunPod transcription timed out after {timeout} seconds."
            ) from exc
        raise _transcription_error(
            f"RunPod transcription service failed. {_safe_error_detail(str(exc.reason or exc))}"
        ) from exc
    except TimeoutError as exc:
        raise _transcription_error(
            f"RunPod transcription timed out after {timeout} seconds."
        ) from exc

    print("[MT3] response received")
    midi_bytes = _parse_runpod_body(raw)
    print(f"[MT3] midi_bytes={len(midi_bytes)}")
    print("[MT3] complete")
    return midi_bytes


def _post_multipart_audio(
    url: str, audio_path: Path, api_key: str, timeout: int
) -> bytes:
    filename = audio_path.name
    payload = audio_path.read_bytes()
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}--\r\n".encode("utf-8")
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "audio/midi, application/octet-stream, application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    print(f"[MT3] provider=http")
    print(f"[MT3] endpoint={url}")
    print(f"[MT3] filename={filename}")
    print("[MT3] request started")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            midi_bytes = _parse_mt3_response(
                response.read(),
                response.headers.get("Content-Type", ""),
            )
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            detail = str(exc)
        raise _transcription_error(
            f"Polyphonic (MT3) endpoint returned HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        if _is_timeout_error(exc):
            raise _transcription_error(
                f"Polyphonic (MT3) endpoint timed out after {timeout}s."
            ) from exc
        raise _transcription_error(
            f"Polyphonic (MT3) endpoint is unreachable: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise _transcription_error(
            f"Polyphonic (MT3) endpoint timed out after {timeout}s."
        ) from exc
    print("[MT3] response received")
    print(f"[MT3] midi_bytes={len(midi_bytes)}")
    print("[MT3] complete")
    return midi_bytes


def _post_audio(url: str, audio_path: Path, api_key: str, timeout: int) -> bytes:
    if is_runpod_endpoint(url):
        return _post_runpod_audio(url, audio_path, api_key, timeout)
    return _post_multipart_audio(url, audio_path, api_key, timeout)


def _run_command(audio_path: Path, command: str, timeout: int) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        midi_out = Path(tmp) / "mt3.mid"
        template = command
        filled = template.replace("{input}", str(audio_path)).replace(
            "{output}", str(midi_out)
        )
        argv = shlex.split(filled)
        if "{input}" not in template and "{output}" not in template:
            argv.extend([str(audio_path), str(midi_out)])
        print("[MT3] provider=command")
        print(f"[MT3] filename={audio_path.name}")
        print("[MT3] request started")
        try:
            completed = subprocess.run(
                argv,
                timeout=timeout,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise _transcription_error(
                f"Polyphonic (MT3) command timed out after {timeout}s."
            ) from exc
        except OSError as exc:
            raise _transcription_error(
                f"Polyphonic (MT3) command failed to start: {exc}"
            ) from exc
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "").strip()[:400]
            raise _transcription_error(
                f"Polyphonic (MT3) command exited {completed.returncode}"
                + (f": {err}" if err else ".")
            )
        if not midi_out.exists():
            raise _transcription_error(
                "Polyphonic (MT3) command did not write the output MIDI file."
            )
        midi_bytes = midi_out.read_bytes()
        print("[MT3] response received")
        print(f"[MT3] midi_bytes={len(midi_bytes)}")
        print("[MT3] complete")
        return midi_bytes


class MT3Backend:
    name = "mt3"

    def transcribe_notes(self, audio_path: str | Path) -> list[NoteEvent]:
        audio_path = Path(audio_path)
        settings = mt3_settings()
        endpoint = settings["endpoint"]
        command = settings["command"]
        timeout = max(1, int(settings["timeout"]))

        if endpoint:
            print(
                f"[MT3] endpoint={normalize_mt3_endpoint(endpoint)} "
                f"timeout={timeout}s"
            )
            midi_bytes = _post_audio(
                endpoint, audio_path, settings["api_key"], timeout
            )
            return _notes_from_midi_bytes(midi_bytes)

        if command:
            print(f"[MT3] command timeout={timeout}s")
            midi_bytes = _run_command(audio_path, command, timeout)
            return _notes_from_midi_bytes(midi_bytes)

        raise _transcription_error(_POLYPHONIC_UNCONFIGURED)
