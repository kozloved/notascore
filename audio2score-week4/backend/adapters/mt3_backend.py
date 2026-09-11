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
import re
import shlex
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from mir.midi_ingest import ingest_midi
from mir.types import NoteEvent
from modes import DEFAULT_MT3_MODEL, MT3_MODELS

DEFAULT_TIMEOUT_SECONDS = 600
_RUN_HTTP_TIMEOUT_SECONDS = 30
_STATUS_HTTP_TIMEOUT_SECONDS = 15
_POLL_INTERVAL_SECONDS = 2.0
_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_RUNPOD_FAIL_STATUSES = frozenset(
    {"FAILED", "CANCELLED", "CANCELED", "TIMED_OUT"}
)

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
    """Canonical RunPod URL ending in /runsync. Leave other URLs unchanged.

    Transcription actually uses /run + /status (see `_post_runpod_audio`).
    /runsync returns or times out around five minutes, which is how long a
    min-workers-0 boot takes, so waiting on it drops MIDI that RunPod still
    finishes.
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


def runpod_endpoint_root(url: str) -> str:
    """https://api.runpod.ai/v2/<id> from a run/runsync/status URL."""
    sync = normalize_mt3_endpoint(url)
    if sync.endswith("/runsync"):
        return sync[: -len("/runsync")]
    return sync.rstrip("/")


def runpod_async_url(url: str) -> str:
    """Queue a job with /run. Do not wait on /runsync (300s HTTP cap)."""
    if not is_runpod_endpoint(url):
        return url
    return runpod_endpoint_root(url) + "/run"


