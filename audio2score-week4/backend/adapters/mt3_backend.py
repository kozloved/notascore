"""Quality-mode MT3 adapter — remote GPU HTTP or a local transcribe command.

Both paths must return MIDI. Notes then follow the same cleaner → CMR →
grand-staff path as Fast (Basic Pitch). This process does not run Magenta
weights; point MT3_ENDPOINT at an MR-MT3 GPU worker, or
MT3_TRANSCRIBE_COMMAND at a command that writes MIDI.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import shlex
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from mir.midi_ingest import ingest_midi
from mir.types import NoteEvent

DEFAULT_TIMEOUT_SECONDS = 300

_QUALITY_UNCONFIGURED = (
    "Quality mode (MT3) is not configured. "
    "Set MT3_ENDPOINT or MT3_TRANSCRIBE_COMMAND."
)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return int(raw)


def mt3_settings() -> dict:
    return {
        "endpoint": (os.getenv("MT3_ENDPOINT") or "").strip(),
        "api_key": (os.getenv("MT3_API_KEY") or "").strip(),
        "command": (os.getenv("MT3_TRANSCRIBE_COMMAND") or "").strip(),
        "timeout": _env_int("MT3_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
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
    }


def _transcription_error(message: str):
    from transcription import TranscriptionError

    return TranscriptionError(message)


def _looks_like_midi(data: bytes) -> bool:
    return data[:4] == b"MThd"


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


def _parse_mt3_response(body: bytes, content_type: str) -> bytes:
    ctype = (content_type or "").lower()
    if "json" in ctype:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _transcription_error(
                "Quality (MT3) endpoint returned invalid JSON."
            ) from exc
        midi = _midi_from_json(payload)
        if midi is None:
            raise _transcription_error(
                "Quality (MT3) JSON response did not include midi_base64."
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
                "Quality (MT3) endpoint returned a non-MIDI body."
            ) from exc
        midi = _midi_from_json(payload)
        if midi is not None:
            return midi
    raise _transcription_error(
        "Quality (MT3) endpoint did not return MIDI bytes or midi_base64 JSON."
    )


def _notes_from_midi_bytes(data: bytes) -> list[NoteEvent]:
    if not _looks_like_midi(data):
        raise _transcription_error("Quality (MT3) returned invalid MIDI.")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mt3.mid"
        path.write_bytes(data)
        notes = ingest_midi(path).notes
    if not notes:
        raise _transcription_error("Quality (MT3) returned a MIDI file with no notes.")
    return notes


def _post_audio(url: str, audio_path: Path, api_key: str, timeout: int) -> bytes:
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
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _parse_mt3_response(
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
            f"Quality (MT3) endpoint returned HTTP {exc.code}: {detail or exc.reason}"
        ) from exc
    except urllib.error.URLError as exc:
        raise _transcription_error(
            f"Quality (MT3) endpoint is unreachable: {exc.reason}"
        ) from exc
    except TimeoutError as exc:
        raise _transcription_error(
            f"Quality (MT3) endpoint timed out after {timeout}s."
        ) from exc


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
                f"Quality (MT3) command timed out after {timeout}s."
            ) from exc
        except OSError as exc:
            raise _transcription_error(
                f"Quality (MT3) command failed to start: {exc}"
            ) from exc
        if completed.returncode != 0:
            err = (completed.stderr or completed.stdout or "").strip()[:400]
            raise _transcription_error(
                f"Quality (MT3) command exited {completed.returncode}"
                + (f": {err}" if err else ".")
            )
        if not midi_out.exists():
            raise _transcription_error(
                "Quality (MT3) command did not write the output MIDI file."
            )
        return midi_out.read_bytes()


class MT3Backend:
    name = "mt3"

    def transcribe_notes(self, audio_path: str | Path) -> list[NoteEvent]:
        audio_path = Path(audio_path)
        settings = mt3_settings()
        endpoint = settings["endpoint"]
        command = settings["command"]
        timeout = max(1, int(settings["timeout"]))

        if endpoint:
            print(f"[MT3] endpoint={endpoint} timeout={timeout}s")
            midi_bytes = _post_audio(
                endpoint, audio_path, settings["api_key"], timeout
            )
            return _notes_from_midi_bytes(midi_bytes)

        if command:
            print(f"[MT3] command timeout={timeout}s")
            midi_bytes = _run_command(audio_path, command, timeout)
            return _notes_from_midi_bytes(midi_bytes)

        raise _transcription_error(_QUALITY_UNCONFIGURED)
