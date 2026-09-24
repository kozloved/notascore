"""Export-quality evidence for the notation-correctness milestone.

Uses existing fixture infrastructure. Renders through the same OSMD config
as the frontend sheet preview, then attempts the SheetResult PDF path
(OSMD SVG → PNG → jsPDF) when Playwright and Chromium are available.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from evaluation.notation_fixtures import FIXTURES
from evaluation.readable_v2_cases import READABLE_V2_CASES
from mir.midi_ingest import ingest_midi
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings
from tests.test_shared_engraving import _context_for, _xml_shape

HERE = Path(__file__).resolve().parent
RENDER = HERE / "render_osmd.mjs"
FRONTEND_SHEET = HERE.parent.parent / "frontend" / "components" / "SheetResult.jsx"

CASES = [
    ("detached_vs_short", "A_detached_regular_line", READABLE_V2_CASES, "readable_v2"),
    ("intentional_short_rests", "B_short_notes_with_rests", READABLE_V2_CASES, "readable_v2"),
    ("repeated_under_pedal", "C_repeated_attacks_under_pedal", READABLE_V2_CASES, "readable_v2"),
    ("held_inner_voice", "G_held_voice_same_staff", READABLE_V2_CASES, "readable_v2"),
    ("mixed_release_chord", "mixed_release_chord", FIXTURES, "notation"),
    ("crossing_hands", "unison_crossing", FIXTURES, "notation"),
    ("syncopation", "syncopation", FIXTURES, "notation"),
    ("triplets", "mixed_tuplets", FIXTURES, "notation"),
    ("meter_6_8", "meter_6_8", FIXTURES, "notation"),
    ("multibar_tie", "multibar_held_melody", FIXTURES, "notation"),
]


def _settings(kind: str) -> NotationSettings:
    if kind == "readable_v2":
        return NotationSettings.readable_opt_in()
    return NotationSettings()


def _build(path: Path, settings: NotationSettings, corrections=None):
    ingested = ingest_midi(path)
    return recompute_notation(
        midi_bytes=path.read_bytes(),
        settings=settings,
        performance=ingested.performance,
        context=_context_for(ingested),
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
    """Exercise SheetResult's OSMD → PNG → jsPDF export path."""
    script = r"""
const { pathToFileURL } = require("node:url");
const fs = require("node:fs");
const htmlPath = process.argv[2];
const pdfPath = process.argv[3];
const { chromium } = require("playwright");
const { jsPDF } = require("jspdf");

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1000, height: 1400 } });
  await page.goto(pathToFileURL(htmlPath).href, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.__osmdReady === true, null, { timeout: 30000 });
  const svgs = await page.$$eval("#osmd svg", (nodes) => nodes.map((n) => n.outerHTML));
  if (!svgs.length) throw new Error("Sheet preview is not ready yet");
  const pngs = [];
  for (const svg of svgs) {
    const dataUrl = await page.evaluate(async (markup) => {
      const blob = new Blob([markup], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const img = new Image();
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
        img.src = url;
      });
      const canvas = document.createElement("canvas");
      canvas.width = img.width * 2;
      canvas.height = img.height * 2;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      return canvas.toDataURL("image/png");
    }, svg);
    pngs.push(dataUrl);
  }
  await browser.close();
  const pdf = new jsPDF({ orientation: "portrait", unit: "pt", format: "a4" });
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  pngs.forEach((dataUrl, index) => {
    if (index > 0) pdf.addPage("a4", "portrait");
    pdf.addImage(dataUrl, "PNG", 0, 0, pageW, pageH);
  });
  pdf.save(pdfPath);
  console.log(JSON.stringify({ pages: pngs.length, pdf: pdfPath }));
})().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
"""
    frontend_dir = FRONTEND_SHEET.parent.parent
    with tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False) as handle:
        handle.write(script)
        script_path = handle.name
    try:
        proc = subprocess.run(
            ["node", script_path, str(html_path), str(pdf_path)],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "pdf": pdf_path.exists(),
    }


def inspect_xml(xml_text: str) -> dict:
    from tests.test_notation_articulation_ownership import musicxml_note_marks

    rows = musicxml_note_marks(xml_text)
    ties = [row["tie"] for row in rows if row["tie"]]
    arts = [row for row in rows if row["articulations"]]
    return {
        "printed_notes": len(rows),
        "tied_fragments": len(ties),
        "marked_notes": len(arts),
        "shape": {
            "part_count": _xml_shape(xml_text)["part_count"],
            "time_signatures": _xml_shape(xml_text)["time_signatures"],
        },
    }


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "frontend_sheet": str(FRONTEND_SHEET),
        "osmd_config": str(HERE / "osmd_config.json"),
        "cases": [],
        "pdf_path_available": False,
        "blocked": [],
    }
    for label, name, catalog, kind in CASES:
        case_dir = out_dir / label
        case_dir.mkdir(parents=True, exist_ok=True)
        midi_path = case_dir / f"{name}.mid"
        catalog[name](midi_path)
        original = midi_path.read_bytes()
        settings = _settings(kind)
        auto, ingested = _build(midi_path, settings)
        assert midi_path.read_bytes() == original
        (case_dir / "automatic.musicxml").write_text(auto.musicxml, encoding="utf-8")
        sid = None
        try:
            sid = next(
                n.get("source_note_id") or n["id"]
                for n in auto.editor_model["notes"]
            )
        except StopIteration:
            sid = None
        edited = auto
        if sid:
            edited, _ = _build(
                midi_path,
                settings,
                corrections=[{"source_note_id": sid, "velocity": 108}],
            )
            (case_dir / "after_velocity_edit.musicxml").write_text(
                edited.musicxml, encoding="utf-8"
            )
        auto_render = _render_osmd(case_dir / "automatic.musicxml", case_dir / "automatic_osmd")
        edited_render = {"skipped": True}
        if sid:
            edited_render = _render_osmd(
                case_dir / "after_velocity_edit.musicxml",
                case_dir / "edited_osmd",
            )
        pdf = {"skipped": True}
        html = case_dir / "automatic_osmd" / "osmd_preview.html"
        if html.exists():
            pdf = _frontend_pdf(html, case_dir / "automatic_sheetresult.pdf")
            if pdf.get("pdf"):
                report["pdf_path_available"] = True
            elif "Cannot find module" in (pdf.get("stderr") or "") or pdf.get("returncode"):
                report["blocked"].append(
                    {
                        "case": label,
                        "reason": "Frontend PDF path blocked",
                        "detail": (pdf.get("stderr") or pdf.get("stdout") or "")[:400],
                    }
                )
        same_shape = True
        if sid:
            same_shape = _xml_shape(auto.musicxml) == _xml_shape(edited.musicxml)
        report["cases"].append(
            {
                "label": label,
                "fixture": name,
                "settings": settings.to_dict(),
                "midi_sha256": hashlib.sha256(original).hexdigest(),
                "performance_sha256": ingested.performance.midi_sha256,
                "automatic": inspect_xml(auto.musicxml),
                "edited_same_engraving": same_shape,
                "osmd_automatic": {
                    key: auto_render[key]
                    for key in ("returncode", "html", "png", "svg")
                },
                "osmd_edited": {
                    key: edited_render.get(key)
                    for key in ("returncode", "html", "png", "svg", "skipped")
                    if key in edited_render
                },
                "pdf": {key: pdf.get(key) for key in ("returncode", "pdf", "skipped") if key in pdf},
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
