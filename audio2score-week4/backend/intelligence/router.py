"""Decide whether Flash-Lite is enough or regions need a deeper model."""

from __future__ import annotations

from dataclasses import dataclass

from intelligence.config import GeminiConfig
from intelligence.schemas import GeminiAnalysis, MusicalAnalysisPacket


@dataclass
class RouteDecision:
    use_lite: bool = True
    regional: bool = False
    use_deep: bool = False
    complexity: float = 0.0
    windows: list[tuple[float, float]] | None = None
    reason: str = ""


class MusicalAnalysisRouter:
    def __init__(self, cfg: GeminiConfig):
        self.cfg = cfg

    def complexity(self, packet: MusicalAnalysisPacket) -> float:
        poly = float(
            (packet.transcription.get("polyphony_summary") or {}).get("max") or 0
        )
        conf = packet.transcription.get("note_confidence_summary") or {}
        mean_conf = float(conf.get("mean") or 1.0)
        low = float(conf.get("low_count") or 0)
        notes = max(int(packet.transcription.get("note_count") or 1), 1)
        inst_conf = 1.0
        cands = packet.transcription.get("instrument_candidates") or []
        if cands:
            inst_conf = float(cands[0].get("confidence") or 0.0)
        tempo_changes = len(packet.tempo.get("tempo_changes") or [])
        pitch_conflicts = len(packet.uncertainties.get("pitch_conflicts") or [])
        crossings = len((packet.piano or {}).get("hand_crossings") or [])
        inst_conflicts = len(packet.uncertainties.get("instrument_conflicts") or [])
        score = 0.0
        score += min(0.25, max(0.0, (poly - 2) / 8.0) * 0.25)
        score += min(0.25, (1.0 - mean_conf) * 0.4 + (low / notes) * 0.3)
        score += 0.15 if inst_conf < 0.55 else 0.0
        score += min(0.15, max(0, tempo_changes - 1) * 0.05)
        score += min(0.15, pitch_conflicts * 0.03)
        score += min(0.1, crossings * 0.03)
        score += 0.1 if inst_conflicts else 0.0
        return round(min(1.0, score), 3)

    def decide(
        self,
        packet: MusicalAnalysisPacket,
        lite: GeminiAnalysis | None = None,
    ) -> RouteDecision:
        complexity = self.complexity(packet)
        windows = self._windows(packet, lite)
        simple_piano = self._simple_piano(packet) and complexity < 0.35
        if simple_piano:
            return RouteDecision(
                use_lite=True,
                regional=False,
                use_deep=False,
                complexity=complexity,
                reason="simple_piano",
            )
        if complexity >= 0.7 and self.cfg.deep_analysis and windows:
            return RouteDecision(
                use_lite=True,
                regional=True,
                use_deep=True,
                complexity=complexity,
                windows=windows,
                reason="highly_ambiguous",
            )
        if complexity >= 0.35 or windows:
            return RouteDecision(
                use_lite=True,
                regional=True,
                use_deep=False,
                complexity=complexity,
                windows=windows,
                reason="moderate_or_uncertain_regions",
            )
        return RouteDecision(
            use_lite=True,
            regional=False,
            use_deep=False,
            complexity=complexity,
            reason="lite_sufficient",
        )

    def _simple_piano(self, packet: MusicalAnalysisPacket) -> bool:
        cands = packet.transcription.get("instrument_candidates") or []
        inst = (cands[0].get("instrument") if cands else "") or ""
        poly = float(
            (packet.transcription.get("polyphony_summary") or {}).get("max") or 0
        )
        tempo_changes = len(packet.tempo.get("tempo_changes") or [])
        mean_conf = float(
            (packet.transcription.get("note_confidence_summary") or {}).get("mean")
            or 0.0
        )
        return (
            inst in ("piano", "unknown")
            and poly <= 6
            and tempo_changes <= 2
            and mean_conf >= 0.7
        )

    def _windows(
        self,
        packet: MusicalAnalysisPacket,
        lite: GeminiAnalysis | None,
    ) -> list[tuple[float, float]]:
        windows: list[tuple[float, float]] = []
        for region in packet.uncertainties.get("low_confidence_regions") or []:
            windows.append(
                (float(region["time_start"]), float(region["time_end"]))
            )
        for conflict in packet.uncertainties.get("pitch_conflicts") or []:
            windows.append(
                (float(conflict["time_start"]), float(conflict["time_end"]))
            )
        if lite:
            for corr in lite.corrections:
                if corr.requires_deep_analysis or corr.confidence < self.cfg.deep_analysis_threshold:
                    windows.append((corr.time_start, corr.time_end))
        merged = _merge_windows(windows)
        return merged[:8]


def _merge_windows(windows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not windows:
        return []
    ordered = sorted(windows, key=lambda w: w[0])
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        prev_s, prev_e = merged[-1]
        if start <= prev_e + 0.25:
            merged[-1] = (prev_s, max(prev_e, end))
        else:
            merged.append((start, end))
    return merged
