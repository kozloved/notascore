"""Gemini generateContent adapter (stdlib HTTP, no SDK required)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from intelligence.config import GeminiConfig
from intelligence.prompts import SYSTEM_PROMPT, USER_TASK_FULL, USER_TASK_REGIONS
from intelligence.schemas import GeminiAnalysis, MusicalAnalysisPacket

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_TASK_HINTS = {
    "full": USER_TASK_FULL,
    "regions": USER_TASK_REGIONS,
    "instruments": "Focus on instrumentation. Return instrument_analysis and related corrections.",
    "structure": "Focus on sections, phrases, and repetitions.",
    "meter": "Focus on time signature and meter changes.",
    "tempo": "Focus on global tempo and tempo changes.",
    "phrases": "Focus on phrase boundaries.",
    "polyphony": "Focus on overlapping voices and density.",
    "validate": "Validate the transcription against the audio; propose only high-confidence corrections.",
}


class GeminiProvider:
    name = "gemini"

    def __init__(self, cfg: GeminiConfig, opener=None):
        self.cfg = cfg
        self._opener = opener or urllib.request.urlopen

    def analyse(
        self,
        packet: MusicalAnalysisPacket,
        *,
        model: str,
        audio_bytes: bytes | None,
        audio_mime: str,
        task: str,
    ) -> tuple[GeminiAnalysis, dict]:
        body = self._request_body(packet, audio_bytes, audio_mime, task)
        url = GEMINI_ENDPOINT.format(model=model)
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.cfg.api_key,
            },
        )
        try:
            with self._opener(request, timeout=self.cfg.timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise RuntimeError(f"Gemini request failed: {exc}") from exc

        text = _extract_text(raw)
        parsed = _parse_json_object(text)
        analysis = GeminiAnalysis.from_dict(parsed, model=model)
        usage = raw.get("usageMetadata") or {}
        meta = {
            "prompt_tokens": int(usage.get("promptTokenCount") or 0),
            "output_tokens": int(
                usage.get("candidatesTokenCount")
                or usage.get("totalTokenCount")
                or 0
            ),
            "raw_model": model,
        }
        return analysis, meta

    def _request_body(
        self,
        packet: MusicalAnalysisPacket,
        audio_bytes: bytes | None,
        audio_mime: str,
        task: str,
    ) -> dict[str, Any]:
        hint = _TASK_HINTS.get(task, USER_TASK_FULL)
        user_text = hint + "\n\nANALYSIS_PACKET:\n" + json.dumps(
            packet.to_dict(), separators=(",", ":")
        )
        parts: list[dict[str, Any]] = [{"text": user_text}]
        if audio_bytes:
            import base64

            parts.append(
                {
                    "inline_data": {
                        "mime_type": audio_mime or "audio/wav",
                        "data": base64.b64encode(audio_bytes).decode("ascii"),
                    }
                }
            )
        return {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }


def _extract_text(raw: dict[str, Any]) -> str:
    candidates = raw.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")
    parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
    chunks = [str(p.get("text") or "") for p in parts if isinstance(p, dict)]
    return "".join(chunks).strip()


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Gemini did not return JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Gemini JSON was not an object")
    return payload
