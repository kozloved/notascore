"""OSMD QA config must match the production frontend renderer."""

import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CONFIG = BACKEND / "evaluation" / "osmd_config.json"
SHEET = BACKEND.parent / "frontend" / "components" / "SheetResult.jsx"


def test_osmd_config_matches_sheet_result():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    jsx = SHEET.read_text(encoding="utf-8")
    constructor = cfg["constructor"]
    assert constructor["backend"] == "svg"
    assert constructor["drawingParameters"] == "compact"
    assert constructor["alignRests"] == 2
    assert constructor["pageFormat"] == "A4_P"
    assert cfg["zoom"] == 0.75
    for key, value in constructor.items():
        if isinstance(value, bool):
            token = "true" if value else "false"
            assert re.search(rf"{key}:\s*{token}", jsx)
        elif isinstance(value, str):
            assert f'{key}: "{value}"' in jsx or f"{key}: '{value}'" in jsx
        elif key == "alignRests":
            assert "alignRests: 2" in jsx
    rules = cfg["engravingRules"]
    numeric = {
        "PageLeftMargin": 10,
        "PageRightMargin": 10,
        "PageTopMargin": 10,
        "PageBottomMargin": 10,
        "StaffDistance": 4.0,
        "BetweenStaffDistance": 2.8,
        "MinimumDistanceBetweenSystems": 3.2,
        "SystemDistance": 3.2,
        "MeasureNumberLabelOffset": 1.5,
        "MeasureNumberLabelXOffset": 0.4,
    }
    for key, value in numeric.items():
        assert rules[key] == value
        assert re.search(rf"{key}\s*=\s*{value}\b", jsx)
    assert rules["MetronomeMarksDrawn"] is True
    assert rules["RenderMeasureNumbersOnlyAtSystemStart"] is True
    assert "drawMeasureNumbersOnlyAtSystemStart: true" in jsx
    assert "osmd.zoom = 0.75" in jsx
    assert (BACKEND / "evaluation" / "render_osmd.mjs").is_file()
    assert (BACKEND / "evaluation" / "osmd_mixed_chord_mre.musicxml").is_file()
