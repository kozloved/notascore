"""Filesystem cache for Gemini analysis results."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from intelligence.config import GeminiConfig
from intelligence.prompts import ANALYSIS_VERSION, PROMPT_VERSION


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def cache_key(
    *,
    audio_hash: str,
    transcription_hash: str,
    model_name: str,
    analysis_version: str = ANALYSIS_VERSION,
    prompt_version: str = PROMPT_VERSION,
    extra: str = "",
) -> str:
    raw = "|".join(
        [
            audio_hash or "no-audio",
            transcription_hash,
            model_name,
            analysis_version,
            prompt_version,
            extra,
        ]
    )
    return _sha(raw)


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_json(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return _sha(blob)


class AnalysisCache:
    def __init__(self, cfg: GeminiConfig):
        self.cfg = cfg
        self.root = cfg.cache_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        stored_at = float(payload.get("stored_at") or 0.0)
        if stored_at and (time.time() - stored_at) > self.cfg.cache_ttl_seconds:
            path.unlink(missing_ok=True)
            return None
        return payload.get("value")

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        path.write_text(
            json.dumps(
                {"stored_at": time.time(), "value": value},
                ensure_ascii=True,
            ),
            encoding="utf-8",
        )
