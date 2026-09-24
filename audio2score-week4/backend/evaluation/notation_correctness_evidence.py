"""Export-quality evidence for rhythm preservation and trustworthy PDFs.

Uses fixture metadata and ingested tempo/meter. Does not import test helpers
that hard-code 4/4. Renders through the same OSMD config as the frontend
sheet preview, then the production frontend PDF export script.
"""

from __future__ import annotations

import hashlib
import json
import re
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

ARTICULATION_CHANGE_KINDS = frozenset({"marked_note", "mixed_chord"})

CASES = [
    ("detached_vs_short", "A_detached_regular_line", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("intentional_short_rests", "B_short_notes_with_rests", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("repeated_under_pedal", "C_repeated_attacks_under_pedal", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("held_inner_voice", "G_held_voice_same_staff", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("detached_triplet_groups", "I_detached_triplet_groups", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("intentional_short_triplet_rests", "J_intentional_short_triplet_rests", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("repeated_triplet_pitches", "K_repeated_triplet_pitches", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("held_voice_under_triplets", "L_held_voice_under_triplets", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}),
    ("mixed_release_chord", "mixed_release_chord", FIXTURES, "notation", FIXTURE_META["mixed_release_chord"]),
    ("crossing_hands", "unison_crossing", FIXTURES, "notation", FIXTURE_META["unison_crossing"]),
    ("syncopation", "syncopation", FIXTURES, "notation", FIXTURE_META["syncopation"]),
    ("triplets_v1", "mixed_tuplets", FIXTURES, "notation", FIXTURE_META["mixed_tuplets"]),
    ("triplets_v2", "mixed_tuplets", FIXTURES, "readable_v2", FIXTURE_META["mixed_tuplets"]),
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


def _mixed_chord_articulations(rows: list[dict]) -> bool:
    """True when members of one MusicXML chord carry different marks."""
    groups: list[list[tuple]] = []
    current: list[tuple] | None = None
    for row in rows:
        if row["chord"] and current is not None:
            current.append(row["articulations"])
            continue
        current = [row["articulations"]]
        groups.append(current)
    return any(len(set(group)) > 1 for group in groups if len(group) > 1)


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
        "mixed_chord_marks": _mixed_chord_articulations(rows),
        "rest_count": sum(
            1
            for el in root.iter()
            if _local(el.tag) == "note"
            and (el.find("{*}rest") is not None or el.find(".//{*}rest") is not None)
        ),
        "shape": {
            "part_count": max(1, len(parts)),
            "time_signatures": signatures,
            "measure_count": len(measures),
            "trailing_empty_measures": empty_trailing,
        },
    }


def _midi_from_pitch(note_el) -> int | None:
    pitch_el = note_el.find("{*}pitch")
    if pitch_el is None:
        return None
    step_el = pitch_el.find("{*}step")
    octave_el = pitch_el.find("{*}octave")
    if step_el is None or octave_el is None or step_el.text is None or octave_el.text is None:
        return None
    step = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}.get(step_el.text.strip())
    if step is None:
        return None
    alter_el = pitch_el.find("{*}alter")
    alter = int(float(alter_el.text)) if alter_el is not None and alter_el.text else 0
    return 12 * (int(octave_el.text) + 1) + step + alter


def musicxml_members(xml_text: str) -> list[dict]:
    """Per-member pitch, source id, articulations and ties from MusicXML.

    Chord marks stay attached to the sounding note that owns them. A swapped
    staccato/tenuto pair must not compare equal.
    """
    root = ET.fromstring(xml_text)
    rows = []
    measure_number = 0
    for el in root.iter():
        name = _local(el.tag)
        if name == "measure":
            measure_number = int(el.get("number") or measure_number + 1)
        if name != "note":
            continue
        if el.find("{*}rest") is not None or el.find(".//{*}rest") is not None:
            continue
        pitch = _midi_from_pitch(el)
        if pitch is None:
            continue
        arts = tuple(
            sorted(
                _local(child.tag)
                for arts in el.findall(".//{*}articulations")
                for child in list(arts)
            )
        )
        ties = tuple(t.get("type") for t in el.findall("{*}tie") if t.get("type"))
        voice_el = el.find("{*}voice")
        rows.append(
            {
                "measure": measure_number,
                "pitch": pitch,
                "source_id": el.get("id"),
                "voice": (voice_el.text if voice_el is not None else None),
                "articulations": arts,
                "tie": ties[-1] if ties else None,
                "chord": el.find("{*}chord") is not None,
            }
        )
    return rows


def engraving_structure(xml_text: str) -> dict:
    """Normalized engraving used to compare automatic vs edited exports.

    Includes pitches, onsets, durations, voices, ties, beams, tuplets, clefs,
    meter and per-member articulations / source identities. Velocity is
    excluded so an unrelated velocity edit can leave structure unchanged.
    Meter equality alone is not a pass. Unioned chord marks are not enough.
    """
    from music21 import converter

    score = converter.parse(xml_text, format="musicxml")
    parts = []
    for part in score.parts:
        inst = part.getInstrument()
        part_row = {
            "name": str(part.partName or ""),
            "instrument": str(getattr(inst, "instrumentName", None) or ""),
            "measures": [],
        }
        for measure in part.getElementsByClass("Measure"):
            voices: dict[str, list] = {}
            for el in measure.recurse().notesAndRests:
                site = el.activeSite
                if site is not None and site.__class__.__name__ == "Voice":
                    vid = str(site.id)
                else:
                    vid = str(getattr(el, "voice", None) or "1")
                members = list(el.notes) if el.isChord else [el]
                pitches = [
                    int(m.pitch.midi)
                    for m in members
                    if getattr(m, "pitch", None) is not None
                ]
                voices.setdefault(vid, []).append(
                    {
                        "offset": round(float(el.offset), 4),
                        "ql": round(float(el.quarterLength), 4),
                        "pitches": pitches,
                        "is_rest": bool(el.isRest),
                        "tie": getattr(getattr(el, "tie", None), "type", None),
                        "beams": tuple(
                            sorted(
                                str(getattr(beam, "type", beam))
                                for beam in (getattr(el, "beams", None) or [])
                            )
                        ),
                        "tuplets": tuple(
                            (
                                int(getattr(tup, "numberNotesActual", 0) or 0),
                                int(getattr(tup, "numberNotesNormal", 0) or 0),
                            )
                            for tup in (getattr(getattr(el, "duration", None), "tuplets", None) or [])
                        ),
                        "member_articulations": [
                            {
                                "pitch": int(member.pitch.midi),
                                "tie": getattr(getattr(member, "tie", None), "type", None),
                                "articulations": tuple(
                                    sorted(
                                        type(art).__name__
                                        for art in (
                                            getattr(member, "articulations", None) or []
                                        )
                                    )
                                ),
                            }
                            for member in members
                            if getattr(member, "pitch", None) is not None
                        ],
                    }
                )
            clef = None
            if measure.clef is not None:
                clef = str(getattr(measure.clef, "sign", None) or measure.clef)
            part_row["measures"].append(
                {
                    "number": int(measure.number),
                    "voices": [
                        {"id": vid, "elements": voices[vid]} for vid in sorted(voices)
                    ],
                    "ts": getattr(measure.timeSignature, "ratioString", None),
                    "clef": clef,
                }
            )
        parts.append(part_row)
    return {
        "part_count": len(parts),
        "parts": parts,
        "time_signatures": [ts.ratioString for ts in score.flatten().getTimeSignatures()],
        "members": musicxml_members(xml_text),
    }


def _drop_articulations(structure: dict) -> dict:
    stripped = json.loads(json.dumps(structure, default=list))
    for part in stripped.get("parts", []):
        for measure in part.get("measures", []):
            for voice in measure.get("voices", []):
                for el in voice.get("elements", []):
                    el.pop("articulations", None)
                    for member in el.get("member_articulations", []):
                        member.pop("articulations", None)
    for member in stripped.get("members", []):
        member.pop("articulations", None)
    return stripped


def compare_engraving(auto_xml: str, edited_xml: str, *, kind: str) -> dict:
    automatic = engraving_structure(auto_xml)
    edited = engraving_structure(edited_xml)
    meter_only = automatic["time_signatures"] == edited["time_signatures"]
    structure_equal = automatic == edited
    without_arts = _drop_articulations(automatic) == _drop_articulations(edited)
    articulation_change = kind in ARTICULATION_CHANGE_KINDS
    if articulation_change:
        ok = without_arts and not structure_equal
        comparison = "articulation_change"
    else:
        ok = structure_equal
        comparison = "unchanged_engraving"
    return {
        "comparison": comparison,
        "meter_equal": meter_only,
        "structure_equal": structure_equal,
        "structure_equal_ignoring_articulations": without_arts,
        "pass": ok,
        "meter_only_insufficient": meter_only and not ok,
    }


PDF_MAGIC = b"%PDF-"
_PDF_PAGE_OBJECT = re.compile(rb"/Type\s*/Page(?![sA-Za-z])")


def parse_pdf_page_count(data: bytes) -> dict:
    """Parse a PDF enough to reject junk and count page objects.

    stdout page claims and file existence are not enough. A text file that
    happens to mention pages must fail. ``/Type /Pages`` is the tree node,
    not a rendered page.
    """
    if not data.startswith(PDF_MAGIC):
        return {"ok": False, "pages": None, "reason": "missing %PDF- header"}
    if b"%%EOF" not in data:
        return {"ok": False, "pages": None, "reason": "missing %%EOF trailer"}
    pages = len(_PDF_PAGE_OBJECT.findall(data))
    if pages < 1:
        return {"ok": False, "pages": 0, "reason": "no /Type /Page objects"}
    return {"ok": True, "pages": pages, "reason": None}


def expected_osmd_pages(out_dir: Path) -> int | None:
    """Page count from the OSMD model, not from PDF stdout."""
    model = _osmd_model(out_dir)
    if isinstance(model, dict):
        count = model.get("pageCount")
        if isinstance(count, int) and count >= 1:
            return count
    if out_dir.exists():
        rendered = len(list(out_dir.glob("osmd-page-*.svg")))
        if rendered >= 1:
            return rendered
    return None


def _visual_record(render: dict, out_dir: Path) -> dict:
    """Record whether OSMD pages were rendered. Never claims visual review."""
    status_path = out_dir / "visual_status.json"
    payload = {}
    if status_path.exists():
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    skipped = bool(render.get("skipped"))
    svg = bool(render.get("svg")) or bool(payload.get("svg"))
    png = bool(render.get("png")) or bool(payload.get("png"))
    pages = int(payload.get("pages") or 0)
    if not pages:
        pages = len(list(out_dir.glob("osmd-page-*.svg"))) if out_dir.exists() else 0
    pages_rendered = bool(svg and png and pages >= 1)
    if skipped or render.get("returncode") not in (0, None):
        status = "failed" if render.get("returncode") not in (0, None) and not skipped else "skipped"
    elif pages_rendered:
        status = "rendered"
    elif svg or png:
        status = "incomplete"
    else:
        status = "skipped"
    reason = payload.get("reason") or (render.get("stderr") or "")[:400]
    if status == "skipped" and not reason:
        reason = "OSMD snapshot was not produced"
    elif status == "rendered":
        reason = "Pages rendered; visual review is not claimed from screenshots"
    return {
        "status": status,
        "counts_as_success": False,
        "pages_rendered": pages_rendered,
        "visual_review_completed": False,
        "svg": svg,
        "png": png,
        "pages_checked": pages,
        "reason": reason or None,
        "model": (out_dir / "osmd_model.json").exists() if out_dir.exists() else False,
    }


def _pdf_record(pdf: dict, pdf_path: Path, *, expected_pages: int | None = None) -> dict:
    """Separate export, parse, page-count check, and visual review.

    File existence plus a stdout page count is not a pass. Visual review is
    never inferred from export or screenshot generation.
    """
    skipped = bool(pdf.get("skipped"))
    exists = pdf_path.exists() and pdf_path.stat().st_size > 0
    export_completed = (
        not skipped
        and pdf.get("returncode") in (0, None)
        and bool(pdf.get("pdf"))
        and exists
    )
    parsed = (
        parse_pdf_page_count(pdf_path.read_bytes())
        if exists
        else {"ok": False, "pages": None, "reason": "missing file"}
    )
    pdf_parsed = bool(parsed.get("ok"))
    parsed_pages = parsed.get("pages")
    page_count_verified = (
        pdf_parsed
        and expected_pages is not None
        and int(expected_pages) >= 1
        and int(parsed_pages) == int(expected_pages)
    )
    claimed_pages = None
    for line in (pdf.get("stdout") or "").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "pages" in payload:
            claimed_pages = int(payload["pages"])
            break
    if skipped:
        status = "skipped"
        reason = pdf.get("reason") or "PDF export skipped"
    elif not export_completed:
        status = "failed"
        reason = (pdf.get("stderr") or pdf.get("stdout") or "PDF export missing")[:400]
    elif not pdf_parsed:
        status = "failed"
        reason = parsed.get("reason") or "malformed PDF"
    elif expected_pages is None:
        status = "incomplete"
        reason = "PDF parsed; expected OSMD page count is unavailable"
    elif not page_count_verified:
        status = "failed"
        reason = (
            f"PDF page count {parsed_pages} != expected OSMD pages {expected_pages}"
        )
    else:
        status = "passed"
        reason = None
    return {
        "status": status,
        "counts_as_success": status == "passed",
        "export_completed": export_completed,
        "pdf_parsed": pdf_parsed,
        "page_count_verified": page_count_verified,
        "pages_rendered": False,
        "visual_review_completed": False,
        "pdf": exists,
        "pages_checked": parsed_pages or 0,
        "parsed_pages": parsed_pages,
        "expected_pages": expected_pages,
        "claimed_pages": claimed_pages,
        "all_pages_checked": page_count_verified,
        "reason": reason,
    }


def _osmd_model(out_dir: Path) -> dict | None:
    path = out_dir / "osmd_model.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"error": "invalid osmd_model.json"}


def _corrections_for(kind: str, auto) -> list[dict] | None:
    notes = auto.editor_model["notes"]
    if kind == "marked_note":
        sid = _sid_for(auto, start=0)
        return [{"source_note_id": sid, "articulation": "tenuto"}] if sid else None
    if kind == "mixed_chord":
        by_pitch = {int(n["pitch"]): n for n in notes if abs(float(n["start"])) < 0.2}
        # E4/G4 are the MusicXML chord members. C4 is an independent hold.
        e4 = by_pitch.get(64)
        g4 = by_pitch.get(67)
        if not e4 or not g4:
            return None
        return [
            {"source_note_id": e4.get("source_note_id") or e4["id"], "articulation": "staccato"},
            {"source_note_id": g4.get("source_note_id") or g4["id"], "articulation": "tenuto"},
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
        engraving = compare_engraving(auto.musicxml, edited.musicxml, kind=kind)
        visual_auto = _visual_record(auto_render, case_dir / "automatic_osmd")
        visual_edited = (
            _visual_record(edited_render, case_dir / "edited_osmd")
            if corrections
            else {
                "status": "skipped",
                "counts_as_success": False,
                "pages_rendered": False,
                "visual_review_completed": False,
                "reason": "no edit",
            }
        )
        expected_auto = expected_osmd_pages(case_dir / "automatic_osmd")
        expected_edited = expected_osmd_pages(case_dir / "edited_osmd")
        pdf_auto_rec = _pdf_record(
            pdf_auto,
            case_dir / "automatic_sheetresult.pdf",
            expected_pages=expected_auto,
        )
        pdf_edited_rec = (
            _pdf_record(
                pdf_edited,
                case_dir / "after_unrelated_edit_sheetresult.pdf",
                expected_pages=expected_edited,
            )
            if corrections
            else {
                "status": "skipped",
                "counts_as_success": False,
                "export_completed": False,
                "pdf_parsed": False,
                "page_count_verified": False,
                "visual_review_completed": False,
                "reason": "no edit",
            }
        )
        for visual, where in ((visual_auto, "automatic"), (visual_edited, "edited")):
            if visual.get("status") in {"skipped", "failed", "incomplete"} and visual.get("reason") != "no edit":
                report["blocked"].append(
                    {
                        "case": label,
                        "surface": where,
                        "reason": f"Visual verification {visual.get('status')}",
                        "detail": visual.get("reason"),
                    }
                )
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
                "edit_class": (
                    "articulation_change"
                    if kind in ARTICULATION_CHANGE_KINDS
                    else "unchanged_engraving"
                ),
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
                "engraving_comparison": engraving,
                "osmd_model": _osmd_model(case_dir / "automatic_osmd"),
                "osmd_automatic": {
                    key: auto_render[key]
                    for key in ("returncode", "html", "png", "svg")
                },
                "osmd_edited": {
                    key: edited_render.get(key)
                    for key in ("returncode", "html", "png", "svg", "skipped")
                    if key in edited_render
                },
                "visual_automatic": visual_auto,
                "visual_edited": visual_edited,
                "pdf_automatic": pdf_auto_rec,
                "pdf_after_unrelated_edit": pdf_edited_rec,
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
