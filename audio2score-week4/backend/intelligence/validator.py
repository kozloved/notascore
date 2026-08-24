"""Reject invalid or destructive Gemini MIDI/score patches."""

from __future__ import annotations

from intelligence.config import GeminiConfig
from intelligence.schemas import Correction
from mir.types import NoteEvent

ALLOWED_TYPES = {"instrument", "pitch", "timing", "voice", "meter", "tempo", "hand"}
ALLOWED_METERS = {"4/4", "3/4", "2/4", "6/8", "2/2", "5/4", "12/8"}
PIANO_MIN = 21
PIANO_MAX = 108


class MusicalCorrectionValidator:
    def __init__(self, cfg: GeminiConfig):
        self.cfg = cfg

    def combined_confidence(
        self,
        correction: Correction,
        notes: list[NoteEvent],
        *,
        audio_feature_confidence: float,
    ) -> float:
        gemini = _clamp(correction.confidence)
        window_conf = _window_transcription_confidence(notes, correction)
        if _is_drop(correction):
            transcription = _clamp(1.0 - window_conf)
        else:
            transcription = window_conf
        consistency = _musical_consistency(correction, notes)
        audio = _clamp(audio_feature_confidence)
        return round(
            0.25 * transcription
            + 0.20 * audio
            + 0.35 * gemini
            + 0.20 * consistency,
            3,
        )

    def validate(
        self,
        corrections: list[Correction],
        notes: list[NoteEvent],
        *,
        audio_feature_confidence: float,
        allow_deep: bool = False,
    ) -> tuple[list[Correction], list[Correction]]:
        accepted: list[Correction] = []
        rejected: list[Correction] = []
        drop_count = 0
        raw_cap = len(notes) * self.cfg.max_drop_fraction
        max_drops = int(raw_cap)
        if notes and self.cfg.max_drop_fraction > 0 and max_drops < 1:
            max_drops = 1

        for corr in corrections:
            corr.final_confidence = self.combined_confidence(
                corr, notes, audio_feature_confidence=audio_feature_confidence
            )
            reason = self._reject_reason(corr, notes, allow_deep=allow_deep)
            if reason:
                corr.reason = f"{corr.reason} [{reason}]".strip()
                rejected.append(corr)
                continue
            if _is_drop(corr):
                drop_count += 1
                if drop_count > max_drops:
                    corr.reason = f"{corr.reason} [too many drops]".strip()
                    rejected.append(corr)
                    continue
            accepted.append(corr)
        return accepted, rejected

    def _reject_reason(
        self, corr: Correction, notes: list[NoteEvent], *, allow_deep: bool
    ) -> str | None:
        if corr.type not in ALLOWED_TYPES:
            return "unsupported type"
        if corr.time_end < corr.time_start:
            return "invalid timing"
        if corr.time_end - corr.time_start > 30:
            return "window too wide"
        if corr.requires_deep_analysis and not allow_deep:
            return "needs deep analysis"
        if corr.final_confidence < self.cfg.auto_apply_threshold:
            return "below auto-apply threshold"
        if corr.type == "pitch":
            proposed = corr.proposed_value or {}
            if proposed.get("drop") or proposed.get("action") == "delete":
                return None
            pitch = proposed.get("pitch")
            if pitch is None:
                return "missing pitch"
            if not PIANO_MIN <= int(pitch) <= PIANO_MAX:
                return "pitch out of range"
        if corr.type == "timing":
            start = corr.proposed_value.get("start_time", corr.time_start)
            end = corr.proposed_value.get("end_time", corr.time_end)
            if float(end) - float(start) < 0.02:
                return "duration too short"
        if corr.type == "tempo":
            bpm = corr.proposed_value.get("bpm") or corr.proposed_value.get("global_bpm")
            if bpm is None:
                return "missing tempo"
            if not 40 <= float(bpm) <= 240:
                return "tempo out of range"
        if corr.type == "meter":
            ts = str(corr.proposed_value.get("time_signature") or "")
            if ts not in ALLOWED_METERS:
                return "meter not allowed"
        if corr.type == "instrument":
            name = str(
                corr.proposed_value.get("instrument")
                or corr.proposed_value.get("primary")
                or ""
            ).lower()
            if name not in {"piano", "guitar", "voice", "drums", "strings", "unknown"}:
                return "instrument not allowed"
        if not notes and corr.type in {"pitch", "timing"}:
            return "no notes to patch"
        return None


def _is_drop(corr: Correction) -> bool:
    proposed = corr.proposed_value or {}
    return bool(proposed.get("drop") or proposed.get("action") == "delete")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _window_transcription_confidence(
    notes: list[NoteEvent], corr: Correction
) -> float:
    windowed = [
        n
        for n in notes
        if n.start_time >= corr.time_start - 0.05
        and n.start_time <= corr.time_end + 0.05
    ]
    existing_pitch = corr.existing_value.get("pitch")
    if existing_pitch is not None:
        windowed = [n for n in windowed if int(n.pitch) == int(existing_pitch)]
    if not windowed:
        return 0.5
    return _clamp(sum(n.confidence for n in windowed) / len(windowed))


def _musical_consistency(corr: Correction, notes: list[NoteEvent]) -> float:
    if corr.type == "pitch" and _is_drop(corr):
        existing = int(corr.existing_value.get("pitch") or 0)
        neighbors = [
            n
            for n in notes
            if abs(n.start_time - corr.time_start) <= 0.08
            and abs(n.pitch - existing) in (12, 24)
        ]
        return 0.9 if neighbors else 0.45
    if corr.type == "tempo":
        return 0.7
    if corr.type == "meter":
        return 0.65
    if corr.type == "hand":
        return 0.6
    if corr.type == "instrument":
        return 0.55
    return 0.5