def runpod_status_url(url: str, job_id: str) -> str:
    return f"{runpod_endpoint_root(url)}/status/{job_id}"


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
    provider = mt3_provider(endpoint, command)
    timeout = _env_int("MT3_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    # Existing VPS env still has 300 from the /runsync era. Cold start often
    # takes ~5 minutes, so wait at least 10 minutes for RunPod.
    if provider == "runpod":
        timeout = max(timeout, 600)
    return {
        "endpoint": endpoint,
        "api_key": (os.getenv("MT3_API_KEY") or "").strip(),
        "command": command,
        "timeout": timeout,
        "model": _mt3_model_name(),
        "toolkit": "mt3-infer",
        "toolkit_version": "0.2.0",
        "provider": provider,
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


def _coerce_runpod_output(output: object) -> dict | None:
    """RunPod sometimes JSON-strings or list-wraps the handler return value."""
    if isinstance(output, dict):
        inner = output.get("output")
        if isinstance(inner, (dict, str, list)) and not output.get("midi_base64"):
            nested = _coerce_runpod_output(inner)
            if nested:
                return nested
        return output
    if isinstance(output, str):
        raw = output.strip()
        if raw[:1] not in "{[":
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return _coerce_runpod_output(parsed)
    if isinstance(output, list):
        for item in output:
            parsed = _coerce_runpod_output(item)
            if isinstance(parsed, dict):
                return parsed
    return None


def _midi_source_dicts(payload: object) -> list[dict]:
    sources: list[dict] = []
    if not isinstance(payload, dict):
        return sources
    output = _coerce_runpod_output(payload.get("output"))
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
        notes = ingest_midi(path, source_backend="mt3").notes
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
    if status in _RUNPOD_FAIL_STATUSES:
        extra = _safe_error_detail(str(payload.get("error") or status))
        raise _transcription_error(
            f"RunPod transcription service failed.{(' ' + extra) if extra else ''}"
        )
    if status in {"IN_QUEUE", "IN_PROGRESS"}:
        raise _transcription_error(
            "RunPod transcription service failed. Job is still queued."
        )

    error = payload.get("error")
    if error and status not in {"COMPLETED", ""}:
        raise _transcription_error(
            f"RunPod transcription service failed. {_safe_error_detail(str(error))}"
        )

    output = _coerce_runpod_output(payload.get("output"))
    if isinstance(output, dict):
        nested_error = output.get("error")
        if nested_error and not output.get("midi_base64"):
            raise _transcription_error(
                f"RunPod transcription service failed. {_safe_error_detail(str(nested_error))}"
            )
        if output.get("warmup") and not output.get("midi_base64"):
            raise _transcription_error(
                "RunPod worker skipped inference. Audio was not transcribed."
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
    if isinstance(payload, dict) and payload.get("warmup") and not payload.get("midi_base64"):
        raise _transcription_error(
            "RunPod worker skipped inference. Audio was not transcribed."
        )

    return _midi_from_runpod_payload(payload)


def _runpod_headers(api_key: str, content_type: bool = False) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _runpod_open_json(
    request: urllib.request.Request, timeout: int, wait_seconds: int
) -> dict:
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
                f"RunPod transcription timed out after {wait_seconds} seconds."
            ) from exc
        raise _transcription_error(
            f"RunPod transcription service failed. {_safe_error_detail(str(exc.reason or exc))}"
        ) from exc
    except TimeoutError as exc:
        raise _transcription_error(
            f"RunPod transcription timed out after {wait_seconds} seconds."
        ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _transcription_error("RunPod returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise _transcription_error("RunPod returned invalid JSON.")
    return payload


def _runpod_job_id(payload: dict) -> str:
    raw = payload.get("id") or payload.get("jobId") or payload.get("job_id")
    job_id = str(raw or "").strip()
    if not job_id or not _JOB_ID_RE.fullmatch(job_id):
        raise _transcription_error("RunPod did not return a job id.")
    return job_id


def _runpod_payload_ready(payload: dict) -> bool:
    status = str(payload.get("status") or "").upper()
    output = _coerce_runpod_output(payload.get("output"))
    has_midi = isinstance(payload.get("midi_base64"), str) or (
        isinstance(output, dict) and isinstance(output.get("midi_base64"), str)
    )
    has_error = bool(
        payload.get("error")
        or (isinstance(output, dict) and output.get("error"))
        or (isinstance(output, dict) and output.get("warmup") and not has_midi)
    )
    if status in _RUNPOD_FAIL_STATUSES:
        return True
    if status in {"IN_QUEUE", "IN_PROGRESS"}:
        return False
    if status == "COMPLETED":
        # Handler errors come back as COMPLETED + output.error, not FAILED.
        return has_midi or has_error or output is not None
    return has_midi or isinstance(output, dict)


def _poll_runpod_job(
    url: str, job_id: str, api_key: str, wait_seconds: int, deadline: float
) -> dict:
    status_url = runpod_status_url(url, job_id)
    last_status = ""
    while True:
        request = urllib.request.Request(
            status_url,
            headers=_runpod_headers(api_key),
            method="GET",
        )
        payload = _runpod_open_json(
            request, _STATUS_HTTP_TIMEOUT_SECONDS, wait_seconds
        )
        status = str(payload.get("status") or "").upper()
        delay = payload.get("delayTime")
        if status != last_status:
            extra = f" delayTime={delay}" if delay is not None else ""
            print(f"[MT3] runpod job={job_id} status={status}{extra}", flush=True)
            last_status = status
        if _runpod_payload_ready(payload):
            return payload
        if status in _RUNPOD_FAIL_STATUSES:
            extra = _safe_error_detail(str(payload.get("error") or status))
            raise _transcription_error(
                f"RunPod transcription service failed.{(' ' + extra) if extra else ''}"
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _transcription_error(
                f"RunPod transcription timed out after {wait_seconds} seconds."
            )
        time.sleep(min(_POLL_INTERVAL_SECONDS, remaining))


def _post_runpod_audio(
    url: str, audio_path: Path, api_key: str, timeout: int
) -> bytes:
    if not api_key:
        raise _transcription_error("RunPod authentication failed.")

    wait_seconds = max(1, int(timeout))
    deadline = time.monotonic() + wait_seconds
    endpoint = runpod_async_url(url)
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
    print("[MT3] provider=runpod")
    print(f"[MT3] endpoint={endpoint}")
    print(f"[MT3] filename={filename}")
    print("[MT3] request started")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers=_runpod_headers(api_key, content_type=True),
        method="POST",
    )
    submit_timeout = min(wait_seconds, _RUN_HTTP_TIMEOUT_SECONDS)
    payload = _runpod_open_json(request, submit_timeout, wait_seconds)

    if not _runpod_payload_ready(payload):
        status = str(payload.get("status") or "").upper()
        if status in _RUNPOD_FAIL_STATUSES:
            extra = _safe_error_detail(str(payload.get("error") or status))
            raise _transcription_error(
                f"RunPod transcription service failed.{(' ' + extra) if extra else ''}"
            )
        job_id = _runpod_job_id(payload)
        print(f"[MT3] runpod job={job_id} queued", flush=True)
        payload = _poll_runpod_job(url, job_id, api_key, wait_seconds, deadline)

    print("[MT3] response received")
    midi_bytes = _parse_runpod_body(json.dumps(payload).encode("utf-8"))
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

    def __init__(self):
        self.last_midi_bytes = None
        self.last_performance = None

    def _decode(self, data):
        # Retain the response, including controllers and metadata, before any
        # cleaner or score interpretation gets a mutable note copy.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mt3.mid"
            path.write_bytes(data)
            ingested = ingest_midi(path, source_backend="mt3")
        self.last_midi_bytes = bytes(data)
        self.last_performance = ingested.performance
        return ingested.notes

    def transcribe_notes(self, audio_path: str | Path) -> list[NoteEvent]:
        self.last_midi_bytes = None
        self.last_performance = None
        audio_path = Path(audio_path)
        settings = mt3_settings()
        endpoint = settings["endpoint"]
        command = settings["command"]
        timeout = max(1, int(settings["timeout"]))

        if endpoint:
            shown = (
                runpod_async_url(endpoint)
                if settings["provider"] == "runpod"
                else endpoint
            )
            print(f"[MT3] endpoint={shown} timeout={timeout}s")
            midi_bytes = _post_audio(
                endpoint, audio_path, settings["api_key"], timeout
            )
            return self._decode(midi_bytes)

        if command:
            print(f"[MT3] command timeout={timeout}s")
            midi_bytes = _run_command(audio_path, command, timeout)
            return self._decode(midi_bytes)

        raise _transcription_error(_POLYPHONIC_UNCONFIGURED)
