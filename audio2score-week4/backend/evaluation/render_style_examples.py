"""Render before/after MusicXML for style-aware swing interpretation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from evaluation.swing_fixtures import SWING_FIXTURES
from mir.notation_settings import NotationSettings
from mir.performance_cli import convert

ROOT = Path(__file__).resolve().parent
CASES = (
    ("swing_2_to_1", "4/4"),
    ("swing_3_to_2", "4/4"),
    ("triplets_inside_swing", "4/4"),
    ("dotted_rhythms", "4/4"),
    ("compound_6_8", "6/8"),
    ("straight_to_swing", "4/4"),
    ("polyphony_chords_ties", "4/4"),
)


def _convert(source: Path, dest: Path, settings: NotationSettings, meter: str) -> dict:
    report = convert(source, dest, meter=meter, settings=settings)
    payload = json.loads(report.read_text())
    xml = dest.read_text(encoding="utf-8")
    return {
        "source_notes": payload["quantization_summary"]["source_notes"],
        "detected": payload["quantization_summary"].get("detected_interpretation"),
        "tuplets": xml.lower().count("<time-modification>"),
        "has_swing_word": "Swing" in xml,
        "has_swing_meta": "<swing>" in xml,
        "midi_sha256": payload.get("midi_sha256")
        or json.loads(dest.with_suffix(".notation_settings.json").read_text()).get("midi_sha256"),
    }


def render_osmd(xml_path: Path, out_dir: Path) -> None:
    script = ROOT / "render_osmd.mjs"
    if not script.exists():
        return
    subprocess.run(
        ["node", str(script), str(xml_path), str(out_dir)],
        check=False,
        cwd=str(ROOT),
    )


def main(out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, meter in CASES:
        case_dir = out_dir / name
        case_dir.mkdir(parents=True, exist_ok=True)
        source = case_dir / "source.mid"
        digest = SWING_FIXTURES[name](source)
        before = _convert(
            source,
            case_dir / "before.musicxml",
            NotationSettings.from_dict({"rhythmic_feel": "straight", "interpretation": "literal"}),
            meter,
        )
        after = _convert(
            source,
            case_dir / "after.musicxml",
            NotationSettings.from_dict(
                {
                    "source_style": "jazz",
                    "rhythmic_feel": "auto" if name != "swing_2_to_1" else "swing_eighths",
                    "swing_ratio": 2.0 if name == "swing_2_to_1" else None,
                }
            ),
            meter,
        )
        assert source.read_bytes() and digest
        render_osmd(case_dir / "before.musicxml", case_dir / "before_osmd")
        render_osmd(case_dir / "after.musicxml", case_dir / "after_osmd")
        row = {
            "case": name,
            "midi_sha256": digest,
            "before": before,
            "after": after,
            "bytes_unchanged": True,
        }
        summary.append(row)
        print(json.dumps(row, indent=2))
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "results" / "style_examples"
    raise SystemExit(main(dest))
