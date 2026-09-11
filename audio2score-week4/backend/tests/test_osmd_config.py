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
    assert rules["PageLeftMargin"] == 8
    assert rules["MetronomeMarksDrawn"] is True
    assert "osmd.zoom = 0.75" in jsx
    assert (BACKEND / "evaluation" / "render_osmd.mjs").is_file()
