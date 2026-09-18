from mir.notation_settings import (
    ALGORITHM_VERSION_CURRENT,
    ALGORITHM_VERSION_READABLE,
    DisplayGrid,
    Interpretation,
    NotationSettings,
    NotationSettingsError,
    merge_notation_settings,
    parse_notation_settings,
)
import pytest


def test_defaults_match_current_engine():
    settings = NotationSettings()
    assert settings.display_grid == DisplayGrid.AUTO
    assert settings.triplet_policy.value == "auto"
    assert settings.interpretation == Interpretation.READABLE
    assert settings.syncopation.value == "preserve"
    assert settings.overlap_handling.value == "contextual"
    assert settings.max_dots == 1
    assert settings.algorithm_version == ALGORITHM_VERSION_CURRENT
    assert settings.uses_current_vocabulary() is True
    assert settings.uses_improved_readable() is False


def test_contradictory_overrides_are_rejected():
    with pytest.raises(NotationSettingsError, match="Contradictory display_grid"):
        NotationSettings.from_dict(
            {
                "measure_overrides": [
                    {"start_measure": 1, "end_measure": 4, "display_grid": "eighth"},
                    {"start_measure": 3, "end_measure": 6, "display_grid": "sixteenth"},
                ]
            }
        )


def test_compatible_overrides_merge():
    settings = NotationSettings.from_dict(
        {
            "measure_overrides": [
                {"start_measure": 1, "end_measure": 4, "display_grid": "eighth"},
                {"start_measure": 3, "end_measure": 6, "triplet_policy": "disabled"},
            ]
        }
    )
    m3 = settings.resolved_for_measure(3)
    assert m3.display_grid == DisplayGrid.EIGHTH
    assert m3.triplet_policy.value == "disabled"
    m5 = settings.resolved_for_measure(5)
    assert m5.display_grid == DisplayGrid.AUTO
    assert m5.triplet_policy.value == "disabled"


def test_cache_key_includes_algorithm_and_settings():
    a = NotationSettings()
    b = NotationSettings.readable_opt_in()
    assert a.cache_key("abc") != b.cache_key("abc")
    assert a.cache_key("abc") != a.cache_key("def")
    assert a.algorithm_version == ALGORITHM_VERSION_CURRENT
    assert b.algorithm_version == ALGORITHM_VERSION_READABLE
    assert parse_notation_settings(a.to_dict()).to_dict() == a.to_dict()


def test_unknown_fields_are_rejected():
    with pytest.raises(NotationSettingsError, match="display_grid"):
        parse_notation_settings({"display_grid": "sixty-fourth"})
    with pytest.raises(NotationSettingsError, match="algorithm_version"):
        parse_notation_settings({"algorithm_version": "not-a-version"})


def test_pickup_and_downbeat_must_agree():
    with pytest.raises(NotationSettingsError, match="disagree"):
        parse_notation_settings(
            {
                "meter": "4/4",
                "pickup_beats": 1.0,
                "first_downbeat_beat": 0.5,
            }
        )
    settings = parse_notation_settings(
        {"meter": "4/4", "pickup_beats": 1.0, "first_downbeat_beat": 5.0}
    )
    assert settings.pickup_beats == 1.0


def test_partial_settings_preserve_clear_and_replace():
    current = NotationSettings.from_dict(
        {
            "interpretation": "literal",
            "meter": "4/4",
            "pickup_beats": 1.0,
            "display_grid": "eighth",
        }
    )
    preserved = merge_notation_settings(
        current, {"display_grid": "sixteenth"}, fields_set={"display_grid"}
    )
    assert preserved.display_grid == DisplayGrid.SIXTEENTH
    assert preserved.interpretation == Interpretation.LITERAL
    assert preserved.meter == "4/4"
    assert preserved.pickup_beats == 1.0
    cleared = merge_notation_settings(
        preserved, {"pickup_beats": None}, fields_set={"pickup_beats"}
    )
    assert cleared.pickup_beats is None
    assert cleared.meter == "4/4"
    replaced = merge_notation_settings(
        cleared, {"meter": "6/8"}, fields_set={"meter"}
    )
    assert replaced.meter == "6/8"
    with pytest.raises(NotationSettingsError, match="cannot be cleared"):
        merge_notation_settings(
            replaced, {"interpretation": None}, fields_set={"interpretation"}
        )
