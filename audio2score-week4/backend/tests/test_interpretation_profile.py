from mir.interpretation_profile import (
    INTERPRETATION_PROFILE_VERSION,
    InterpretationProfile,
    InterpretationProfileError,
    RhythmicFeel,
    SourceStyle,
)
from mir.notation_settings import (
    NotationSettings,
    NotationSettingsError,
    merge_notation_settings,
    parse_notation_settings,
)
import pytest


def test_defaults_keep_legacy_requests_compatible():
    settings = NotationSettings()
    assert settings.interpretation_profile.version == INTERPRETATION_PROFILE_VERSION
    assert settings.interpretation_profile.source_style == SourceStyle.AUTO
    assert settings.interpretation_profile.is_default() is True
    parsed = parse_notation_settings({})
    assert parsed.interpretation_profile.is_default() is True
    assert parse_notation_settings(settings.to_dict()).to_dict() == settings.to_dict()


def test_old_payload_without_profile_still_parses():
    settings = parse_notation_settings(
        {
            "display_grid": "auto",
            "interpretation": "readable",
            "algorithm_version": "performance-score-1",
        }
    )
    assert settings.interpretation_profile.rhythmic_feel == RhythmicFeel.AUTO
    assert settings.interpretation_profile.swing_ratio is None


def test_cache_key_includes_profile():
    base = NotationSettings()
    jazz = NotationSettings.from_dict({"source_style": "jazz", "rhythmic_feel": "swing_eighths"})
    assert base.cache_key("abc") != jazz.cache_key("abc")
    assert jazz.interpretation_profile.source_style == SourceStyle.JAZZ


def test_invalid_style_and_ratio_rejected():
    with pytest.raises(NotationSettingsError):
        parse_notation_settings({"source_style": "baroque"})
    with pytest.raises(NotationSettingsError):
        parse_notation_settings({"swing_ratio": 9})
    with pytest.raises(InterpretationProfileError):
        InterpretationProfile.from_dict({"rhythmic_feel": "waltz"})


def test_merge_overrides_and_clears_ratio():
    current = NotationSettings.from_dict(
        {"source_style": "jazz", "rhythmic_feel": "auto", "swing_ratio": 2.0}
    )
    patched = merge_notation_settings(
        current, {"rhythmic_feel": "straight"}, fields_set={"rhythmic_feel"}
    )
    assert patched.interpretation_profile.rhythmic_feel == RhythmicFeel.STRAIGHT
    assert patched.interpretation_profile.source_style == SourceStyle.JAZZ
    assert patched.interpretation_profile.swing_ratio == 2.0
    cleared = merge_notation_settings(
        patched, {"swing_ratio": None}, fields_set={"swing_ratio"}
    )
    assert cleared.interpretation_profile.swing_ratio is None
    nested = merge_notation_settings(
        cleared,
        {"interpretation_profile": {"source_style": "classical", "rhythmic_feel": "auto"}},
        fields_set={"interpretation_profile"},
    )
    assert nested.interpretation_profile.source_style == SourceStyle.CLASSICAL
