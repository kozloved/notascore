"""Versioned style/feel profile for post-transcription interpretation.

This is a prior for notation decisions, not a hard quantization grid and not
an acoustic transcription control. Arrangement target style is a separate
future concept and is not exposed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

INTERPRETATION_PROFILE_VERSION = 1

SWING_RATIO_MIN = 1.0
SWING_RATIO_MAX = 4.0


class SourceStyle(str, Enum):
    AUTO = "auto"
    JAZZ = "jazz"
    CLASSICAL = "classical"
    POP_ROCK = "pop_rock"
    CONTEMPORARY_ART = "contemporary_art"


class RhythmicFeel(str, Enum):
    AUTO = "auto"
    STRAIGHT = "straight"
    SWING_EIGHTHS = "swing_eighths"
    SWING_SIXTEENTHS = "swing_sixteenths"
    SHUFFLE = "shuffle"


class TimingFeel(str, Enum):
    AUTO = "auto"
    STEADY = "steady"
    EXPRESSIVE = "expressive"


class OutputMode(str, Enum):
    """Internal spelling nudge, not a second interpretation axis.

    Readable/Literal (``NotationSettings.interpretation``) is the user-facing
    contract from PR #102. ``faithful`` is the default and does not change
    saved scores. ``simplified`` may prefer coarser candidates under Readable;
    it never deletes notes. Keep parsing it for compatibility; do not expose
    it as a competing Faithful/Simplified interpretation control.
    """

    FAITHFUL = "faithful"
    SIMPLIFIED = "simplified"


_SOURCE_STYLE_ALIASES = {
    "auto": SourceStyle.AUTO,
    "jazz": SourceStyle.JAZZ,
    "classical": SourceStyle.CLASSICAL,
    "pop_rock": SourceStyle.POP_ROCK,
    "pop-rock": SourceStyle.POP_ROCK,
    "pop": SourceStyle.POP_ROCK,
    "rock": SourceStyle.POP_ROCK,
    "contemporary_art": SourceStyle.CONTEMPORARY_ART,
    "contemporary-art": SourceStyle.CONTEMPORARY_ART,
    "contemporary": SourceStyle.CONTEMPORARY_ART,
}

_RHYTHMIC_FEEL_ALIASES = {
    "auto": RhythmicFeel.AUTO,
    "straight": RhythmicFeel.STRAIGHT,
    "swing_eighths": RhythmicFeel.SWING_EIGHTHS,
    "swing-eighths": RhythmicFeel.SWING_EIGHTHS,
    "swing8": RhythmicFeel.SWING_EIGHTHS,
    "swing": RhythmicFeel.SWING_EIGHTHS,
    "swing_sixteenths": RhythmicFeel.SWING_SIXTEENTHS,
    "swing-sixteenths": RhythmicFeel.SWING_SIXTEENTHS,
    "swing16": RhythmicFeel.SWING_SIXTEENTHS,
    "shuffle": RhythmicFeel.SHUFFLE,
}

_TIMING_ALIASES = {
    "auto": TimingFeel.AUTO,
    "steady": TimingFeel.STEADY,
    "expressive": TimingFeel.EXPRESSIVE,
    "rubato": TimingFeel.EXPRESSIVE,
}

_OUTPUT_MODE_ALIASES = {
    "faithful": OutputMode.FAITHFUL,
    "simplified": OutputMode.SIMPLIFIED,
    "simplify": OutputMode.SIMPLIFIED,
}


class InterpretationProfileError(ValueError):
    """Invalid interpretation profile."""


def _enum_from(value, enum_cls, aliases, field_name):
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, enum_cls):
        return value
    key = str(value).strip().lower().replace(" ", "_")
    if key not in aliases:
        allowed = ", ".join(item.value for item in enum_cls)
        raise InterpretationProfileError(
            f"Unknown {field_name}={value!r}. Use {allowed}."
        )
    return aliases[key]


@dataclass(frozen=True)
class StylePrior:
    """Declarative weights. Higher favors that hypothesis; never a hard rule.

    Live production fields (used by ``mir.swing`` / onset search):
    ``straight``, ``swing_eighths``, ``swing_sixteenths``, ``shuffle``,
    ``dotted``, ``apply_margin``, ``min_observations``, ``min_confidence``.

    Reserved / unused in this milestone (do not present as implemented
    musical capabilities): ``triplet``, ``tempo_flexibility``,
    ``notation_complexity_penalty``, ``voice_independence``,
    ``syncopation_preservation``. ``output_mode=simplified`` applies a
    separate onset-cost nudge in ``performance_score``, not this last field.
    """

    straight: float = 0.55
    swing_eighths: float = 0.20
    swing_sixteenths: float = 0.10
    shuffle: float = 0.15
    triplet: float = 0.35
    dotted: float = 0.35
    tempo_flexibility: float = 0.55
    notation_complexity_penalty: float = 1.0
    voice_independence: float = 1.0
    syncopation_preservation: float = 1.0
    apply_margin: float = 0.18
    min_observations: int = 4
    min_confidence: float = 0.55

    @staticmethod
    def live_fields() -> tuple[str, ...]:
        return (
            "straight",
            "swing_eighths",
            "swing_sixteenths",
            "shuffle",
            "dotted",
            "apply_margin",
            "min_observations",
            "min_confidence",
        )


# Style is a prior, not a genre rule. AUTO infers feel from timing evidence
# and must succeed without the user choosing Jazz. Jazz does not always
# swing; classical is not strictly quantized; contemporary art is not
# assumed to be simple.
STYLE_PRIORS: dict[SourceStyle, StylePrior] = {
    SourceStyle.AUTO: StylePrior(),
    SourceStyle.JAZZ: StylePrior(
        straight=0.35,
        swing_eighths=0.55,
        swing_sixteenths=0.25,
        shuffle=0.35,
        triplet=0.40,
        dotted=0.30,
        tempo_flexibility=0.45,
        notation_complexity_penalty=1.15,
        voice_independence=1.15,
        syncopation_preservation=1.25,
        apply_margin=0.12,
        min_observations=3,
        min_confidence=0.48,
    ),
    SourceStyle.CLASSICAL: StylePrior(
        straight=0.80,
        swing_eighths=0.06,
        swing_sixteenths=0.04,
        shuffle=0.04,
        triplet=0.45,
        dotted=0.50,
        tempo_flexibility=0.85,
        notation_complexity_penalty=0.95,
        voice_independence=1.20,
        syncopation_preservation=1.10,
        apply_margin=0.28,
        min_observations=6,
        min_confidence=0.70,
    ),
    SourceStyle.POP_ROCK: StylePrior(
        straight=0.70,
        swing_eighths=0.22,
        swing_sixteenths=0.12,
        shuffle=0.35,
        triplet=0.25,
        dotted=0.40,
        tempo_flexibility=0.40,
        notation_complexity_penalty=1.20,
        voice_independence=1.00,
        syncopation_preservation=1.05,
        apply_margin=0.16,
        min_observations=4,
        min_confidence=0.55,
    ),
    SourceStyle.CONTEMPORARY_ART: StylePrior(
        straight=0.50,
        swing_eighths=0.08,
        swing_sixteenths=0.08,
        shuffle=0.06,
        triplet=0.50,
        dotted=0.45,
        tempo_flexibility=0.90,
        notation_complexity_penalty=0.70,
        voice_independence=1.25,
        syncopation_preservation=1.20,
        apply_margin=0.32,
        min_observations=8,
        min_confidence=0.75,
    ),
}


@dataclass(frozen=True)
class InterpretationProfile:
    version: int = INTERPRETATION_PROFILE_VERSION
    source_style: SourceStyle = SourceStyle.AUTO
    rhythmic_feel: RhythmicFeel = RhythmicFeel.AUTO
    timing: TimingFeel = TimingFeel.AUTO
    output_mode: OutputMode = OutputMode.FAITHFUL
    swing_ratio: float | None = None

    def __post_init__(self):
        if int(self.version) != INTERPRETATION_PROFILE_VERSION:
            raise InterpretationProfileError(
                f"Unknown interpretation profile version={self.version!r}."
            )
        if self.swing_ratio is not None:
            ratio = float(self.swing_ratio)
            if not (SWING_RATIO_MIN <= ratio <= SWING_RATIO_MAX):
                raise InterpretationProfileError(
                    f"swing_ratio must be between {SWING_RATIO_MIN} and {SWING_RATIO_MAX}."
                )
            object.__setattr__(self, "swing_ratio", ratio)

    def style_prior(self) -> StylePrior:
        return STYLE_PRIORS.get(self.source_style, STYLE_PRIORS[SourceStyle.AUTO])

    def is_default(self) -> bool:
        return (
            self.source_style == SourceStyle.AUTO
            and self.rhythmic_feel == RhythmicFeel.AUTO
            and self.timing == TimingFeel.AUTO
            and self.output_mode == OutputMode.FAITHFUL
            and self.swing_ratio is None
        )

    def user_feel_override(self) -> RhythmicFeel | None:
        if self.rhythmic_feel == RhythmicFeel.AUTO:
            return None
        return self.rhythmic_feel

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "source_style": self.source_style.value,
            "rhythmic_feel": self.rhythmic_feel.value,
            "timing": self.timing.value,
            "output_mode": self.output_mode.value,
            "swing_ratio": self.swing_ratio,
        }

    def replace(self, **changes) -> "InterpretationProfile":
        payload = self.to_dict()
        payload.update(changes)
        for key, enum_cls in (
            ("source_style", SourceStyle),
            ("rhythmic_feel", RhythmicFeel),
            ("timing", TimingFeel),
            ("output_mode", OutputMode),
        ):
            if key in changes and isinstance(changes[key], enum_cls):
                payload[key] = changes[key].value
        return InterpretationProfile.from_dict(payload)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None = None) -> "InterpretationProfile":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise InterpretationProfileError("Interpretation profile must be an object.")
        version = data.get("version", INTERPRETATION_PROFILE_VERSION)
        try:
            version = int(version)
        except (TypeError, ValueError) as exc:
            raise InterpretationProfileError("Invalid interpretation profile version.") from exc
        ratio = data.get("swing_ratio")
        if ratio == "":
            ratio = None
        if ratio is not None:
            try:
                ratio = float(ratio)
            except (TypeError, ValueError) as exc:
                raise InterpretationProfileError("Invalid swing_ratio.") from exc
        return cls(
            version=version,
            source_style=_enum_from(
                data.get("source_style", SourceStyle.AUTO),
                SourceStyle,
                _SOURCE_STYLE_ALIASES,
                "source_style",
            )
            or SourceStyle.AUTO,
            rhythmic_feel=_enum_from(
                data.get("rhythmic_feel", RhythmicFeel.AUTO),
                RhythmicFeel,
                _RHYTHMIC_FEEL_ALIASES,
                "rhythmic_feel",
            )
            or RhythmicFeel.AUTO,
            timing=_enum_from(
                data.get("timing", TimingFeel.AUTO),
                TimingFeel,
                _TIMING_ALIASES,
                "timing",
            )
            or TimingFeel.AUTO,
            output_mode=_enum_from(
                data.get("output_mode", OutputMode.FAITHFUL),
                OutputMode,
                _OUTPUT_MODE_ALIASES,
                "output_mode",
            )
            or OutputMode.FAITHFUL,
            swing_ratio=ratio,
        )


def default_interpretation_profile() -> InterpretationProfile:
    return InterpretationProfile()


def parse_interpretation_profile(
    value: InterpretationProfile | dict | None = None,
) -> InterpretationProfile:
    if value is None:
        return InterpretationProfile()
    if isinstance(value, InterpretationProfile):
        return value
    return InterpretationProfile.from_dict(value)
