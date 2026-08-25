"""On-disk corpus schema for the Checkpoint 5 regression benchmark."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LoadedCase:
    case_id: str
    category: str
    description: str
    path: Path
    metadata: dict[str, Any]
    reference: dict[str, Any]
    input_midi: Path
    reference_midi: Path

    @property
    def tempo_bpm(self) -> float:
        return float(self.metadata.get("tempo_bpm") or 120)

    @property
    def time_signature(self) -> str:
        return str(self.metadata.get("time_signature") or "4/4")

    @property
    def key(self) -> str:
        return str(self.metadata.get("key") or "C")

    @property
    def ci(self) -> bool:
        return bool(self.metadata.get("ci", True))

    @property
    def expected_meter(self) -> str | None:
        expected = self.reference.get("expected") or self.metadata.get("expected") or {}
        return expected.get("meter") or self.time_signature

    @property
    def expected_key(self) -> str | None:
        expected = self.reference.get("expected") or self.metadata.get("expected") or {}
        return expected.get("key") or self.key

    @property
    def expected_voice_count_rh(self) -> int | None:
        expected = self.reference.get("expected") or {}
        return expected.get("voice_count_rh")

    @property
    def notation_plan_required(self) -> bool:
        expected = self.reference.get("expected") or {}
        return bool(expected.get("notation_plan_required", True))

    @property
    def keep_all_octaves(self) -> bool:
        expected = self.reference.get("expected") or {}
        return bool(expected.get("keep_all_octaves", False))

    @property
    def check_hands(self) -> bool:
        expected = self.reference.get("expected") or self.metadata.get("expected") or {}
        return bool(expected.get("check_hands", True))

    @property
    def meter_eval(self) -> str:
        expected = self.reference.get("expected") or self.metadata.get("expected") or {}
        value = str(expected.get("meter_eval") or "STRICT_METER").strip().upper()
        if value not in {"STRICT_METER", "METER_AMBIGUOUS", "METER_NOT_EVALUATED"}:
            return "STRICT_METER"
        return value

    @property
    def reference_notes(self) -> list[dict[str, Any]]:
        return list(self.reference.get("notes") or [])
