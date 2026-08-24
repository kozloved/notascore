"""GeminiMusicAnalysisService — one structured JSON analysis call plus optional region pass."""

from __future__ import annotations

import json
import time

from intelligence.audio import encode_analysis_wav
from intelligence.cache import AnalysisCache, cache_key, hash_bytes, hash_json
from intelligence.config import GeminiConfig
from intelligence.costs import CostRecord, CostTracker, estimate_cost
from intelligence.gemini_provider import GeminiProvider
from intelligence.packet import packet_for_regions
from intelligence.provider import MusicAnalysisProvider
from intelligence.router import MusicalAnalysisRouter, RouteDecision
from intelligence.schemas import GeminiAnalysis, MusicalAnalysisPacket
from audio_engine.normalizer import NormalizedAudio


class GeminiMusicAnalysisService:
    def __init__(
        self,
        cfg: GeminiConfig,
        provider: MusicAnalysisProvider | None = None,
        cache: AnalysisCache | None = None,
        tracker: CostTracker | None = None,
    ):
        self.cfg = cfg
        self.provider = provider or GeminiProvider(cfg)
        self.cache = cache or AnalysisCache(cfg)
        self.tracker = tracker or CostTracker(cfg)
        self.router = MusicalAnalysisRouter(cfg)

    def analyse_music(
        self,
        packet: MusicalAnalysisPacket,
        *,
        job_id: str,
        normalized: NormalizedAudio | None = None,
        audio_hash: str = "",
    ) -> GeminiAnalysis:
        return self._run(packet, job_id=job_id, normalized=normalized, audio_hash=audio_hash, task="full")

    def analyse_instruments(self, packet, **kwargs):
        return self._run(packet, task="instruments", **kwargs)

    def analyse_structure(self, packet, **kwargs):
        return self._run(packet, task="structure", **kwargs)

    def analyse_meter(self, packet, **kwargs):
        return self._run(packet, task="meter", **kwargs)

    def analyse_tempo(self, packet, **kwargs):
        return self._run(packet, task="tempo", **kwargs)

    def analyse_phrases(self, packet, **kwargs):
        return self._run(packet, task="phrases", **kwargs)

    def analyse_polyphony(self, packet, **kwargs):
        return self._run(packet, task="polyphony", **kwargs)

    def validate_transcription(self, packet, **kwargs):
        return self._run(packet, task="validate", **kwargs)

    def analyse_uncertain_regions(
        self,
        packet: MusicalAnalysisPacket,
        windows: list[tuple[float, float]],
        *,
        job_id: str,
        normalized: NormalizedAudio | None = None,
        audio_hash: str = "",
        model: str | None = None,
    ) -> GeminiAnalysis:
        sliced = packet_for_regions(packet, windows)
        return self._run(
            sliced,
            job_id=job_id,
            normalized=normalized,
            audio_hash=audio_hash,
            task="regions",
            model=model,
            windows=windows,
        )

    def route(self, packet: MusicalAnalysisPacket, lite: GeminiAnalysis | None = None) -> RouteDecision:
        return self.router.decide(packet, lite)

    def _run(
        self,
        packet: MusicalAnalysisPacket,
        *,
        job_id: str = "",
        normalized: NormalizedAudio | None = None,
        audio_hash: str = "",
        task: str = "full",
        model: str | None = None,
        windows: list[tuple[float, float]] | None = None,
    ) -> GeminiAnalysis:
        model_name = model or self.cfg.default_model
        packet_dict = packet.to_dict()
        transcription_hash = hash_json(packet_dict["transcription"])
        key = cache_key(
            audio_hash=audio_hash,
            transcription_hash=transcription_hash,
            model_name=model_name,
            extra=task,
        )
        cached = self.cache.get(key)
        if cached:
            analysis = GeminiAnalysis.from_dict(cached, model=model_name)
            analysis.cache_hit = True
            self._log_cost(
                job_id=job_id or packet.job_id,
                model=model_name,
                input_type="cache",
                audio_duration=0.0,
                text_chars=0,
                output_tokens=0,
                latency_ms=0.0,
                cache_hit=True,
                estimated_cost_override=float(cached.get("_estimated_cost") or 0.0),
            )
            return analysis

        audio_bytes = None
        audio_seconds = 0.0
        if self.cfg.audio_input and normalized is not None:
            audio_bytes, audio_seconds = encode_analysis_wav(
                normalized,
                max_seconds=self.cfg.max_audio_seconds,
                windows=windows,
            )
            if audio_bytes and not audio_hash:
                audio_hash = hash_bytes(audio_bytes)

        started = time.perf_counter()
        send_audio = bool(audio_bytes) and self.cfg.audio_input
        try:
            analysis, usage, used_audio = self._call_provider(
                packet,
                model_name=model_name,
                audio_bytes=audio_bytes if send_audio else None,
                task=task,
            )
        except Exception as exc:
            print(f"[Gemini] analysis failed ({exc}); continuing without patches")
            failed = GeminiAnalysis(raw={"_error": str(exc)[:400]})
            return failed

        latency_ms = (time.perf_counter() - started) * 1000.0
        text_chars = len(json.dumps(packet_dict))
        output_tokens = int(usage.get("output_tokens") or 0)
        prompt_tokens = int(usage.get("prompt_tokens") or 0) or None
        billed_audio = audio_seconds if used_audio else 0.0
        input_tokens, cost = estimate_cost(
            model_name,
            text_chars=text_chars,
            audio_seconds=billed_audio,
            output_tokens=output_tokens,
            prompt_tokens=prompt_tokens,
        )
        payload = analysis.to_dict()
        payload["_estimated_cost"] = cost
        payload["_input_tokens"] = input_tokens
        self.cache.set(key, payload)
        self._log_cost(
            job_id=job_id or packet.job_id,
            model=model_name,
            input_type="audio+json" if used_audio else "json",
            audio_duration=billed_audio,
            text_chars=text_chars,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cache_hit=False,
            prompt_tokens=prompt_tokens,
        )
        analysis.model = model_name
        return analysis

    def _call_provider(
        self,
        packet: MusicalAnalysisPacket,
        *,
        model_name: str,
        audio_bytes: bytes | None,
        task: str,
    ) -> tuple[GeminiAnalysis, dict, bool]:
        try:
            analysis, usage = self.provider.analyse(
                packet,
                model=model_name,
                audio_bytes=audio_bytes,
                audio_mime="audio/wav",
                task=task,
            )
            return analysis, usage, bool(audio_bytes)
        except Exception as exc:
            if audio_bytes and "timed out" in str(exc).lower():
                print("[Gemini] audio call timed out; retrying JSON-only")
                analysis, usage = self.provider.analyse(
                    packet,
                    model=model_name,
                    audio_bytes=None,
                    audio_mime="audio/wav",
                    task=task,
                )
                return analysis, usage, False
            raise

    def _log_cost(
        self,
        *,
        job_id: str,
        model: str,
        input_type: str,
        audio_duration: float,
        text_chars: int,
        output_tokens: int,
        latency_ms: float,
        cache_hit: bool,
        prompt_tokens: int | None = None,
        estimated_cost_override: float | None = None,
    ) -> None:
        input_tokens, cost = estimate_cost(
            model,
            text_chars=text_chars,
            audio_seconds=audio_duration,
            output_tokens=output_tokens,
            prompt_tokens=prompt_tokens,
        )
        if estimated_cost_override is not None:
            cost = estimated_cost_override
        self.tracker.record(
            CostRecord(
                job_id=job_id,
                model=model,
                input_type=input_type,
                audio_duration=audio_duration,
                estimated_input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=round(latency_ms, 1),
                estimated_cost=round(cost, 8),
                cache_hit=cache_hit,
                timestamp=time.time(),
            )
        )
