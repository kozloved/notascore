"""Export-quality evidence for rhythm preservation and trustworthy PDFs.

Uses fixture metadata and ingested tempo/meter. Does not import test helpers
that hard-code 4/4. Renders through the same OSMD config as the frontend
sheet preview, then the production frontend PDF export script.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET

from evaluation.notation_fixtures import FIXTURE_META, FIXTURES
from evaluation.readable_v2_cases import READABLE_V2_CASES
from mir.interpretation_context import InterpretationContext
from mir.midi_ingest import ingest_midi
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings
from timing.tempo_map import MusicalTimeMap

HERE = Path(__file__).resolve().parent
RENDER = HERE / "render_osmd.mjs"
FRONTEND = HERE.parent.parent / "frontend"
FRONTEND_SHEET = FRONTEND / "components" / "SheetResult.jsx"
EXPORT_PDF = FRONTEND / "scripts" / "export-sheet-pdf.mjs"

CASES = [
    ("detached_vs_short", "A_detached_regular_line", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("intentional_short_rests", "B_short_notes_with_rests", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("repeated_under_pedal", "C_repeated_attacks_under_pedal", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("held_inner_voice", "G_held_voice_same_staff", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("mixed_release_chord", "mixed_release_chord", FIXTURES, "notation", FIXTURE_META["mixed_release_chord"]),
    ("crossing_hands", "unison_crossing", FIXTURES, "notation", FIXTURE_META["unison_crossing"]),
    ("syncopation", "syncopation", FIXTURES, "notation", FIXTURE_META["syncopation"]),
    ("triplets", "mixed_tuplets", FIXTURES, "notation", FIXTURE_META["mixed_tuplets"]),
    ("meter_6_8", "meter_6_8", FIXTURES, "notation", FIXTURE_META["meter_6_8"]),
    ("multibar_tie", "multibar_held_melody", FIXTURES, "notation", FIXTURE_META["multibar_held_melody"]),
    ("marked_note", "mixed_tuplets", FIXTURES, "marked_note", FIXTURE_META["mixed_tuplets"]),
    ("mixed_chord_marks", "mixed_release_chord", FIXTURES, "mixed_chord", FIXTURE_META["mixed_release_chord"]),
]


def context_from_ingest(ingested, *, meter: str | None = None, display_bpm: float | None = None):
    """Interpretation context from ingested MIDI, not a 4/4 test helper."""
    notes = ingested.notes
    duration = max((n.end_time for n in notes), default=8.0)
    time_map = MusicalTimeMap.from_tempo_map(ingested.tempo_map, duration_sec=max(duration, 4.0))
    points = list(getattr(ingested.tempo_map, "points", None) or [])
    bpm = float(display_bpm) if display_bpm is not None else (
        float(points[0].bpm) if points else 120.0
    )
    selected = meter or ingested.time_sig_hint or "4/4"
    kind = notes[0].instrument if notes else "piano"
    instrument = kind.value if hasattr(kind, "value") else str(kind or "piano")
    return InterpretationContext(
        time_map=time_map,
        selected_meter=selected,
        key_name="C",
        display_bpm=bpm,
        accepted_source_note_ids=tuple(n.note_id for n in notes),
        has_recorded_selection=True,
        midi_sha256=ingested.performance.midi_sha256,
        source_backend="midi",
        instrument=instrument or "piano",
    )


def _settings(kind: str) -> NotationSettings:
    if kind == "readable_v2":
        return NotationSettings.readable_opt_in()
    return NotationSettings()


def _sid_for(result, *, pitch=None, start=None):
    for row in result.editor_model["notes"]:
        if pitch is not None and int(row["pitch"]) != int(pitch):
            continue
        if start is not None and abs(float(row["start"]) - float(start)) > 0.2:
            continue
        return row.get("source_note_id") or row["id"]
    if result.editor_model["notes"]:
        row = result.editor_model["notes"][0]
        return row.get("source_note_id") or row["id"]
    return None


def _build(path: Path, settings: NotationSettings, *, meter: str, tempo: float, corrections=None):
    ingested = ingest_midi(path)
    expected = meter
    actual = ingested.time_sig_hint or "4/4"
    if actual != expected:
        raise AssertionError(f"ingested meter {actual} != fixture metadata {expected}")
    context = context_from_ingest(ingested, meter=expected, display_bpm=tempo)
    if context.selected_meter != expected:
        raise AssertionError(f"context meter {context.selected_meter} != {expected}")
    return recompute_notation(
        midi_bytes=path.read_bytes(),
        settings=settings,
        performance=ingested.performance,
        context=context,
        corrections=corrections,
    ), ingested


def _render_osmd(xml_path: Path, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["node", str(RENDER), str(xml_path), str(out_dir)],
        capture_output=True,
        text=True,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "html": (out_dir / "osmd_preview.html").exists(),
        "png": (out_dir / "osmd.png").exists(),
        "svg": (out_dir / "osmd.svg").exists(),
    }


def _frontend_pdf(html_path: Path, pdf_path: Path) -> dict:
    """Call the production frontend export script (not a /tmp imitation)."""
    if not EXPORT_PDF.exists():
        return {
            "returncode": 2,
            "stdout": "",
            "stderr": f"missing {EXPORT_PDF}",
            "pdf": False,
        }
    proc = subprocess.run(
        ["node", str(EXPORT_PDF), str(html_path), str(pdf_path)],
        cwd=str(FRONTEND),
        capture_output=True,
        text=True,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "pdf": pdf_path.exists(),
    }


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def musicxml_note_marks(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    rows = []
    measure_number = 0
    for el in root.iter():
        name = _local(el.tag)
        if name == "measure":
            measure_number = int(el.get("number") or measure_number + 1)
        if name != "note":
            continue
        if el.find(".//{*}rest") is not None:
            continue
        arts = tuple(
            sorted(
                _local(child.tag)
                for arts in el.findall(".//{*}articulations")
                for child in list(arts)
            )
        )
        ties = tuple(t.get("type") for t in el.findall("{*}tie") if t.get("type"))
        actual = el.find(".//{*}actual-notes")
        normal = el.find(".//{*}normal-notes")
        rows.append(
            {
                "measure": measure_number,
                "articulations": arts,
                "tie": ties[-1] if ties else None,
                "tuplet": (
                    int(actual.text or 0),
                    int(normal.text or 0),
                )
                if actual is not None and normal is not None
                else None,
                "chord": el.find("{*}chord") is not None,
            }
        )
    return rows


def inspect_xml(xml_text: str) -> dict:
    rows = musicxml_note_marks(xml_text)
    signatures = []
    beats = []
    empty_trailing = 0
    root = ET.fromstring(xml_text)
    measures = [el for el in root.iter() if _local(el.tag) == "measure"]
    for measure in measures:
        ts = measure.find("{*}time") or measure.find(".//{*}time")
        if ts is not None:
            beats_el = ts.find("{*}beats")
            beat_type = ts.find("{*}beat-type")
            if beats_el is not None and beat_type is not None:
                signatures.append(f"{beats_el.text}/{beat_type.text}")
        sounding = [
            note
            for note in measure.findall("{*}note")
            if note.find("{*}rest") is None and note.find(".//{*}rest") is None
        ]
        beats.append(len(sounding))
    while beats and beats[-1] == 0:
        empty_trailing += 1
        beats.pop()
    parts = [el for el in root.iter() if _local(el.tag) == "score-part"]
    return {
        "printed_notes": len(rows),
        "tied_fragments": len([row for row in rows if row["tie"]]),
        "marked_notes": len([row for row in rows if row["articulations"]]),
        "tuplet_notes": len([row for row in rows if row["tuplet"]]),
        "mixed_chord_marks": any(
            row["chord"] and row["articulations"] for row in rows
        ),
        "shape": {
            "part_count": max(1, len(parts)),
            "time_signatures": signatures,
            "measure_count": len(measures),
            "trailing_empty_measures": empty_trailing,
        },
    }


def _corrections_for(kind: str, auto) -> list[dict] | None:
    notes = auto.editor_model["notes"]
    if kind == "marked_note":
        sid = _sid_for(auto, start=0)
        return [{"source_note_id": sid, "articulation": "tenuto"}] if sid else None
    if kind == "mixed_chord":
        by_pitch = {int(n["pitch"]): n for n in notes if abs(float(n["start"])) < 0.2}
        c5 = by_pitch.get(60)
        e5 = by_pitch.get(64)
        if not c5 or not e5:
            return None
        return [
            {"source_note_id": c5.get("source_note_id") or c5["id"], "articulation": "staccato"},
            {"source_note_id": e5.get("source_note_id") or e5["id"], "articulation": "tenuto"},
        ]
    sid = _sid_for(auto)
    return [{"source_note_id": sid, "velocity": 108}] if sid else None


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "frontend_sheet": str(FRONTEND_SHEET),
        "frontend_pdf_script": str(EXPORT_PDF),
        "osmd_config": str(HERE / "osmd_config.json"),
        "evidence_kind": "synthetic_midi",
        "real_audio_evidence": False,
        "cases": [],
        "pdf_path_available": False,
        "blocked": [],
    }
    for label, name, catalog, kind, meta in CASES:
        case_dir = out_dir / label
        case_dir.mkdir(parents=True, exist_ok=True)
        midi_path = case_dir / f"{name}.mid"
        catalog[name](midi_path)
        original = midi_path.read_bytes()
        settings = _settings(kind)
        meter = str(meta["meter"])
        tempo = float(meta["tempo"])
        auto, ingested = _build(midi_path, settings, meter=meter, tempo=tempo)
        assert midi_path.read_bytes() == original
        exported_meter = inspect_xml(auto.musicxml)["shape"]["time_signatures"]
        if meter not in exported_meter and exported_meter:
            raise AssertionError(
                f"{label} expected exported meter {meter}, got {exported_meter}"
            )
        if meter not in exported_meter:
            raise AssertionError(f"{label} exported no time signature; expected {meter}")
        (case_dir / "automatic.musicxml").write_text(auto.musicxml, encoding="utf-8")
        corrections = _corrections_for(kind, auto)
        edited = auto
        if corrections:
            edited, _ = _build(
                midi_path, settings, meter=meter, tempo=tempo, corrections=corrections
            )
            assert midi_path.read_bytes() == original
            (case_dir / "after_unrelated_edit.musicxml").write_text(
                edited.musicxml, encoding="utf-8"
            )
        auto_render = _render_osmd(case_dir / "automatic.musicxml", case_dir / "automatic_osmd")
        edited_render = {"skipped": True}
        if corrections:
            edited_render = _render_osmd(
                case_dir / "after_unrelated_edit.musicxml",
                case_dir / "edited_osmd",
            )
        pdf_auto = {"skipped": True}
        pdf_edited = {"skipped": True}
        html_auto = case_dir / "automatic_osmd" / "osmd_preview.html"
        if html_auto.exists():
            pdf_auto = _frontend_pdf(html_auto, case_dir / "automatic_sheetresult.pdf")
            if pdf_auto.get("pdf"):
                report["pdf_path_available"] = True
            elif "Cannot find module" in (pdf_auto.get("stderr") or "") or pdf_auto.get("returncode"):
                report["blocked"].append(
                    {
                        "case": label,
                        "reason": "Frontend PDF path blocked",
                        "detail": (pdf_auto.get("stderr") or pdf_auto.get("stdout") or "")[:400],
                    }
                )
        html_edited = case_dir / "edited_osmd" / "osmd_preview.html"
        if html_edited.exists():
            pdf_edited = _frontend_pdf(html_edited, case_dir / "after_unrelated_edit_sheetresult.pdf")
            if pdf_edited.get("pdf"):
                report["pdf_path_available"] = True
        auto_inspect = inspect_xml(auto.musicxml)
        edited_inspect = inspect_xml(edited.musicxml)
        trailing = auto_inspect["shape"]["trailing_empty_measures"]
        if trailing:
            report.setdefault("trailing_empty_measures", []).append(
                {
                    "case": label,
                    "count": trailing,
                    "note": (
                        "Reported only. Intentional silence and musical duration "
                        "were left unchanged."
                    ),
                }
            )
        report["cases"].append(
            {
                "label": label,
                "fixture": name,
                "kind": kind,
                "expected_meter": meter,
                "ingested_meter": ingested.time_sig_hint,
                "exported_meter": auto_inspect["shape"]["time_signatures"],
                "settings": settings.to_dict(),
                "midi_sha256": hashlib.sha256(original).hexdigest(),
                "performance_sha256": ingested.performance.midi_sha256,
                "source_midi_unchanged": midi_path.read_bytes() == original,
                "automatic": auto_inspect,
                "edited": edited_inspect,
                "edited_same_meter": auto_inspect["shape"]["time_signatures"]
                == edited_inspect["shape"]["time_signatures"],
                "osmd_automatic": {
                    key: auto_render[key]
                    for key in ("returncode", "html", "png", "svg")
                },
                "osmd_edited": {
                    key: edited_render.get(key)
                    for key in ("returncode", "html", "png", "svg", "skipped")
                    if key in edited_render
                },
                "pdf_automatic": {
                    key: pdf_auto.get(key)
                    for key in ("returncode", "pdf", "skipped")
                    if key in pdf_auto
                },
                "pdf_after_unrelated_edit": {
                    key: pdf_edited.get(key)
                    for key in ("returncode", "pdf", "skipped")
                    if key in pdf_edited
                },
            }
        )
    (out_dir / "evidence_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    import sys

    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/opt/cursor/artifacts/notation_evidence")
    run(dest)
    print(f"wrote {dest / 'evidence_report.json'}")
