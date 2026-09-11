"""HTTP stem-separation provider. Runs on an external worker, never in the API process."""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from engine.flags import separation_endpoint
from separation.base import ALLOWED_STEMS, SeparationResult, StemAudio

DEFAULT_TIMEOUT_SECONDS = 600
_ALLOWED = frozenset(ALLOWED_STEMS)


class HttpSeparator:
    """POST audio to SEPARATION_ENDPOINT. Never invents stems the worker omitted."""

    name = "http"

    def __init__(self, endpoint: str | None = None, timeout: int | None = None):
        self.endpoint = (endpoint if endpoint is not None else separation_endpoint()).rstrip("/")
        if timeout is None:
            raw = os.getenv("SEPARATION_TIMEOUT", "")
            timeout = int(raw) if str(raw).strip() else DEFAULT_TIMEOUT_SECONDS
        self.timeout = max(1, int(timeout))
        self.last_request_count = 0
        self.last_error = ""

    def separate(
        self,
        audio_path: str,
        *,
        job_id: str = "",
        output_dir: str | Path | None = None,
        requested_stems: list[str] | None = None,
    ) -> SeparationResult:
        started = time.perf_counter()
        requested = [
            s for s in (requested_stems or list(ALLOWED_STEMS)) if s in _ALLOWED
        ]
        if not self.endpoint:
            return SeparationResult(
                stems=[],
                model=self.name,
                skipped=True,
                skip_reason="SEPARATION_ENDPOINT is unset; HTTP separator idle.",
                requested_backend=self.name,
                actual_backend="",
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )

        audio_path = Path(audio_path)
        dest_dir = Path(output_dir) if output_dir else audio_path.parent
        dest_dir.mkdir(parents=True, exist_ok=True)
        body = json.dumps(
            {
                "audio_base64": base64.b64encode(audio_path.read_bytes()).decode("ascii"),
                "filename": audio_path.name,
                "job_id": job_id,
                "requested_stems": requested,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        api_key = os.getenv("SEPARATION_API_KEY", "").strip()
        if api_key:
            request.add_header("Authorization", f"Bearer {api_key}")
            request.add_header("X-API-Key", api_key)

        self.last_request_count += 1
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:400]
            except Exception:
                detail = str(exc)
            return self._failed(
                started,
                f"Separation endpoint returned HTTP {exc.code}: {detail or exc.reason}",
            )
        except urllib.error.URLError as exc:
            return self._failed(started, f"Separation endpoint unreachable: {exc.reason}")
        except TimeoutError:
            return self._failed(
                started, f"Separation endpoint timed out after {self.timeout}s."
            )
        except json.JSONDecodeError as exc:
            return self._failed(started, f"Separation endpoint returned invalid JSON: {exc}")

        if not isinstance(payload, dict):
            return self._failed(started, "Separation endpoint returned a non-object JSON body.")

        model = str(payload.get("model") or self.name)
        model_version = str(payload.get("model_version") or payload.get("version") or "")
        raw_stems = payload.get("stems") or {}
        warnings = [str(w) for w in (payload.get("warnings") or [])]
        stems: list[StemAudio] = []

        items: list[tuple[str, dict]] = []
        if isinstance(raw_stems, dict):
            items = [(str(k), v if isinstance(v, dict) else {"audio_base64": v}) for k, v in raw_stems.items()]
        elif isinstance(raw_stems, list):
            for row in raw_stems:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("stem_id") or row.get("label") or "")
                items.append((label, row))

        for label, row in items:
            stem_id = str(row.get("stem_id") or label).strip().lower()
            if stem_id not in _ALLOWED:
                warnings.append(f"ignored unsupported stem {stem_id!r}")
                continue
            audio_b64 = row.get("audio_base64") or row.get("audio") or ""
            if not audio_b64:
                warnings.append(f"stem {stem_id} omitted (no audio)")
                continue
            try:
                audio_bytes = base64.b64decode(audio_b64)
            except Exception:
                warnings.append(f"stem {stem_id} omitted (invalid audio_base64)")
                continue
            ext = str(row.get("ext") or "wav").lstrip(".")
            prefix = f"{job_id}.stem." if job_id else "stem."
            out_path = dest_dir / f"{prefix}{stem_id}.{ext}"
            out_path.write_bytes(audio_bytes)
            conf = row.get("confidence")
            stems.append(
                StemAudio(
                    stem_id=stem_id,
                    instrument=stem_id,
                    path=str(out_path),
                    confidence=float(conf) if conf is not None and conf != "" else None,
                    model=model,
                    model_version=model_version,
                )
            )

        duration_ms = (time.perf_counter() - started) * 1000.0
        return SeparationResult(
            stems=stems,
            model=model,
            model_version=model_version,
            warnings=warnings,
            skipped=False,
            requested_backend=self.name,
            actual_backend=model,
            duration_ms=duration_ms,
        )

    def _failed(self, started: float, error: str) -> SeparationResult:
        self.last_error = error
        return SeparationResult(
            stems=[],
            model=self.name,
            skipped=False,
            skip_reason="",
            warnings=[error],
            error=error,
            requested_backend=self.name,
            actual_backend="",
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )
