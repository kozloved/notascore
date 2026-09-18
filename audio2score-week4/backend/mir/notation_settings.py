"""Explicit, reversible notation settings for the derived score only.

These never rewrite original MIDI bytes, source note IDs, or performed
seconds. Defaults reproduce the production performance-score engine
(`performance-score-1`). Improved readable policies are opt-in via
`algorithm_version=performance-score-2`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable

ALGORITHM_VERSION_CURRENT = "performance-score-1"
ALGORITHM_VERSION_READABLE = "performance-score-2"
SUPPORTED_ALGORITHM_VERSIONS = (
    ALGORITHM_VERSION_CURRENT,
    ALGORITHM_VERSION_READABLE,
)

# Default max dots matches the current named-duration set (single dots only).
DEFAULT_MAX_DOTS = 1


class DisplayGrid(str, Enum):
    AUTO = "auto"
    EIGHTH = "eighth"
    SIXTEENTH = "sixteenth"
    THIRTY_SECOND = "thirty-second"


class TripletPolicy(str, Enum):
    AUTO = "auto"
    ENABLED = "enabled"
    DISABLED = "disabled"


class Interpretation(str, Enum):
    LITERAL = "literal"
    READABLE = "readable"


class SyncopationPolicy(str, Enum):
    PRESERVE = "preserve"
    SHOW_METER = "show_meter"


class OverlapHandling(str, Enum):
    PRESERVE = "preserve"
    CONTEXTUAL = "contextual"


_DISPLAY_GRID_ALIASES = {
    "auto": DisplayGrid.AUTO,
    "eighth": DisplayGrid.EIGHTH,
    "8th": DisplayGrid.EIGHTH,
    "1/8": DisplayGrid.EIGHTH,
    "sixteenth": DisplayGrid.SIXTEENTH,
    "16th": DisplayGrid.SIXTEENTH,
    "1/16": DisplayGrid.SIXTEENTH,
    "thirty-second": DisplayGrid.THIRTY_SECOND,
    "thirty_second": DisplayGrid.THIRTY_SECOND,
    "32nd": DisplayGrid.THIRTY_SECOND,
    "1/32": DisplayGrid.THIRTY_SECOND,
}

_TRIPLET_ALIASES = {
    "auto": TripletPolicy.AUTO,
    "enabled": TripletPolicy.ENABLED,
    "on": TripletPolicy.ENABLED,
    "true": TripletPolicy.ENABLED,
    "disabled": TripletPolicy.DISABLED,
    "off": TripletPolicy.DISABLED,
    "false": TripletPolicy.DISABLED,
}

_INTERPRETATION_ALIASES = {
    "literal": Interpretation.LITERAL,
    "readable": Interpretation.READABLE,
    "current": Interpretation.READABLE,
}

_SYNCOPATION_ALIASES = {
    "preserve": SyncopationPolicy.PRESERVE,
    "show_meter": SyncopationPolicy.SHOW_METER,
    "show-meter": SyncopationPolicy.SHOW_METER,
    "meter": SyncopationPolicy.SHOW_METER,
}

_OVERLAP_ALIASES = {
    "preserve": OverlapHandling.PRESERVE,
    "contextual": OverlapHandling.CONTEXTUAL,
    "context": OverlapHandling.CONTEXTUAL,
}


class NotationSettingsError(ValueError):
    """Invalid or contradictory notation settings."""


def _enum_from(value, enum_cls, aliases, field_name):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, enum_cls):
        return value
    key = str(value).strip().lower().replace(" ", "_")
    if key not in aliases:
        allowed = ", ".join(item.value for item in enum_cls)
        raise NotationSettingsError(
            f"Unknown {field_name}={value!r}. Use {allowed}."
        )
    return aliases[key]


def _int_range(value, *, field_name, lo, hi, default=None):
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise NotationSettingsError(f"Invalid {field_name}.") from exc
    if number < lo or number > hi:
        raise NotationSettingsError(
            f"{field_name} must be between {lo} and {hi}."
        )
    return number


def _optional_float(value, *, field_name, lo, hi):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NotationSettingsError(f"Invalid {field_name}.") from exc
    if not (lo <= number <= hi):
        raise NotationSettingsError(f"{field_name} is out of range.")
    return number


@dataclass(frozen=True)
class MeasureOverride:
    """Score-wide settings remain the default; this replaces selected fields."""

    start_measure: int
    end_measure: int
    display_grid: DisplayGrid | None = None
    triplet_policy: TripletPolicy | None = None
    interpretation: Interpretation | None = None
    syncopation: SyncopationPolicy | None = None
    overlap_handling: OverlapHandling | None = None
    max_dots: int | None = None

    def __post_init__(self):
        if self.start_measure < 1 or self.end_measure < self.start_measure:
            raise NotationSettingsError(
                "Measure overrides must use 1-based inclusive ranges "
                "with start_measure <= end_measure."
            )
        if self.max_dots is not None and not 0 <= self.max_dots <= 3:
            raise NotationSettingsError("max_dots must be between 0 and 3.")
        if not any(
            value is not None
            for value in (
                self.display_grid,
                self.triplet_policy,
                self.interpretation,
                self.syncopation,
                self.overlap_handling,
                self.max_dots,
            )
        ):
            raise NotationSettingsError(
                "Measure override must set at least one notation field."
            )

    def covers(self, measure_number: int) -> bool:
        return self.start_measure <= int(measure_number) <= self.end_measure

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "start_measure": self.start_measure,
            "end_measure": self.end_measure,
        }
        if self.display_grid is not None:
            payload["display_grid"] = self.display_grid.value
        if self.triplet_policy is not None:
            payload["triplet_policy"] = self.triplet_policy.value
        if self.interpretation is not None:
            payload["interpretation"] = self.interpretation.value
        if self.syncopation is not None:
            payload["syncopation"] = self.syncopation.value
        if self.overlap_handling is not None:
            payload["overlap_handling"] = self.overlap_handling.value
        if self.max_dots is not None:
            payload["max_dots"] = self.max_dots
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "MeasureOverride":
        if not isinstance(data, dict):
            raise NotationSettingsError("Each measure override must be an object.")
        start_measure = _int_range(
            data.get("start_measure"), field_name="start_measure", lo=1, hi=10_000
        )
        end_measure = _int_range(
            data.get("end_measure"), field_name="end_measure", lo=1, hi=10_000
        )
        if start_measure is None or end_measure is None:
            raise NotationSettingsError(
                "Measure overrides require start_measure and end_measure."
            )
        return cls(
            start_measure=start_measure,
            end_measure=end_measure,
            display_grid=_enum_from(
                data.get("display_grid"), DisplayGrid, _DISPLAY_GRID_ALIASES, "display_grid"
            ),
            triplet_policy=_enum_from(
                data.get("triplet_policy"), TripletPolicy, _TRIPLET_ALIASES, "triplet_policy"
            ),
            interpretation=_enum_from(
                data.get("interpretation"), Interpretation, _INTERPRETATION_ALIASES, "interpretation"
            ),
            syncopation=_enum_from(
                data.get("syncopation"), SyncopationPolicy, _SYNCOPATION_ALIASES, "syncopation"
            ),
            overlap_handling=_enum_from(
                data.get("overlap_handling"), OverlapHandling, _OVERLAP_ALIASES, "overlap_handling"
            ),
            max_dots=_int_range(
                data.get("max_dots"), field_name="max_dots", lo=0, hi=3, default=None
            ),
        )


def _conflict(left: MeasureOverride, right: MeasureOverride) -> str | None:
    overlap_start = max(left.start_measure, right.start_measure)
    overlap_end = min(left.end_measure, right.end_measure)
    if overlap_start > overlap_end:
        return None
    fields = (
        ("display_grid", left.display_grid, right.display_grid),
        ("triplet_policy", left.triplet_policy, right.triplet_policy),
        ("interpretation", left.interpretation, right.interpretation),
        ("syncopation", left.syncopation, right.syncopation),
        ("overlap_handling", left.overlap_handling, right.overlap_handling),
        ("max_dots", left.max_dots, right.max_dots),
    )
    for name, a, b in fields:
        if a is not None and b is not None and a != b:
            return (
                f"Contradictory {name} overrides for measures "
                f"{overlap_start}–{overlap_end}: {a} vs {b}."
            )
    return None


@dataclass(frozen=True)
class NotationSettings:
    display_grid: DisplayGrid = DisplayGrid.AUTO
    triplet_policy: TripletPolicy = TripletPolicy.AUTO
    interpretation: Interpretation = Interpretation.READABLE
    syncopation: SyncopationPolicy = SyncopationPolicy.PRESERVE
    overlap_handling: OverlapHandling = OverlapHandling.CONTEXTUAL
    max_dots: int = DEFAULT_MAX_DOTS
    algorithm_version: str = ALGORITHM_VERSION_CURRENT
    meter: str | None = None
    pickup_beats: float | None = None
    first_downbeat_beat: float | None = None
    measure_overrides: tuple[MeasureOverride, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if self.algorithm_version not in SUPPORTED_ALGORITHM_VERSIONS:
            raise NotationSettingsError(
                f"Unknown algorithm_version={self.algorithm_version!r}. "
                f"Use {' | '.join(SUPPORTED_ALGORITHM_VERSIONS)}."
            )
        if not 0 <= int(self.max_dots) <= 3:
            raise NotationSettingsError("max_dots must be between 0 and 3.")
        if self.pickup_beats is not None and self.pickup_beats < 0:
            raise NotationSettingsError("pickup_beats must be >= 0.")
        if self.first_downbeat_beat is not None and self.first_downbeat_beat < 0:
            raise NotationSettingsError("first_downbeat_beat must be >= 0.")
        if (
            self.pickup_beats is not None
            and self.first_downbeat_beat is not None
            and abs((self.first_downbeat_beat % 1) - (self.pickup_beats % 1)) > 1e-6
            and self.meter
        ):
            # Pickup length and first downbeat must describe the same bar phase.
            raise NotationSettingsError(
                "pickup_beats and first_downbeat_beat disagree about bar phase."
            )
        overrides = tuple(self.measure_overrides or ())
        for left, right in (
            (overrides[i], overrides[j])
            for i in range(len(overrides))
            for j in range(i + 1, len(overrides))
        ):
            message = _conflict(left, right)
            if message:
                raise NotationSettingsError(message)

    def uses_improved_readable(self) -> bool:
        return (
            self.interpretation == Interpretation.READABLE
            and self.algorithm_version == ALGORITHM_VERSION_READABLE
        )

    def uses_current_vocabulary(self) -> bool:
        """True when onset candidates must match the historical engine."""
        return (
            self.display_grid == DisplayGrid.AUTO
            and self.triplet_policy == TripletPolicy.AUTO
            and self.interpretation != Interpretation.LITERAL
            and not self.uses_improved_readable()
        )

    def preserve_performed_durations(self) -> bool:
        return self.interpretation == Interpretation.LITERAL

    def resolved_for_measure(self, measure_number: int) -> "NotationSettings":
        changes: dict[str, Any] = {}
        for override in self.measure_overrides:
            if not override.covers(measure_number):
                continue
            if override.display_grid is not None:
                changes["display_grid"] = override.display_grid
            if override.triplet_policy is not None:
                changes["triplet_policy"] = override.triplet_policy
            if override.interpretation is not None:
                changes["interpretation"] = override.interpretation
            if override.syncopation is not None:
                changes["syncopation"] = override.syncopation
            if override.overlap_handling is not None:
                changes["overlap_handling"] = override.overlap_handling
            if override.max_dots is not None:
                changes["max_dots"] = override.max_dots
        if not changes:
            return self
        return self.replace(**changes)

    def replace(self, **changes) -> "NotationSettings":
        payload = self.to_dict()
        payload.update(changes)
        if "display_grid" in changes and isinstance(changes["display_grid"], DisplayGrid):
            payload["display_grid"] = changes["display_grid"].value
        if "triplet_policy" in changes and isinstance(changes["triplet_policy"], TripletPolicy):
            payload["triplet_policy"] = changes["triplet_policy"].value
        if "interpretation" in changes and isinstance(changes["interpretation"], Interpretation):
            payload["interpretation"] = changes["interpretation"].value
        if "syncopation" in changes and isinstance(changes["syncopation"], SyncopationPolicy):
            payload["syncopation"] = changes["syncopation"].value
        if "overlap_handling" in changes and isinstance(
            changes["overlap_handling"], OverlapHandling
        ):
            payload["overlap_handling"] = changes["overlap_handling"].value
        return NotationSettings.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_grid": self.display_grid.value,
            "triplet_policy": self.triplet_policy.value,
            "interpretation": self.interpretation.value,
            "syncopation": self.syncopation.value,
            "overlap_handling": self.overlap_handling.value,
            "max_dots": int(self.max_dots),
            "algorithm_version": self.algorithm_version,
            "meter": self.meter,
            "pickup_beats": self.pickup_beats,
            "first_downbeat_beat": self.first_downbeat_beat,
            "measure_overrides": [item.to_dict() for item in self.measure_overrides],
        }

    def identity_payload(self) -> dict[str, Any]:
        """Stable subset used for notation cache identity."""
        return self.to_dict()

    def cache_key(self, midi_sha256: str | None = None) -> str:
        blob = json.dumps(
            {
                "midi_sha256": midi_sha256 or "",
                "settings": self.identity_payload(),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None = None) -> "NotationSettings":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise NotationSettingsError("Notation settings must be an object.")
        overrides_raw = data.get("measure_overrides") or ()
        if not isinstance(overrides_raw, (list, tuple)):
            raise NotationSettingsError("measure_overrides must be a list.")
        meter = data.get("meter")
        if meter is not None:
            meter = str(meter).strip() or None
            if meter and "/" not in meter:
                raise NotationSettingsError("meter must look like 4/4 or 6/8.")
        return cls(
            display_grid=_enum_from(
                data.get("display_grid", DisplayGrid.AUTO),
                DisplayGrid,
                _DISPLAY_GRID_ALIASES,
                "display_grid",
            )
            or DisplayGrid.AUTO,
            triplet_policy=_enum_from(
                data.get("triplet_policy", TripletPolicy.AUTO),
                TripletPolicy,
                _TRIPLET_ALIASES,
                "triplet_policy",
            )
            or TripletPolicy.AUTO,
            interpretation=_enum_from(
                data.get("interpretation", Interpretation.READABLE),
                Interpretation,
                _INTERPRETATION_ALIASES,
                "interpretation",
            )
            or Interpretation.READABLE,
            syncopation=_enum_from(
                data.get("syncopation", SyncopationPolicy.PRESERVE),
                SyncopationPolicy,
                _SYNCOPATION_ALIASES,
                "syncopation",
            )
            or SyncopationPolicy.PRESERVE,
            overlap_handling=_enum_from(
                data.get("overlap_handling", OverlapHandling.CONTEXTUAL),
                OverlapHandling,
                _OVERLAP_ALIASES,
                "overlap_handling",
            )
            or OverlapHandling.CONTEXTUAL,
            max_dots=_int_range(
                data.get("max_dots", DEFAULT_MAX_DOTS),
                field_name="max_dots",
                lo=0,
                hi=3,
                default=DEFAULT_MAX_DOTS,
            ),
            algorithm_version=str(
                data.get("algorithm_version") or ALGORITHM_VERSION_CURRENT
            ).strip(),
            meter=meter,
            pickup_beats=_optional_float(
                data.get("pickup_beats"), field_name="pickup_beats", lo=0, hi=16
            ),
            first_downbeat_beat=_optional_float(
                data.get("first_downbeat_beat"),
                field_name="first_downbeat_beat",
                lo=0,
                hi=10_000,
            ),
            measure_overrides=tuple(
                MeasureOverride.from_dict(item) for item in overrides_raw
            ),
        )

    @classmethod
    def readable_opt_in(cls, base: "NotationSettings | None" = None) -> "NotationSettings":
        source = base or cls()
        return source.replace(
            interpretation=Interpretation.READABLE,
            algorithm_version=ALGORITHM_VERSION_READABLE,
        )

    @classmethod
    def literal(cls, base: "NotationSettings | None" = None) -> "NotationSettings":
        source = base or cls()
        return source.replace(
            interpretation=Interpretation.LITERAL,
            algorithm_version=ALGORITHM_VERSION_CURRENT,
        )


def default_notation_settings() -> NotationSettings:
    return NotationSettings()


def parse_notation_settings(value: NotationSettings | dict | None = None) -> NotationSettings:
    if value is None:
        return NotationSettings()
    if isinstance(value, NotationSettings):
        return value
    return NotationSettings.from_dict(value)


def notation_settings_from_meta(meta) -> NotationSettings:
    extra = getattr(meta, "extra", None) or {}
    if isinstance(extra, dict) and extra.get("notation_settings") is not None:
        return parse_notation_settings(extra.get("notation_settings"))
    return NotationSettings()


def settings_for_reset() -> NotationSettings:
    return NotationSettings()
