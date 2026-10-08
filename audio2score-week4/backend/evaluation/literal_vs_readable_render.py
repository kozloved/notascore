"""Render the same MIDI in Literal and Readable through OSMD + PDF export.

Expected notation is specified independently of symbol count. Fewer rests or
ties are not treated as automatically better.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from evaluation.notation_correctness_evidence import (
    _build,
    _frontend_pdf,
    _render_osmd,
    inspect_xml,
    measure_validity,
)
from evaluation.notation_fixtures import FIXTURE_META, FIXTURES
from evaluation.readable_v2_cases import EXPECTED_NOTATION, READABLE_V2_CASES
from mir.notation_settings import NotationSettings

HERE = Path(__file__).resolve().parent
NOTA_SAMPLES = HERE / "development" / "NotaTestSamples"

PAIRS = [
    {
        "id": "A_detached_regular_line",
        "builder": READABLE_V2_CASES["A_detached_regular_line"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["A_detached_regular_line"],
    },
    {
        "id": "B_short_notes_with_rests",
        "builder": READABLE_V2_CASES["B_short_notes_with_rests"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["B_short_notes_with_rests"],
    },
    {
        "id": "humanized_ceg_chord",
        "builder": READABLE_V2_CASES["humanized_ceg_chord"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["humanized_ceg_chord"],
    },
    {
        "id": "rapid_sixteenth_run",
        "builder": READABLE_V2_CASES["rapid_sixteenth_run"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["rapid_sixteenth_run"],
    },
    {
        "id": "early_release_whole",
        "builder": READABLE_V2_CASES["early_release_whole"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["early_release_whole"],
    },
    {
        "id": "uneven_chord_releases",
        "builder": READABLE_V2_CASES["uneven_chord_releases"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["uneven_chord_releases"],
    },
    {
        "id": "mixed_release_quarters",
        "builder": READABLE_V2_CASES["mixed_release_quarters"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["mixed_release_quarters"],
    },
    {
        "id": "mixed_release_chords",
        "builder": READABLE_V2_CASES["mixed_release_chords"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["mixed_release_chords"],
    },
    {
        "id": "short_chords_with_rests",
        "builder": READABLE_V2_CASES["short_chords_with_rests"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["short_chords_with_rests"],
    },
    {
        "id": "hold_under_mixed_release_chords",
        "builder": READABLE_V2_CASES["hold_under_mixed_release_chords"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["hold_under_mixed_release_chords"],
    },
    {
        "id": "literal_measure_then_readable",
        "builder": READABLE_V2_CASES["mixed_release_quarters"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["literal_measure_then_readable"],
        "extra_modes": [
            (
                "literal_m1_readable_m2",
                NotationSettings.from_dict(
                    {
                        "interpretation": "readable",
                        "measure_overrides": [
                            {
                                "start_measure": 1,
                                "end_measure": 1,
                                "interpretation": "literal",
                            }
                        ],
                    }
                ),
            )
        ],
    },
    {
        "id": "isolated_rest_in_phrase",
        "builder": READABLE_V2_CASES["isolated_rest_in_phrase"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["isolated_rest_in_phrase"],
    },
    {
        "id": "strongly_detached_quarters",
        "builder": READABLE_V2_CASES["strongly_detached_quarters"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["strongly_detached_quarters"],
    },
    {
        "id": "strongly_detached_chords",
        "builder": READABLE_V2_CASES["strongly_detached_chords"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["strongly_detached_chords"],
    },
    {
        "id": "detached_bass_chord_pulse",
        "builder": READABLE_V2_CASES["detached_bass_chord_pulse"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["detached_bass_chord_pulse"],
    },
    {
        "id": "detached_phrase_with_pause",
        "builder": READABLE_V2_CASES["detached_phrase_with_pause"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["detached_phrase_with_pause"],
    },
    {
        "id": "hold_under_strongly_detached",
        "builder": READABLE_V2_CASES["hold_under_strongly_detached"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["hold_under_strongly_detached"],
    },
    {
        "id": "ambiguous_five_shorts",
        "builder": READABLE_V2_CASES["ambiguous_five_shorts"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["ambiguous_five_shorts"],
    },
    {
        "id": "G_held_voice_same_staff",
        "builder": READABLE_V2_CASES["G_held_voice_same_staff"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["G_held_voice_same_staff"],
    },
    {
        "id": "syncopation",
        "builder": FIXTURES["syncopation"],
        "meter": FIXTURE_META["syncopation"]["meter"],
        "tempo": float(FIXTURE_META["syncopation"]["tempo"]),
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION.get(
            "syncopation",
            {
                "onset": "Off-beat quarters crossing beats, then a sustain over the barline.",
                "release": "Keep the syncopation. Do not snap onto the beat.",
                "engraving": "Readable may fill the last sustain; onsets stay off the beat.",
            },
        ),
    },
    {
        "id": "meter_3_4",
        "builder": FIXTURES["meter_3_4"],
        "meter": "3/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": {
            "onset": "Six successive quarter attacks in 3/4.",
            "release": "Readable writes quarters; Literal may keep short releases.",
            "engraving": "Two bars of 3/4. Do not flatten into 4/4.",
        },
    },
    {
        "id": "meter_6_8",
        "builder": FIXTURES["meter_6_8"],
        "meter": "6/8",
        "tempo": 90.0,
        "kind": "synthetic",
        "expected": {
            "onset": "Four dotted-quarter attacks in 6/8.",
            "release": "Keep compound pulse. Do not rewrite as 3/4 quarters.",
            "engraving": "Compound meter stays 6/8.",
        },
    },
    {
        "id": "mixed_tuplets",
        "builder": FIXTURES["mixed_tuplets"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": EXPECTED_NOTATION["mixed_tuplets"],
    },
    {
        "id": "rubato_pickup",
        "builder": FIXTURES["rubato_pickup"],
        "meter": "4/4",
        "tempo": 120.0,
        "kind": "synthetic",
        "expected": {
            "onset": "Pickup eighth then quarters with a slowing tempo map.",
            "release": "Pickup survives. Printed tempo density must not drop playback tempo.",
            "engraving": "Keep the anacrusis distinct from bar 1.",
        },
    },
]


def _crop_png(src: Path, dest: Path, *, pad: int = 16) -> bool:
    if not src.exists():
        return False
    try:
        from PIL import Image
    except ImportError:
        shutil.copy2(src, dest)
        return True
    image = Image.open(src).convert("RGB")
    pixels = image.load()
    width, height = image.size
    bg = pixels[0, 0]
    def is_bg(px):
        return all(abs(px[i] - bg[i]) <= 12 for i in range(3))
    left, top, right, bottom = width, height, 0, 0
    found = False
    for y in range(height):
        for x in range(width):
            if not is_bg(pixels[x, y]):
                found = True
                if x < left:
                    left = x
                if y < top:
                    top = y
                if x > right:
                    right = x
                if y > bottom:
                    bottom = y
    if not found:
        shutil.copy2(src, dest)
        return True
    box = (
        max(0, left - pad),
        max(0, top - pad),
        min(width, right + 1 + pad),
        min(height, bottom + 1 + pad),
    )
    image.crop(box).save(dest)
    return True


def _mode_record(result, midi_sha: str) -> dict:
    xml = result.musicxml
    notes = result.editor_model.get("notes") or []
    return {
        "interpretation": result.settings.interpretation.value
        if hasattr(result.settings.interpretation, "value")
        else str(result.settings.interpretation),
        "algorithm_version": result.settings.algorithm_version,
        "cache_key": result.cache_key,
        "midi_sha256": result.midi_sha256,
        "source_midi_unchanged": result.midi_sha256 == midi_sha,
        "score_midi_sha256": hashlib.sha256(result.score_midi or b"").hexdigest()
        if result.score_midi
        else None,
        "note_count": len(notes),
        "durations": sorted({round(float(n["duration"]), 4) for n in notes}),
        "onsets": sorted({round(float(n["start"]), 4) for n in notes}),
        "xml": inspect_xml(xml),
        "validity": measure_validity(xml),
    }


def render_pair(spec: dict, out_dir: Path) -> dict:
    case_dir = out_dir / spec["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    midi_path = case_dir / "input.mid"
    spec["builder"](midi_path)
    original = midi_path.read_bytes()
    midi_sha = hashlib.sha256(original).hexdigest()
    literal, _ = _build(
        midi_path, NotationSettings.literal(), meter=spec["meter"], tempo=spec["tempo"]
    )
    readable, _ = _build(
        midi_path, NotationSettings(), meter=spec["meter"], tempo=spec["tempo"]
    )
    assert midi_path.read_bytes() == original
    results = [("literal", literal), ("readable", readable)]
    extra_records = {}
    for label, extra_settings in spec.get("extra_modes") or ():
        extra, _ = _build(
            midi_path, extra_settings, meter=spec["meter"], tempo=spec["tempo"]
        )
        assert midi_path.read_bytes() == original
        results.append((label, extra))
        extra_records[label] = _mode_record(extra, midi_sha)
    renders = {}
    for label, result in results:
        xml_path = case_dir / f"{label}.musicxml"
        xml_path.write_text(result.musicxml, encoding="utf-8")
        osmd_dir = case_dir / f"{label}_osmd"
        osmd = _render_osmd(xml_path, osmd_dir)
        html = osmd_dir / "osmd_preview.html"
        pdf_path = case_dir / f"{label}_sheetresult.pdf"
        pdf = {"pdf": False, "returncode": 2, "stderr": "missing html"}
        if html.exists():
            pdf = _frontend_pdf(html, pdf_path)
        png = osmd_dir / "osmd.png"
        crop = case_dir / f"{label}_crop.png"
        cropped = _crop_png(png, crop) if png.exists() else False
        renders[label] = {
            "osmd": {key: osmd.get(key) for key in ("returncode", "html", "png", "svg")},
            "pdf": {"ok": bool(pdf.get("pdf")), "path": str(pdf_path) if pdf_path.exists() else None},
            "crop": str(crop) if cropped and crop.exists() else None,
        }
    report = {
        "id": spec["id"],
        "kind": spec["kind"],
        "meter": spec["meter"],
        "expected": spec["expected"],
        "midi_sha256": midi_sha,
        "literal": _mode_record(literal, midi_sha),
        "readable": _mode_record(readable, midi_sha),
        "renders": renders,
        "cache_keys_differ": literal.cache_key != readable.cache_key,
    }
    report.update(extra_records)
    return report


def development_midi() -> list[dict]:
    rows = []
    if not NOTA_SAMPLES.exists():
        return rows
    for path in sorted(NOTA_SAMPLES.rglob("*_raw.mid")):
        rows.append(
            {
                "id": f"dev_{path.stem}",
                "path": path,
                "meter": "4/4",
                "tempo": 120.0,
                "kind": "development_midi",
                "expected": {
                    "onset": "Undocumented development MIDI, not musician-validated.",
                    "release": "Readable should be cleaner without erasing musical structure.",
                    "engraving": "Printed-lane / duration changes are not quality proof.",
                },
            }
        )
    return rows


def render_midi_path(path: Path, spec: dict, out_dir: Path) -> dict:
    case_dir = out_dir / spec["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    midi_path = case_dir / "input.mid"
    shutil.copy2(path, midi_path)
    original = midi_path.read_bytes()
    midi_sha = hashlib.sha256(original).hexdigest()
    from mir.midi_ingest import ingest_midi

    ingested = ingest_midi(midi_path)
    meter = ingested.time_sig_hint or spec["meter"]
    points = list(getattr(ingested.tempo_map, "points", None) or [])
    tempo = float(points[0].bpm) if points else spec["tempo"]
    literal, _ = _build(midi_path, NotationSettings.literal(), meter=meter, tempo=tempo)
    readable, _ = _build(midi_path, NotationSettings(), meter=meter, tempo=tempo)
    assert midi_path.read_bytes() == original
    renders = {}
    for label, result in (("literal", literal), ("readable", readable)):
        xml_path = case_dir / f"{label}.musicxml"
        xml_path.write_text(result.musicxml, encoding="utf-8")
        osmd_dir = case_dir / f"{label}_osmd"
        osmd = _render_osmd(xml_path, osmd_dir)
        html = osmd_dir / "osmd_preview.html"
        pdf_path = case_dir / f"{label}_sheetresult.pdf"
        pdf = {"pdf": False}
        if html.exists():
            pdf = _frontend_pdf(html, pdf_path)
        png = osmd_dir / "osmd.png"
        crop = case_dir / f"{label}_crop.png"
        cropped = _crop_png(png, crop) if png.exists() else False
        renders[label] = {
            "osmd": {key: osmd.get(key) for key in ("returncode", "html", "png", "svg")},
            "pdf": {"ok": bool(pdf.get("pdf"))},
            "crop": str(crop) if cropped and crop.exists() else None,
        }
    return {
        "id": spec["id"],
        "kind": spec["kind"],
        "meter": meter,
        "expected": spec["expected"],
        "midi_sha256": midi_sha,
        "literal": _mode_record(literal, midi_sha),
        "readable": _mode_record(readable, midi_sha),
        "renders": renders,
        "cache_keys_differ": literal.cache_key != readable.cache_key,
    }


def copy_artifacts(report: dict, artifacts: Path) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    for row in report["cases"]:
        case_id = row["id"]
        case_dir = Path(report["out_dir"]) / case_id
        for mode in row.get("renders") or ("literal", "readable"):
            crop = case_dir / f"{mode}_crop.png"
            pdf = case_dir / f"{mode}_sheetresult.pdf"
            png = case_dir / f"{mode}_osmd" / "osmd.png"
            if crop.exists():
                shutil.copy2(crop, artifacts / f"lvr_{case_id}_{mode}_crop.png")
            if png.exists():
                shutil.copy2(png, artifacts / f"lvr_{case_id}_{mode}.png")
            if pdf.exists():
                shutil.copy2(pdf, artifacts / f"lvr_{case_id}_{mode}.pdf")
    (artifacts / "lvr_literal_vs_readable.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )


def run(out_dir: Path, *, include_dev: bool = True, artifacts: Path | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for spec in PAIRS:
        cases.append(render_pair(spec, out_dir))
    if include_dev:
        for spec in development_midi():
            cases.append(render_midi_path(spec["path"], spec, out_dir))
    report = {
        "evidence_kind": "literal_vs_readable_osmd_pdf",
        "note": (
            "Same MIDI, two user-facing modes, production OSMD + frontend PDF. "
            "Expected notation is specified independently. Fewer symbols are not "
            "automatically better. Development MIDI is undocumented."
        ),
        "out_dir": str(out_dir),
        "cases": cases,
    }
    (out_dir / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if artifacts is not None:
        copy_artifacts(report, artifacts)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=HERE / "results" / "literal_vs_readable")
    parser.add_argument("--artifacts", type=Path, default=None)
    parser.add_argument("--no-dev", action="store_true")
    args = parser.parse_args(argv)
    run(args.out, include_dev=not args.no_dev, artifacts=args.artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
