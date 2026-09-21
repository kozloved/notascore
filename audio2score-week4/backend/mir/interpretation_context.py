"""Versioned production interpretation context for notation regeneration.

A display-grid or readability change must reuse this context rather than
re-estimating tempo, rotating the beat origin, restoring excluded notes,
or changing key. Missing context is an explicit migration/fallback, never
a silent MIDI-tempo reinterpretation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mir.types import TempoMap, TempoPoint
from timing.tempo_map import MusicalTimeMap

CONTEXT_SCHEMA_VERSION = 1
FALLBACK_MISSING = "legacy_interpretation_context_missing"
FALLBACK_TEMPO_JSON = "migrated_from_tempo_json"
FALLBACK_MIDI_INGEST = "migrated_from_midi_ingest"


class InterpretationContextError(ValueError):
    """Context is missing, contradictory, or the wrong schema."""


@dataclass(frozen=True)
class InterpretationContext:
    schema_version: int = CONTEXT_SCHEMA_VERSION
    time_map: MusicalTimeMap | None = None
    selected_meter: str = "4/4"
    key_name: str = "C"
    instrument: str = "piano"
    display_bpm: float = 120.0
    tempo_scale: float = 1.0
    pickup_beats: float | None = None
    first_downbeat_beat: float | None = None
    downbeat_beats: tuple[float, ...] = ()
    score_beat_offset: float = 0.0
    accepted_source_note_ids: tuple[str, ...] = ()
    excluded_source_note_ids: tuple[str, ...] = ()
    has_recorded_selection: bool = False
    time_map_includes_score_offset: bool = False
    layout_decisions: tuple[dict, ...] = ()
    printed_tempo: tuple[dict, ...] = ()
    playback_tempo: tuple[dict, ...] = ()
    pedal_events: tuple[tuple[float, int], ...] = ()
    midi_sha256: str | None = None
    source_backend: str = ""
    fallback: str | None = None

    def __post_init__(self):
        if int(self.schema_version) != CONTEXT_SCHEMA_VERSION:
            raise InterpretationContextError(
                f"Unsupported interpretation context schema {self.schema_version}."
            )
        if self.time_map is None:
            raise InterpretationContextError(
                "Interpretation context requires a seconds-to-score-beats map."
            )

    def identity_digest(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "time_map": time_map_to_dict(self.time_map),
            "selected_meter": self.selected_meter,
            "key_name": self.key_name,
            "instrument": self.instrument,
            "display_bpm": self.display_bpm,
            "tempo_scale": self.tempo_scale,
            "pickup_beats": self.pickup_beats,
            "first_downbeat_beat": self.first_downbeat_beat,
            "downbeat_beats": list(self.downbeat_beats),
            "score_beat_offset": self.score_beat_offset,
            "time_map_includes_score_offset": self.time_map_includes_score_offset,
            "accepted_source_note_ids": list(self.accepted_source_note_ids),
            "excluded_source_note_ids": list(self.excluded_source_note_ids),
            "has_recorded_selection": self.has_recorded_selection,
            "layout_decisions": canonical_json(self.layout_decisions),
            "printed_tempo": canonical_json(self.printed_tempo),
            "playback_tempo": canonical_json(self.playback_tempo),
            "pedal_events": [list(row) for row in self.pedal_events],
            "midi_sha256": self.midi_sha256 or "",
            "source_backend": self.source_backend or "",
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def tempo_map(self) -> TempoMap:
        return tempo_map_from_musical(self.time_map)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "time_map": time_map_to_dict(self.time_map),
            "selected_meter": self.selected_meter,
            "key_name": self.key_name,
            "instrument": self.instrument,
            "display_bpm": self.display_bpm,
            "tempo_scale": self.tempo_scale,
            "pickup_beats": self.pickup_beats,
            "first_downbeat_beat": self.first_downbeat_beat,
            "downbeat_beats": list(self.downbeat_beats),
            "score_beat_offset": self.score_beat_offset,
            "accepted_source_note_ids": list(self.accepted_source_note_ids),
            "excluded_source_note_ids": list(self.excluded_source_note_ids),
            "has_recorded_selection": self.has_recorded_selection,
            "time_map_includes_score_offset": self.time_map_includes_score_offset,
            "layout_decisions": [dict(row) for row in self.layout_decisions],
            "printed_tempo": [dict(row) for row in self.printed_tempo],
            "playback_tempo": [dict(row) for row in self.playback_tempo],
            "pedal_events": [list(row) for row in self.pedal_events],
            "midi_sha256": self.midi_sha256,
            "source_backend": self.source_backend,
            "fallback": self.fallback,
            "identity_digest": self.identity_digest(),
        }

    def write_json(self, path: str | Path) -> Path:
        dest = Path(path)
        dest.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return dest

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "InterpretationContext":
        if not isinstance(data, dict):
            raise InterpretationContextError("Interpretation context must be an object.")
        version = int(data.get("schema_version") or 0)
        if version != CONTEXT_SCHEMA_VERSION:
            raise InterpretationContextError(
                f"Unsupported interpretation context schema {version}."
            )
        meter = str(data.get("selected_meter") or "4/4")
        return cls(
            schema_version=version,
            time_map=time_map_from_dict(data.get("time_map")),
            selected_meter=meter,
            key_name=str(data.get("key_name") or "C"),
            instrument=str(data.get("instrument") or "piano"),
            display_bpm=float(data.get("display_bpm") or 120.0),
            tempo_scale=float(data.get("tempo_scale") or 1.0),
            pickup_beats=_optional_float(data.get("pickup_beats")),
            first_downbeat_beat=_optional_float(data.get("first_downbeat_beat")),
            downbeat_beats=tuple(float(v) for v in (data.get("downbeat_beats") or ())),
            score_beat_offset=float(data.get("score_beat_offset") or 0.0),
            accepted_source_note_ids=tuple(
                str(v) for v in (data.get("accepted_source_note_ids") or ()) if v
            ),
            excluded_source_note_ids=tuple(
                str(v) for v in (data.get("excluded_source_note_ids") or ()) if v
            ),
            has_recorded_selection=_recorded_selection(data),
            time_map_includes_score_offset=bool(data.get("time_map_includes_score_offset")),
            layout_decisions=tuple(
                dict(row) for row in (data.get("layout_decisions") or ()) if isinstance(row, dict)
            ),
            printed_tempo=tuple(
                dict(row) for row in (data.get("printed_tempo") or ()) if isinstance(row, dict)
            ),
            playback_tempo=tuple(
                dict(row) for row in (data.get("playback_tempo") or ()) if isinstance(row, dict)
            ),
            pedal_events=tuple(
                (float(row[0]), int(row[1]), str(row[2]))
                if len(row) > 2
                else (float(row[0]), int(row[1]))
                for row in (data.get("pedal_events") or ())
                if isinstance(row, (list, tuple)) and len(row) >= 2
            ),
            midi_sha256=data.get("midi_sha256"),
            source_backend=str(data.get("source_backend") or ""),
            fallback=data.get("fallback"),
        )

    @classmethod
    def read_json(cls, path: str | Path) -> "InterpretationContext":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def time_map_to_dict(time_map: MusicalTimeMap | None) -> dict[str, Any]:
    if time_map is None:
        return {}
    return {
        "beat_times": list(time_map.beat_times),
        "confidence": list(time_map.confidence),
        "source": time_map.source,
        "exact_points": [list(point) for point in time_map.exact_points],
    }


def time_map_from_dict(data: dict[str, Any] | None) -> MusicalTimeMap:
    if not isinstance(data, dict) or not data.get("beat_times"):
        raise InterpretationContextError("Interpretation context is missing a time map.")
    exact = tuple(
        (float(row[0]), float(row[1]), float(row[2]))
        for row in (data.get("exact_points") or ())
        if isinstance(row, (list, tuple)) and len(row) >= 3
    )
    return MusicalTimeMap(
        tuple(float(t) for t in data["beat_times"]),
        tuple(float(c) for c in (data.get("confidence") or ())),
        source=str(data.get("source") or "explicit_beats"),
        exact_points=exact,
    )


def tempo_map_from_musical(time_map: MusicalTimeMap) -> TempoMap:
    points = [
        TempoPoint(time_sec=float(t), beat=float(beat), bpm=float(bpm))
        for t, beat, bpm in time_map._knots()
    ]
    if not points:
        bpm = 60.0 / max(time_map.beat_times[1] - time_map.beat_times[0], 1e-6)
        points = [TempoPoint(time_sec=float(time_map.beat_times[0]), beat=0.0, bpm=bpm)]
    return TempoMap(points)


def _optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _recorded_selection(data: dict[str, Any]) -> bool:
    if "has_recorded_selection" in data:
        return bool(data.get("has_recorded_selection"))
    return "accepted_source_note_ids" in data or "excluded_source_note_ids" in data


def canonical_json(value: Any) -> Any:
    """Deterministic JSON-ready form for cache and identity digests."""
    if isinstance(value, dict):
        return {str(key): canonical_json(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [canonical_json(item) for item in value]
    if isinstance(value, list):
        return [canonical_json(item) for item in value]
    if isinstance(value, float):
        return round(value, 9)
    try:
        from fractions import Fraction

        if isinstance(value, Fraction):
            return str(value)
    except Exception:
        pass
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return str(value)


def migrate_from_tempo_payload(
    payload: dict[str, Any],
    *,
    midi_sha256: str | None = None,
    source_backend: str = "",
    accepted_source_note_ids: tuple[str, ...] = (),
    excluded_source_note_ids: tuple[str, ...] = (),
    layout_decisions: tuple[dict, ...] = (),
    pedal_events: tuple[tuple[float, int], ...] = (),
    key_name: str = "C",
    instrument: str = "piano",
) -> InterpretationContext:
    """Rebuild context from tempo.json. Explicit fallback, not a silent re-estimate."""
    from score_edits import time_map_from_tempo_payload

    time_map = time_map_from_tempo_payload(payload)
    selected = payload.get("selected_meter") or "4/4"
    if isinstance(selected, dict):
        selected = selected.get("ratio") or selected.get("meter") or "4/4"
    quality = payload.get("quality") or {}
    display_bpm = quality.get("median_bpm") or 120.0
    printed = payload.get("printed_tempo") or []
    downbeats = []
    for t in payload.get("downbeat_times") or ():
        try:
            downbeats.append(float(time_map.seconds_to_beats(float(t))))
        except Exception:
            continue
    return InterpretationContext(
        time_map=time_map,
        selected_meter=str(selected),
        key_name=key_name,
        instrument=instrument,
        display_bpm=float(display_bpm),
        tempo_scale=float((payload.get("score") or {}).get("tempo_scale") or payload.get("tempo_scale") or 1.0),
        downbeat_beats=tuple(downbeats),
        accepted_source_note_ids=accepted_source_note_ids,
        excluded_source_note_ids=excluded_source_note_ids,
        has_recorded_selection=bool(accepted_source_note_ids or excluded_source_note_ids),
        layout_decisions=layout_decisions,
        printed_tempo=tuple(dict(row) for row in printed if isinstance(row, dict)),
        pedal_events=pedal_events,
        midi_sha256=midi_sha256,
        source_backend=source_backend,
        fallback=FALLBACK_TEMPO_JSON,
    )


def load_context_payload(
    raw: bytes | str | None,
    *,
    tempo_payload: dict[str, Any] | None = None,
    midi_sha256: str | None = None,
    source_backend: str = "",
    accepted_source_note_ids: tuple[str, ...] = (),
    excluded_source_note_ids: tuple[str, ...] = (),
    layout_decisions: tuple[dict, ...] = (),
    pedal_events: tuple[tuple[float, int], ...] = (),
    key_name: str = "C",
    instrument: str = "piano",
) -> tuple[InterpretationContext | None, str | None]:
    """Load a versioned context or return an explicit fallback status."""
    if raw:
        try:
            payload = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
            return InterpretationContext.from_dict(payload), payload.get("fallback")
        except Exception as exc:
            raise InterpretationContextError(
                f"Stored interpretation context is unreadable: {exc}"
            ) from exc
    if tempo_payload:
        return (
            migrate_from_tempo_payload(
                tempo_payload,
                midi_sha256=midi_sha256,
                source_backend=source_backend,
                accepted_source_note_ids=accepted_source_note_ids,
                excluded_source_note_ids=excluded_source_note_ids,
                layout_decisions=layout_decisions,
                pedal_events=pedal_events,
                key_name=key_name,
                instrument=instrument,
            ),
            FALLBACK_TEMPO_JSON,
        )
    return None, FALLBACK_MISSING
