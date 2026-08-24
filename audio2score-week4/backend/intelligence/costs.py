"""Gemini request cost tracking."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from intelligence.config import AUDIO_TOKENS_PER_SECOND, GeminiConfig, pricing_for


@dataclass
class CostRecord:
    job_id: str
    model: str
    input_type: str
    audio_duration: float
    estimated_input_tokens: int
    output_tokens: int
    latency_ms: float
    estimated_cost: float
    cache_hit: bool
    timestamp: float


def estimate_cost(
    model: str,
    *,
    text_chars: int,
    audio_seconds: float,
    output_tokens: int,
    prompt_tokens: int | None = None,
) -> tuple[int, float]:
    rates = pricing_for(model)
    audio_tokens = int(round(audio_seconds * AUDIO_TOKENS_PER_SECOND))
    text_tokens = prompt_tokens
    if text_tokens is None:
        text_tokens = max(1, text_chars // 4)
    input_tokens = int(text_tokens + audio_tokens)
    audio_cost = (audio_tokens / 1_000_000.0) * rates["audio_input"]
    text_cost = (max(text_tokens, 0) / 1_000_000.0) * rates["text_input"]
    out_cost = (output_tokens / 1_000_000.0) * rates["output"]
    return input_tokens, audio_cost + text_cost + out_cost


class CostTracker:
    def __init__(self, cfg: GeminiConfig):
        self.path = Path(cfg.cache_dir).parent / "gemini_costs.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, row: CostRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(row)) + "\n")

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def summary(self) -> dict[str, Any]:
        rows = self.records()
        if not rows:
            return {
                "requests": 0,
                "cost_per_transcription": 0.0,
                "average_gemini_cost": 0.0,
                "cost_per_audio_minute": 0.0,
                "cache_savings": 0.0,
                "premium_escalation_rate": 0.0,
            }
        jobs = {r.get("job_id") for r in rows}
        costs = [float(r.get("estimated_cost") or 0.0) for r in rows]
        billed = [r for r in rows if not r.get("cache_hit")]
        cached = [r for r in rows if r.get("cache_hit")]
        audio_minutes = sum(float(r.get("audio_duration") or 0.0) for r in billed) / 60.0
        billed_cost = sum(float(r.get("estimated_cost") or 0.0) for r in billed)
        cache_savings = sum(float(r.get("estimated_cost") or 0.0) for r in cached)
        premium = [
            r
            for r in billed
            if "flash-lite" not in str(r.get("model") or "")
        ]
        return {
            "requests": len(rows),
            "jobs": len(jobs),
            "cost_per_transcription": round(sum(costs) / max(len(jobs), 1), 6),
            "average_gemini_cost": round(sum(costs) / len(rows), 6),
            "cost_per_audio_minute": round(
                billed_cost / audio_minutes, 6
            )
            if audio_minutes > 0
            else 0.0,
            "cache_savings": round(cache_savings, 6),
            "premium_escalation_rate": round(len(premium) / max(len(billed), 1), 3),
        }


def now_ms() -> float:
    return time.perf_counter() * 1000.0
