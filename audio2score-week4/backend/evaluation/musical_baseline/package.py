"""Build a reproducible P1 musician-review package from eligible candidates.

Uses existing notation builders. Keeps performance-score-1 default and
performance-score-2 opt-in. Does not invent reviews or quality scores.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from evaluation.hands_rhythm_metrics import extract_measures_musicxml
from evaluation.musical_baseline.catalog import (
    REVIEW_DIMENSIONS,
    CandidateExample,
    asset_inventory,
    candidates,
    dimension_status_for,
    family_coverage,
    resolve_midi_writer,
    split_leakage,
)
from evaluation.musical_baseline.reviews import (
    CASE_REPORT_NAME,
    COMPLETION_CRITERIA,
    FINGERPRINT_NAME,
    REVIEW_FORM_NAME,
    REVIEW_JSON_NAME,
    aggregate_reviews,
    build_fingerprint,
    empty_review_template,
    validate_case_dir,
    write_review_form_if_absent,
    write_review_if_absent,
)
from evaluation.notation_correctness_evidence import _build, _render_osmd, measure_validity
from evaluation.readable_v2_rollout import _assignments, _surface, compare_staff_voice
from mir.notation_settings import (
    ALGORITHM_VERSION_CURRENT,
    ALGORITHM_VERSION_READABLE,
    NotationSettings,
)

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "review_package"


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _score_context(xml_text: str) -> dict[str, Any]:
    """Clef, key, meter, and staff context from MusicXML (for phrase extracts)."""
    root = ET.fromstring(xml_text)
    _strip_ns(root)
    clefs: list[dict[str, str]] = []
    keys: list[dict[str, str]] = []
    meters: list[str] = []
    staff_count = 0
    for attributes in root.findall(".//attributes"):
        for clef in attributes.findall("clef"):
            clefs.append(
                {
                    "number": clef.get("number") or "1",
                    "sign": clef.findtext("sign") or "",
                    "line": clef.findtext("line") or "",
                }
            )
        for key in attributes.findall("key"):
            keys.append(
                {
                    "fifths": key.findtext("fifths") or "",
                    "mode": key.findtext("mode") or "",
                }
            )
        for time_el in attributes.findall("time"):
            beats = time_el.findtext("beats") or ""
            beat_type = time_el.findtext("beat-type") or ""
            if beats and beat_type:
                meters.append(f"{beats}/{beat_type}")
        staves = attributes.findtext("staves")
        if staves:
            staff_count = max(staff_count, int(staves))
    if staff_count == 0:
        staff_count = max((int(c["number"]) for c in clefs), default=1)
    return {
        "clefs": clefs,
        "keys": keys,
        "meters": meters or [],
        "staff_count": staff_count,
    }


def _note_index(assignments: dict) -> list[dict[str, Any]]:
    rows = []
    for note in assignments.get("notes") or []:
        rows.append(
            {
                "source_note_id": note.get("id"),
                "pitch": note.get("pitch"),
                "start": note.get("start"),
                "duration": note.get("duration"),
                "staff": note.get("staff"),
                "musical_voice": note.get("musical_voice"),
                "printed_voice": note.get("printed_voice"),
                "voice_provenance": note.get("voice_provenance"),
            }
        )
    return rows


def _review_form_markdown(candidate: CandidateExample, dimensions: dict[str, dict]) -> str:
    lines = [
        f"# Review form — `{candidate.example_id}`",
        "",
        f"- Title: {candidate.title}",
        f"- Composition ID: `{candidate.composition_id}`",
        f"- Performance ID: `{candidate.performance_id}`",
        f"- Split: `{candidate.split}`",
        f"- Source: `{candidate.source_kind}` / `{candidate.source_id}`",
        f"- Instrument: {candidate.instrument}",
        f"- Meter / tempo: {candidate.meter} @ {candidate.tempo}",
        f"- Families: {', '.join(candidate.families)}",
        f"- Permitted use: `{candidate.permitted_use}`",
        f"- Copyrighted: `{candidate.copyrighted}`",
        "",
        "Identify notes by **source_note_id** in `note_index.json` "
        "(not printed lane numbers alone).",
        "",
        "Default engine is `performance-score-1`. Opt-in `performance-score-2` "
        "artifacts are for comparison only. Export success is not musical quality.",
        "",
        "**Human-owned files:** edit `review.json` (authoritative) and optionally "
        f"`{REVIEW_FORM_NAME}`. Package rebuilds never overwrite filled reviews. "
        "Copy hashes from `artifact_fingerprint.json` into "
        "`review.json` → `artifact_binding` before submitting "
        "(include playback `v1/v2_score_midi_sha256`; use null if a "
        "playback file is absent).",
        "",
        "Valid dimension statuses: `pass` | `fail` | `needs_work` | "
        "`not_reviewed` | `not_applicable`. Optional per-version fields: "
        "`versions.v1` / `versions.v2`.",
        "",
        "## Attribution",
        "",
        "- Reviewer name: _______________________________",
        "- Reviewer role / credentials: _________________",
        "- Review date (ISO): ___________________________",
        "- Contact (optional): __________________________",
        "",
        "## Dimensions (score each separately; leave blank if not reviewing)",
        "",
    ]
    prompts = {
        "acoustic_accuracy": (
            "Only if suitable audio + reference labels exist. "
            "Do pitches and performed timings match the recording?"
        ),
        "musical_interpretation_accuracy": (
            "Is the printed interpretation usable "
            "(meter, pickup, voices, rests, articulation, duration spelling)?"
        ),
        "export_integrity": (
            "Mechanical: MusicXML/MIDI readable, identities preserved, "
            "no silent fallback. Automated checks may pre-fill this."
        ),
        "human_correction_effort": (
            "About how many minutes / edits to make this teachable or publishable? "
            "List the top 1–3 corrections keyed by source_note_id."
        ),
    }
    for name in REVIEW_DIMENSIONS:
        dim = dimensions[name]
        lines.extend(
            [
                f"### {name}",
                "",
                f"- Status in package: `{dim['status']}`",
                f"- Reason: {dim['reason']}",
                f"- Prompt: {prompts[name]}",
                "- Rating (pass / fail / needs_work / not_reviewed / not_applicable): ________",
                "- v1 rating (optional): ________",
                "- v2 rating (optional): ________",
                "- Score (optional 1–5; leave blank if unreviewed): ________",
                "- Notes:",
                "",
                "  > ",
                "",
            ]
        )
    lines.extend(
        [
            "## Staff vs musical voice vs printed lanes",
            "",
            "Compare these separately. A printed-lane change after duration fill "
            "(e.g. development MIDI 138) is not automatically a musical-voice defect.",
            "",
            "- Staff grouping ok? ________",
            "- Musical-voice grouping ok? ________",
            "- Printed lanes ok / expected adjustment? ________",
            "",
            "## Contracts reminder",
            "",
            "- Preserve original MIDI bytes and source-note identities.",
            "- Preserve performed timing, exact tuplets/ties, accepted corrections, locks.",
            "- Do not retune the engine solely because printed lanes move.",
            "",
        ]
    )
    return "\n".join(lines)


def _export_check(
    *,
    midi_path: Path,
    original: bytes,
    v1,
    v2,
    assign1: dict,
    assign2: dict,
) -> dict[str, Any]:
    """Mechanical export integrity for performance→score packages.

    Do not use ``stage_gate`` with performed MIDI as the score reference:
    that gate expects annotated/quantized offsets and would fail offset F1
    even when MusicXML export identity is intact.
    """
    valid1 = measure_validity(v1.musicxml)
    valid2 = measure_validity(v2.musicxml)
    ids1 = {row["id"] for row in assign1.get("notes") or []}
    ids2 = {row["id"] for row in assign2.get("notes") or []}
    checks = {
        "source_bytes_unchanged": midi_path.read_bytes() == original,
        "v1_musicxml_nonempty": bool(v1.musicxml.strip()),
        "v2_musicxml_nonempty": bool(v2.musicxml.strip()),
        "v1_score_midi_present": bool(v1.score_midi),
        "v2_score_midi_present": bool(v2.score_midi),
        "v1_musical_valid": bool(valid1.get("musical_valid")),
        "v2_musical_valid": bool(valid2.get("musical_valid")),
        "source_note_ids_nonempty": bool(ids1),
        "source_note_ids_stable_across_versions": ids1 == ids2,
        "v1_default_algorithm": v1.settings.algorithm_version == ALGORITHM_VERSION_CURRENT,
        "v2_opt_in_algorithm": v2.settings.algorithm_version == ALGORITHM_VERSION_READABLE,
    }
    passed = all(checks.values())
    return {
        "dimension": "export_integrity",
        "status": "passed" if passed else "failed",
        "passed": passed,
        "checks": checks,
        "measure_validity": {"v1": valid1, "v2": valid2},
        "reason": (
            "mechanical MusicXML/MIDI integrity on the shared planner "
            "(not acoustic quality; not musician readability)"
        ),
        "mechanical": True,
        "score": None,
        "reviewer": "automated_export_integrity",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "notes": (
            "Automated export integrity only. Does not prove musical quality. "
            "Performed-MIDI offset F1 vs a score reference is out of scope here."
        ),
    }


def _write_phrase_extracts(
    case_dir: Path,
    *,
    v1_xml: str,
    v2_xml: str,
    note_ids: list[str],
) -> dict[str, Any]:
    """Preserve clef/key/meter/staff by measure extract (not music21 rewrite)."""
    phrase_dir = case_dir / "phrases"
    phrase_dir.mkdir(parents=True, exist_ok=True)
    v1_path = case_dir / "v1.musicxml"
    v2_path = case_dir / "v2.musicxml"
    context = _score_context(v1_xml)
    # Short examples: keep all measures present in v1.
    root = ET.fromstring(v1_xml)
    _strip_ns(root)
    numbers = set()
    for measure in root.findall(".//measure"):
        try:
            numbers.add(int(measure.get("number") or 0))
        except ValueError:
            continue
    if not numbers:
        numbers = {1}
    before = extract_measures_musicxml(
        v1_path, phrase_dir / "v1_phrase.musicxml", numbers
    )
    after = extract_measures_musicxml(
        v2_path, phrase_dir / "v2_phrase.musicxml", numbers
    )
    manifest = {
        "measure_numbers": sorted(numbers),
        "source_note_ids": note_ids,
        "score_context": context,
        "v1": before,
        "v2": after,
        "context_preserved": True,
        "note": (
            "Phrase extracts copy selected measures without rewriting clef, "
            "key, or meter attributes."
        ),
    }
    (phrase_dir / "phrase_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def build_case(
    candidate: CandidateExample,
    out_dir: Path,
    *,
    render: bool = False,
) -> dict[str, Any]:
    case_dir = out_dir / candidate.split / candidate.example_id
    case_dir.mkdir(parents=True, exist_ok=True)
    writer = resolve_midi_writer(candidate)
    midi_path = case_dir / "input.mid"
    writer.write(midi_path)
    original = midi_path.read_bytes()
    midi_sha = hashlib.sha256(original).hexdigest()

    v1, ingested = _build(
        midi_path,
        NotationSettings(),
        meter=writer.meter,
        tempo=writer.tempo,
    )
    assert midi_path.read_bytes() == original
    v2, _ = _build(
        midi_path,
        NotationSettings.readable_opt_in(),
        meter=writer.meter,
        tempo=writer.tempo,
    )
    assert midi_path.read_bytes() == original

    (case_dir / "v1.musicxml").write_text(v1.musicxml, encoding="utf-8")
    (case_dir / "v2.musicxml").write_text(v2.musicxml, encoding="utf-8")
    if v1.score_midi:
        (case_dir / "v1.score.mid").write_bytes(v1.score_midi)
    if v2.score_midi:
        (case_dir / "v2.score.mid").write_bytes(v2.score_midi)

    assign1 = _assignments(v1)
    assign2 = _assignments(v2)
    note_index = _note_index(assign1)
    (case_dir / "note_index.json").write_text(
        json.dumps(
            {
                "matched_by": "source_note_id",
                "notes": note_index,
                "staff_musical_printed_compared_separately": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    phrase = _write_phrase_extracts(
        case_dir,
        v1_xml=v1.musicxml,
        v2_xml=v2.musicxml,
        note_ids=[n["source_note_id"] for n in note_index if n.get("source_note_id")],
    )

    staff_voice = compare_staff_voice(assign1, assign2)
    surface1 = _surface(v1.musicxml)
    surface2 = _surface(v2.musicxml)
    valid1 = measure_validity(v1.musicxml)
    valid2 = measure_validity(v2.musicxml)

    dimensions = dimension_status_for(candidate)
    dimensions["export_integrity"] = _export_check(
        midi_path=midi_path,
        original=original,
        v1=v1,
        v2=v2,
        assign1=assign1,
        assign2=assign2,
    )

    renders: list[dict[str, Any]] = []
    if render:
        for version, xml in (("v1", v1.musicxml), ("v2", v2.musicxml)):
            xml_path = case_dir / f"{version}.musicxml"
            osmd = _render_osmd(xml_path, case_dir / f"{version}_osmd")
            renders.append(
                {
                    "version": version,
                    "osmd": {
                        key: osmd.get(key) for key in ("returncode", "html", "png", "svg")
                    },
                }
            )

    fingerprint = build_fingerprint(
        midi_sha256=midi_sha,
        v1_musicxml=v1.musicxml,
        v2_musicxml=v2.musicxml,
        meter=writer.meter,
        tempo=writer.tempo,
        example_id=candidate.example_id,
        source_id=candidate.source_id,
        v1_score_midi=v1.score_midi or None,
        v2_score_midi=v2.score_midi or None,
    )
    (case_dir / FINGERPRINT_NAME).write_text(
        json.dumps(fingerprint, indent=2) + "\n", encoding="utf-8"
    )

    form_md = _review_form_markdown(candidate, dimensions)
    form_write = write_review_form_if_absent(case_dir, form_md)
    review_template = empty_review_template(
        example_id=candidate.example_id,
        composition_id=candidate.composition_id,
        performance_id=candidate.performance_id,
        split=candidate.split,
        fingerprint=fingerprint,
        acoustic_default=(
            "not_applicable"
            if dimensions["acoustic_accuracy"]["status"] == "not_applicable"
            else "not_reviewed"
        ),
    )
    review_write = write_review_if_absent(case_dir, review_template)

    expected_identity = {
        "example_id": candidate.example_id,
        "composition_id": candidate.composition_id,
        "performance_id": candidate.performance_id,
        "split": candidate.split,
    }
    review_validation = validate_case_dir(
        case_dir, expected=expected_identity
    )
    report_dimensions = dict(dimensions)
    # Overlay human ratings into the report when structurally valid / loadable.
    if review_validation.load_status == "loaded" and review_validation.dimensions:
        for name, human_dim in review_validation.dimensions.items():
            if name == "export_integrity":
                # Keep mechanical export check; attach human overlay separately.
                report_dimensions[name] = {
                    **dimensions["export_integrity"],
                    "human_status": human_dim.get("status"),
                    "human_versions": human_dim.get("versions"),
                    "human_notes": human_dim.get("notes"),
                    "human_score": human_dim.get("score"),
                }
            else:
                report_dimensions[name] = {
                    "dimension": name,
                    "status": human_dim.get("status"),
                    "versions": human_dim.get("versions"),
                    "score": human_dim.get("score"),
                    "notes": human_dim.get("notes"),
                    "reviewer": review_validation.reviewer,
                    "reviewed_at": review_validation.reviewed_at,
                    "reason": (
                        "human review (stale; excluded from completion)"
                        if review_validation.binding_stale
                        else (
                            "human review"
                            if human_dim.get("counts_as_rated")
                            else "human review field present but not a completed rating"
                        )
                    ),
                    "stale": review_validation.binding_stale,
                    "counts_as_rated": bool(human_dim.get("counts_as_rated"))
                    and review_validation.binding_current
                    and not review_validation.binding_stale,
                }

    row = {
        "example_id": candidate.example_id,
        "composition_id": candidate.composition_id,
        "performance_id": candidate.performance_id,
        "split": candidate.split,
        "source_kind": candidate.source_kind,
        "source_id": candidate.source_id,
        "title": candidate.title,
        "families": list(candidate.families),
        "instrument": candidate.instrument,
        "meter": writer.meter,
        "tempo": writer.tempo,
        "permitted_use": candidate.permitted_use,
        "copyrighted": candidate.copyrighted,
        "midi_sha256": midi_sha,
        "performance_sha256": ingested.performance.midi_sha256,
        "source_midi_unchanged": midi_path.read_bytes() == original,
        "artifact_fingerprint": fingerprint,
        "default_algorithm_version": ALGORITHM_VERSION_CURRENT,
        "opt_in_algorithm_version": ALGORITHM_VERSION_READABLE,
        "algorithms": {
            "v1": v1.settings.algorithm_version,
            "v2": v2.settings.algorithm_version,
        },
        "surface": {"v1": surface1, "v2": surface2},
        "measure_validity": {"v1": valid1, "v2": valid2},
        "staff_voice": staff_voice,
        "score_context": phrase["score_context"],
        "phrase_extract": {
            "measure_numbers": phrase["measure_numbers"],
            "source_note_id_count": len(phrase["source_note_ids"]),
        },
        "dimensions": report_dimensions,
        "review": {
            "write": review_write,
            "form_write": form_write,
            "validation": review_validation.to_dict(),
            "review_complete": review_validation.review_complete,
            "musically_accepted": review_validation.musically_accepted,
            "human_owned_files": [REVIEW_JSON_NAME, REVIEW_FORM_NAME],
            "generated_template": "REVIEW_FORM.template.md",
        },
        "artifacts": {
            "input_midi": str((case_dir / "input.mid").relative_to(out_dir)),
            "v1_musicxml": str((case_dir / "v1.musicxml").relative_to(out_dir)),
            "v2_musicxml": str((case_dir / "v2.musicxml").relative_to(out_dir)),
            "v1_score_midi": (
                str((case_dir / "v1.score.mid").relative_to(out_dir))
                if (case_dir / "v1.score.mid").exists()
                else None
            ),
            "v2_score_midi": (
                str((case_dir / "v2.score.mid").relative_to(out_dir))
                if (case_dir / "v2.score.mid").exists()
                else None
            ),
            "note_index": str((case_dir / "note_index.json").relative_to(out_dir)),
            "artifact_fingerprint": str(
                (case_dir / FINGERPRINT_NAME).relative_to(out_dir)
            ),
            "review_form": str((case_dir / REVIEW_FORM_NAME).relative_to(out_dir)),
            "review_json": str((case_dir / REVIEW_JSON_NAME).relative_to(out_dir)),
            "phrases": str((case_dir / "phrases").relative_to(out_dir)),
            "case_report": str((case_dir / CASE_REPORT_NAME).relative_to(out_dir)),
        },
        "renders": renders,
        "contracts": {
            "performance_score_1_default": v1.settings.algorithm_version
            == ALGORITHM_VERSION_CURRENT,
            "performance_score_2_opt_in": v2.settings.algorithm_version
            == ALGORITHM_VERSION_READABLE,
            "original_midi_preserved": midi_path.read_bytes() == original,
            "notes_identified_by_source_note_id": True,
            "staff_musical_printed_compared_separately": True,
            "export_success_is_not_musical_quality": True,
            "human_reviews_preserved_on_rebuild": True,
        },
    }
    (case_dir / CASE_REPORT_NAME).write_text(
        json.dumps(row, indent=2) + "\n", encoding="utf-8"
    )
    return row


def _case_identity_from_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "example_id": row["example_id"],
        "composition_id": row["composition_id"],
        "performance_id": row["performance_id"],
        "split": row["split"],
    }


def _package_commands() -> list[str]:
    return [
        "cd audio2score-week4/backend",
        "python -m evaluation.musical_baseline --inventory",
        "python -m evaluation.musical_baseline --package evaluation/musical_baseline/review_package --render",
        "python -m evaluation.musical_baseline --report-reviews evaluation/musical_baseline/review_package",
        "python -m evaluation.musical_baseline --write-index evaluation/musical_baseline/review_package",
        "python -m evaluation.musical_baseline --bundle evaluation/musical_baseline/review_package",
        "python -m pytest -q tests/test_musical_baseline.py",
    ]


FIRST_SESSION_CASES = (
    "dev-intentional-rests",
    "dev-independent-voices",
    "dev-detached-triplets",
    "dev-pickup",
)


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def write_review_index(out_dir: Path | None = None) -> Path:
    """Write a lightweight local HTML index linking renders and review files."""
    dest = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    if not dest.is_dir():
        raise FileNotFoundError(f"review package not found: {dest}")
    rows: list[dict[str, Any]] = []
    for candidate in candidates(eligible_only=True):
        case_dir = dest / candidate.split / candidate.example_id
        renders = {}
        for version in ("v1", "v2"):
            osmd = case_dir / f"{version}_osmd"
            png = osmd / "osmd.png"
            html = osmd / "osmd_preview.html"
            status_path = osmd / "visual_status.json"
            status = None
            if status_path.is_file():
                try:
                    status = json.loads(status_path.read_text(encoding="utf-8")).get(
                        "status"
                    )
                except (OSError, json.JSONDecodeError):
                    status = "unreadable"
            renders[version] = {
                "png": _rel(png, dest) if png.is_file() else None,
                "html": _rel(html, dest) if html.is_file() else None,
                "status": status,
            }
        rows.append(
            {
                "example_id": candidate.example_id,
                "split": candidate.split,
                "title": candidate.title,
                "families": list(candidate.families),
                "meter": candidate.meter,
                "first_session": candidate.example_id in FIRST_SESSION_CASES,
                "input_midi": _rel(case_dir / "input.mid", dest)
                if (case_dir / "input.mid").is_file()
                else None,
                "v1_score_midi": _rel(case_dir / "v1.score.mid", dest)
                if (case_dir / "v1.score.mid").is_file()
                else None,
                "v2_score_midi": _rel(case_dir / "v2.score.mid", dest)
                if (case_dir / "v2.score.mid").is_file()
                else None,
                "v1_musicxml": _rel(case_dir / "v1.musicxml", dest)
                if (case_dir / "v1.musicxml").is_file()
                else None,
                "v2_musicxml": _rel(case_dir / "v2.musicxml", dest)
                if (case_dir / "v2.musicxml").is_file()
                else None,
                "review_json": _rel(case_dir / REVIEW_JSON_NAME, dest)
                if (case_dir / REVIEW_JSON_NAME).is_file()
                else None,
                "review_form": _rel(case_dir / REVIEW_FORM_NAME, dest)
                if (case_dir / REVIEW_FORM_NAME).is_file()
                else None,
                "fingerprint": _rel(case_dir / FINGERPRINT_NAME, dest)
                if (case_dir / FINGERPRINT_NAME).is_file()
                else None,
                "note_index": _rel(case_dir / "note_index.json", dest)
                if (case_dir / "note_index.json").is_file()
                else None,
                "renders": renders,
            }
        )

    def section(split: str) -> str:
        parts = [f"<h2>{split}</h2>"]
        for row in rows:
            if row["split"] != split:
                continue
            badge = (
                ' <span class="badge">first session</span>'
                if row["first_session"]
                else ""
            )
            fam = ", ".join(row["families"])
            v1p = row["renders"]["v1"]["png"]
            v2p = row["renders"]["v2"]["png"]
            thumbs = ""
            if v1p:
                thumbs += (
                    f'<a href="{v1p}"><img src="{v1p}" alt="v1 render" '
                    f'class="thumb" /></a>'
                )
            if v2p:
                thumbs += (
                    f'<a href="{v2p}"><img src="{v2p}" alt="v2 render" '
                    f'class="thumb" /></a>'
                )
            links = []
            for label, key in (
                ("input.mid", "input_midi"),
                ("v1.score.mid", "v1_score_midi"),
                ("v2.score.mid", "v2_score_midi"),
                ("v1.musicxml", "v1_musicxml"),
                ("v2.musicxml", "v2_musicxml"),
                ("review.json", "review_json"),
                ("REVIEW_FORM.md", "review_form"),
                ("note_index.json", "note_index"),
                ("fingerprint", "fingerprint"),
            ):
                href = row.get(key)
                if href:
                    links.append(f'<a href="{href}">{label}</a>')
            for ver in ("v1", "v2"):
                html = row["renders"][ver]["html"]
                if html:
                    links.append(f'<a href="{html}">{ver} OSMD HTML</a>')
            parts.append(
                f'<section class="case" id="{row["example_id"]}">'
                f"<h3><code>{row['example_id']}</code>{badge}</h3>"
                f"<p>{row['title']} · meter {row['meter']} · {fam}</p>"
                f'<div class="thumbs">{thumbs}</div>'
                f'<p class="links">{" · ".join(links)}</p>'
                "</section>"
            )
        return "\n".join(parts)

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>P1 musical baseline — review index</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 2rem; max-width: 1100px;
           background: #f7f4ee; color: #1a1a1a; }}
    h1, h2 {{ font-family: system-ui, sans-serif; }}
    .badge {{ background: #264653; color: #fff; font-size: 0.75rem;
              padding: 0.15rem 0.45rem; border-radius: 4px; margin-left: 0.4rem; }}
    .case {{ border-top: 1px solid #ccc; padding: 1rem 0; }}
    .thumbs {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 0.75rem 0; }}
    .thumb {{ width: 280px; height: auto; border: 1px solid #bbb;
              background: #fff; }}
    .links a {{ margin-right: 0.25rem; }}
    .note {{ background: #fff; border-left: 4px solid #264653; padding: 0.75rem 1rem; }}
  </style>
</head>
<body>
  <h1>P1 musical baseline — review index</h1>
  <p class="note">
    Open this file locally (file://). Development and held-out cases are
    separated. Default engine is <code>performance-score-1</code> (v1);
    <code>performance-score-2</code> (v2) is opt-in comparison only.
    Synthetic examples can assess notation; they cannot establish acoustic
    transcription accuracy. Do not invent reviewer names or ratings here —
    fill <code>review.json</code> / <code>REVIEW_FORM.md</code> in each case.
  </p>
  <p>
    First session guide: <a href="FIRST_SESSION.md">FIRST_SESSION.md</a> ·
    Instructions: <a href="REVIEW_INSTRUCTIONS.md">REVIEW_INSTRUCTIONS.md</a> ·
    Package report: <a href="package_report.md">package_report.md</a>
  </p>
  {section("development")}
  {section("held_out")}
</body>
</html>
"""
    path = dest / "REVIEW_INDEX.html"
    path.write_text(html, encoding="utf-8")
    return path


def write_first_session_guide(out_dir: Path | None = None) -> Path:
    """Write concise steps for the first 4 development review cases."""
    dest = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    by_id = {c.example_id: c for c in candidates(eligible_only=True)}
    lines = [
        "# First musician review session (development only)",
        "",
        "Engine default remains `performance-score-1` (v1). `performance-score-2`",
        "(v2) is opt-in for side-by-side comparison. Do **not** invent ratings",
        "or reviewer names. Automated OSMD images are not musician sign-off.",
        "These synthetic cases can assess **notation / interpretation /",
        "correction effort**; they cannot prove acoustic transcription accuracy.",
        "",
        "Open `REVIEW_INDEX.html` for thumbnails and file links.",
        "",
        "## Cases (4)",
        "",
    ]
    prompts = {
        "dev-intentional-rests": (
            "Listen for intentional silence between short attacks. Check whether "
            "rests look deliberate (not fragmented junk) on both staves."
        ),
        "dev-independent-voices": (
            "Check whether a sustained voice stays readable under moving notes "
            "on the same staff. Compare staff vs musical-voice vs printed lane."
        ),
        "dev-detached-triplets": (
            "Confirm triplet grouping is readable and detached attacks stay "
            "separate. Compare v1 vs v2 spelling if they differ."
        ),
        "dev-pickup": (
            "Confirm the pickup/rubato opening is playable: downbeat location, "
            "tempo marks for listening, and whether the first written beat feels right."
        ),
    }
    for example_id in FIRST_SESSION_CASES:
        cand = by_id[example_id]
        lines.extend(
            [
                f"### `{example_id}` — {cand.title}",
                "",
                f"- Families: {', '.join(cand.families)}",
                f"- Meter / tempo: {cand.meter} @ {cand.tempo}",
                f"- Folder: `development/{example_id}/`",
                f"- Focus: {prompts[example_id]}",
                "",
                "**Steps**",
                "",
                f"1. Open v1 and v2 renders (`v1_osmd/osmd.png`, `v2_osmd/osmd.png`) "
                f"or HTML previews.",
                f"2. Play `v1.score.mid` then `v2.score.mid` (source: `input.mid`).",
                f"3. Use `note_index.json` / `phrases/` and cite `source_note_id` "
                f"for concrete notes.",
                f"4. Edit `review.json` (authoritative):",
                f"   - `attribution.reviewer`, `attribution.reviewed_at` (ISO date)",
                f"   - copy current hashes from `artifact_fingerprint.json` into "
                f"`artifact_binding` (include playback SHA fields)",
                f"   - `dimensions.musical_interpretation_accuracy.status` "
                f"(`pass`/`fail`/`needs_work`) and optional `versions.v1` / `versions.v2`",
                f"   - `dimensions.human_correction_effort.status` plus notes "
                f"(minutes / top edits by `source_note_id`)",
                f"   - leave `acoustic_accuracy` as `not_applicable` unless real "
                f"audio+labels exist",
                f"5. Optionally mirror notes in `REVIEW_FORM.md`.",
                "",
            ]
        )
    lines.extend(
        [
            "## After the session",
            "",
            "Ask an engineer to run report-only (does not rebuild scores):",
            "",
            "```bash",
            "cd audio2score-week4/backend",
            "python -m evaluation.musical_baseline --report-reviews "
            "evaluation/musical_baseline/review_package",
            "```",
            "",
            "Confirm your cases appear under review_complete / musically_accepted",
            "in `package_report.md` only when bindings match **live** artifacts.",
            "",
            "Held-out cases are **out of scope** for this first session.",
            "",
        ]
    )
    path = dest / "FIRST_SESSION.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def export_portable_bundle(
    out_dir: Path | None = None,
    *,
    bundle_path: Path | None = None,
    engine_commit: str | None = None,
) -> Path:
    """Copy the review package (including gitignored MIDI/renders) into a tarball."""
    import tarfile

    dest = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    if not dest.is_dir():
        raise FileNotFoundError(f"review package not found: {dest}")
    write_review_index(dest)
    write_first_session_guide(dest)
    handoff = HERE / "handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    commit = (engine_commit or "local").strip() or "local"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = (
        Path(bundle_path)
        if bundle_path is not None
        else handoff / f"p1-review-handoff-{commit[:12]}-{stamp}.tar.gz"
    )
    archive.parent.mkdir(parents=True, exist_ok=True)
    supplemental = dest / "supplemental_p2b"
    manifest = {
        "engine_commit": commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_dir": str(dest),
        "includes_midi": True,
        "includes_osmd_renders": True,
        "includes_supplemental_p2b": supplemental.is_dir(),
        "includes_real_sample_checklist": (
            dest / "REAL_SAMPLE_REVIEW_CHECKLIST.md"
        ).is_file(),
        "first_session_cases": list(FIRST_SESSION_CASES),
        "pickup_tempo_examples": ["dev-pickup"],
        "commands": _package_commands(),
        "note": (
            "Portable musician-review handoff. Prepared for review does not "
            "mean P1 is complete. No fabricated ratings. Supplemental P2b "
            "voice pairs are synthetic construction evidence only. Old "
            "handoff archives under handoff/ are preserved separately."
        ),
    }
    (dest / "HANDOFF_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(dest, arcname="review_package")
    return archive


def _assemble_package_report(
    dest: Path,
    case_rows: list[dict[str, Any]],
    *,
    inventory: dict[str, Any],
    generated_at: str | None = None,
    mode: str = "package",
) -> dict[str, Any]:
    validations = []
    for row in case_rows:
        case_dir = dest / row["split"] / row["example_id"]
        # Always validate against live artifact bytes. Never trust a cached
        # case_report / row fingerprint as proof that scores are current.
        validations.append(
            validate_case_dir(
                case_dir,
                expected=_case_identity_from_row(row),
            )
        )
        # Refresh embedded validation on rows for report-only freshness.
        row["review"] = {
            **(row.get("review") or {}),
            "validation": validations[-1].to_dict(),
            "review_complete": validations[-1].review_complete,
            "musically_accepted": validations[-1].musically_accepted,
        }
    summary = aggregate_reviews(validations)
    human_complete = summary["review_complete_count"]
    accepted = summary["musically_accepted_count"]
    report = {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "out_dir": str(dest),
        "default_algorithm_version": ALGORITHM_VERSION_CURRENT,
        "opt_in_algorithm_version": ALGORITHM_VERSION_READABLE,
        "candidate_count": len(case_rows),
        "development_count": sum(1 for r in case_rows if r["split"] == "development"),
        "held_out_count": sum(1 for r in case_rows if r["split"] == "held_out"),
        "family_coverage": family_coverage(),
        "split_leakage": [],
        "splits_disjoint": True,
        "completion_criteria": COMPLETION_CRITERIA,
        "review_summary": summary,
        "musician_reviewed_complete": human_complete,
        "musically_accepted_count": accepted,
        "reviewed_but_not_accepted_count": summary[
            "reviewed_but_not_accepted_count"
        ],
        "p1_complete": False,
        "p1_complete_reason": (
            f"{human_complete}/{len(case_rows)} cases meet review_complete criteria; "
            f"{accepted}/{len(case_rows)} musically accepted (interpretation pass). "
            "Do not mark P1 complete without attributed current reviews. "
            "Completion is not production readiness."
        ),
        "inventory_summary": {
            "gaps": inventory["gaps"],
            "candidate_counts": inventory["candidate_counts"],
            "nota_test_samples": len(inventory["assets"]["nota_test_samples"]),
        },
        "cases": case_rows,
        "commands": _package_commands(),
    }
    return report


def _write_multichannel_midi(path: Path, notes, *, tempo: float = 120.0) -> None:
    """Write (pitch, start, end, velocity, channel) rows; keep overlapping unisons."""
    import mido

    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=int(60_000_000 / tempo), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    events = []
    for pitch, start, end, velocity, channel in notes:
        events.append((float(start), 0, "on", int(pitch), int(velocity), int(channel)))
        events.append((float(end), 1, "off", int(pitch), 0, int(channel)))
    events.sort()
    last_tick = 0
    ticks_per_sec = (tempo / 60.0) * 480
    for time_sec, _order, kind, pitch, velocity, channel in events:
        tick = int(round(time_sec * ticks_per_sec))
        delta = max(0, tick - last_tick)
        last_tick = tick
        msg_type = "note_on" if kind == "on" else "note_off"
        track.append(
            mido.Message(
                msg_type,
                note=pitch,
                velocity=velocity,
                channel=channel,
                time=delta,
            )
        )
    mid.save(str(path))


# Synthetic P2b export-evidence pairs. Not part of the 15-candidate P1 set /
# held-out split; labeled for construction review only.
P2B_EXPORT_EVIDENCE = (
    {
        "example_id": "synth-sustained-resume",
        "title": "Same-pitch sustained line resumes after short interruptions",
        "label": "synthetic_construction_pair",
        "notes": [
            (60, 0.0, 1.0, 80, 0),
            (60, 0.25, 0.5, 70, 1),
            (60, 0.75, 1.0, 70, 1),
            (60, 1.0, 1.5, 80, 0),
        ],
    },
    {
        "example_id": "synth-short-line-continues",
        "title": "Short repeating line continues after sustained hold ends",
        "label": "synthetic_construction_pair",
        "notes": [
            (60, 0.0, 1.0, 80, 0),
            (60, 0.25, 0.5, 70, 1),
            (60, 0.5, 0.75, 70, 1),
            (60, 0.75, 1.0, 70, 1),
            (60, 1.0, 1.25, 70, 1),
        ],
    },
)


def write_supplemental_p2b_evidence(
    out_dir: Path,
    *,
    render: bool = False,
) -> list[dict[str, Any]]:
    """Write matched v1/v2 renders for corrected voice pairs (not P1 candidates).

    Preserves the 15-example development/held-out splits unchanged. These
    folders are explicitly synthetic construction evidence for export/voice
    continuity review preparation — not musician-validated quality claims.
    """
    dest = Path(out_dir) / "supplemental_p2b"
    dest.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for spec in P2B_EXPORT_EVIDENCE:
        case_dir = dest / spec["example_id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        midi_path = case_dir / "input.mid"
        _write_multichannel_midi(midi_path, spec["notes"], tempo=120.0)
        original = midi_path.read_bytes()
        v1, _ingested = _build(
            midi_path, NotationSettings(), meter="4/4", tempo=120.0
        )
        assert midi_path.read_bytes() == original
        v2, _ = _build(
            midi_path,
            NotationSettings.readable_opt_in(),
            meter="4/4",
            tempo=120.0,
        )
        assert midi_path.read_bytes() == original
        (case_dir / "v1.musicxml").write_text(v1.musicxml, encoding="utf-8")
        (case_dir / "v2.musicxml").write_text(v2.musicxml, encoding="utf-8")
        if v1.score_midi:
            (case_dir / "v1.score.mid").write_bytes(v1.score_midi)
        if v2.score_midi:
            (case_dir / "v2.score.mid").write_bytes(v2.score_midi)
        assign1 = _assignments(v1)
        (case_dir / "note_index.json").write_text(
            json.dumps(
                {
                    "matched_by": "source_note_id",
                    "synthetic": True,
                    "label": spec["label"],
                    "notes": _note_index(assign1),
                    "staff_musical_printed_compared_separately": True,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        renders: list[dict[str, Any]] = []
        if render:
            for version, xml in (("v1", v1.musicxml), ("v2", v2.musicxml)):
                xml_path = case_dir / f"{version}.musicxml"
                osmd = _render_osmd(xml_path, case_dir / f"{version}_osmd")
                renders.append(
                    {
                        "version": version,
                        "osmd": {
                            key: osmd.get(key)
                            for key in ("returncode", "html", "png", "svg")
                        },
                    }
                )
        row = {
            "example_id": spec["example_id"],
            "title": spec["title"],
            "label": spec["label"],
            "permitted_use": "synthetic_repo_fixture",
            "package_role": "supplemental_p2b_export_evidence",
            "not_in_p1_candidate_set": True,
            "held_out_unchanged": True,
            "midi_sha256": hashlib.sha256(original).hexdigest(),
            "source_midi_unchanged": midi_path.read_bytes() == original,
            "algorithms": {
                "v1": v1.settings.algorithm_version,
                "v2": v2.settings.algorithm_version,
            },
            "note_count": assign1["count"],
            "musical_voices": assign1.get("musical_voices"),
            "renders": renders,
            "artifacts": {
                "input_midi": str(midi_path.relative_to(out_dir)),
                "v1_musicxml": str((case_dir / "v1.musicxml").relative_to(out_dir)),
                "v2_musicxml": str((case_dir / "v2.musicxml").relative_to(out_dir)),
                "v1_score_midi": (
                    str((case_dir / "v1.score.mid").relative_to(out_dir))
                    if (case_dir / "v1.score.mid").exists()
                    else None
                ),
                "v2_score_midi": (
                    str((case_dir / "v2.score.mid").relative_to(out_dir))
                    if (case_dir / "v2.score.mid").exists()
                    else None
                ),
            },
            "note": (
                "Synthetic construction pair for voice continuity / export "
                "verification. Not a P1 completion case; not musician-reviewed."
            ),
        }
        (case_dir / "case_report.json").write_text(
            json.dumps(row, indent=2) + "\n", encoding="utf-8"
        )
        rows.append(row)
    (dest / "README.md").write_text(
        "\n".join(
            [
                "# Supplemental P2b export evidence (synthetic)",
                "",
                "Corrected multi-channel voice-continuity pairs with matched",
                "v1/v2 MusicXML, score MIDI, and optional OSMD renders.",
                "",
                "- **Not** part of the 15-example P1 candidate set.",
                "- Held-out splits are unchanged.",
                "- Explicitly synthetic — construction-labeled, not musician quality.",
                "",
                "Cases:",
                *[f"- `{r['example_id']}` — {r['title']}" for r in rows],
                "",
            ]
        ),
        encoding="utf-8",
    )
    (dest / "index.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return rows


def _real_sample_checklist() -> str:
    return """# Real-sample review checklist

Use this for **live job** evidence destined for musician review. Reuses the
existing evaluation package / `review.json` structures — no new review app.

Keep synthetic package cases labeled `synthetic_repo_fixture`. Do not bind
older reviews to rebuilt artifact hashes without re-review.

## Per sample

| Field | Value |
|---|---|
| Job ID | |
| Engine commit / version evidence | |
| Algorithm (`performance-score-1` / `performance-score-2`) | |
| Original audio (path or storage key) | |
| Unedited output (MusicXML + score MIDI + playback) | |
| Corrected output (after edits; same IDs) | |
| Timestamp / measure cited | |
| Edits applied (`source_note_id` + fields) | |
| Correction time (minutes) | |
| Reviewer + `reviewed_at` (ISO) | |

## Workflow

1. Record engine SHA and job ID before exporting artifacts.
2. Save unedited MusicXML, score MIDI, and original audio alongside the job.
3. Apply corrections; save corrected exports without rewriting source MIDI.
4. Cite measure/timestamp and list each edit by `source_note_id`.
5. Fill `review.json` attribution + interpretation + correction-effort
   dimensions (same schema as the synthetic package).
6. Run report-only validation against live hashes:
   `python -m evaluation.musical_baseline --report-reviews …`
7. Mark acoustic accuracy only when audio + reference labels exist.

## Limits

- Synthetic fixtures do not prove acoustic accuracy or P1 completion.
- P1 remains incomplete until attributed real reviews exist.
- Default remains v1; v2 stays opt-in.
"""


def build_package(
    out_dir: Path | None = None,
    *,
    render: bool = False,
    eligible_only: bool = True,
) -> dict[str, Any]:
    dest = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    dest.mkdir(parents=True, exist_ok=True)
    inventory = asset_inventory()
    leaks = split_leakage()
    if leaks:
        raise RuntimeError(f"split leakage before package build: {leaks}")

    case_rows = []
    for candidate in candidates(eligible_only=eligible_only):
        case_rows.append(build_case(candidate, dest, render=render))

    supplemental = write_supplemental_p2b_evidence(dest, render=render)

    report = _assemble_package_report(
        dest, case_rows, inventory=inventory, mode="package"
    )
    report["supplemental_p2b"] = supplemental
    (dest / "inventory.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "package_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "package_report.md").write_text(_markdown_report(report), encoding="utf-8")
    (dest / "REVIEW_INSTRUCTIONS.md").write_text(_instructions(), encoding="utf-8")
    (dest / "REAL_SAMPLE_REVIEW_CHECKLIST.md").write_text(
        _real_sample_checklist(), encoding="utf-8"
    )
    write_review_index(dest)
    write_first_session_guide(dest)
    return report


def report_reviews(out_dir: Path | None = None) -> dict[str, Any]:
    """Validate and summarize existing reviews without rebuilding scores.

    Does not modify human-owned ``review.json`` / ``REVIEW_FORM.md``, score
    artifacts (MusicXML/MIDI), or ``artifact_fingerprint.json``. Regenerates
    package_report.* only. Validation recomputes live file hashes and never
    trusts a cached ``case_report.json`` fingerprint as evidence.
    """
    dest = Path(out_dir) if out_dir is not None else DEFAULT_OUT
    if not dest.is_dir():
        raise FileNotFoundError(f"review package not found: {dest}")
    inventory = asset_inventory()
    case_rows: list[dict[str, Any]] = []
    for candidate in candidates(eligible_only=True):
        case_dir = dest / candidate.split / candidate.example_id
        report_path = case_dir / CASE_REPORT_NAME
        if report_path.is_file():
            try:
                row = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                row = {
                    "example_id": candidate.example_id,
                    "composition_id": candidate.composition_id,
                    "performance_id": candidate.performance_id,
                    "split": candidate.split,
                    "source_id": candidate.source_id,
                    "meter": candidate.meter,
                    "dimensions": dimension_status_for(candidate),
                }
        else:
            row = {
                "example_id": candidate.example_id,
                "composition_id": candidate.composition_id,
                "performance_id": candidate.performance_id,
                "split": candidate.split,
                "source_id": candidate.source_id,
                "meter": candidate.meter,
                "dimensions": dimension_status_for(candidate),
            }
        # Drop any cached fingerprint embedded in case_report so assembly
        # cannot accidentally treat it as current evidence.
        row.pop("artifact_fingerprint", None)
        case_rows.append(row)

    report = _assemble_package_report(
        dest, case_rows, inventory=inventory, mode="report_only"
    )
    (dest / "package_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "package_report.md").write_text(_markdown_report(report), encoding="utf-8")
    # Refresh instructions (generated doc), not human reviews.
    (dest / "REVIEW_INSTRUCTIONS.md").write_text(_instructions(), encoding="utf-8")
    return report


def _instructions() -> str:
    return """# P1 musical baseline — review instructions

## Purpose

Assess short examples on **four independent dimensions**. Do not collapse them
into one pass/fail. Export success is not musical quality. Synthetic fixtures
do not prove acoustic accuracy or production readiness.

## Dimensions (keep separate)

1. **Acoustic accuracy** — only when suitable audio and reference labels exist.
   Most synthetic package cases are `not_applicable` and never count toward
   P1 completion.
2. **Musical interpretation accuracy** — meter, pickup, voices, rests,
   articulation, duration spelling. Required for review completion.
3. **Export integrity** — mechanical MusicXML/MIDI identity (package fills
   automated checks). Optional human overlay.
4. **Human correction effort** — minutes/edits to make the score usable.
   Required for review completion.

Valid statuses: `pass` | `fail` | `needs_work` | `not_reviewed` | `not_applicable`.
Optional per-version ratings: `dimensions.<name>.versions.v1` / `.v2`.

## Completion vs acceptance

Documented in code as `COMPLETION_CRITERIA` (`evaluation/musical_baseline/reviews.py`):

- **review_complete** requires: valid `review.json`, matching case identity,
  attribution (`reviewer` + ISO `reviewed_at`), **current** `artifact_binding`
  matching **live** artifact bytes (source MIDI, v1/v2 MusicXML, and playback
  MIDI when present), agreement with `artifact_fingerprint.json`, and both
  interpretation + correction effort rated `pass`/`fail`/`needs_work`.
- Playback hashes (`v1_score_midi_sha256`, `v2_score_midi_sha256`) are required
  binding fields. If a `*.score.mid` file is absent, bind `null`. Changing
  playback invalidates reviews that depend on it. Older reviews that omit
  these fields stay on disk but are not complete until migrated (re-copy from
  a verified fingerprint after `--package`, or re-review).
- Validation **recomputes** hashes from files on disk. Cached fingerprints
  inside `case_report.json` are never used as evidence. Missing, unreadable,
  malformed, or changed required artifacts prevent completion.
- `not_reviewed` / `not_applicable` / missing ratings do **not** count.
- Stale bindings (artifact hashes changed) retain feedback on disk but are
  **excluded** from completion counts until re-reviewed against new hashes.
- **musically_accepted** = review_complete AND interpretation `pass`.
  A complete review may still fail musically.

## Exact musician workflow (first real review)

1. Ensure the package exists (engineer may run `--package` once):
   `python -m evaluation.musical_baseline --package evaluation/musical_baseline/review_package`
2. Open one case, e.g. `development/dev-solo-detached/`.
3. Play `v1.score.mid` / `v2.score.mid`; open `v1.musicxml` / `v2.musicxml`.
4. Use `note_index.json` and `phrases/`; cite `source_note_id`.
5. Copy binding hashes from `artifact_fingerprint.json` into `review.json`
   → `artifact_binding` (include playback SHA-256 fields; template already
   includes them when first created; if you started from an older file,
   refresh these fields from the fingerprint after `--package`).
6. Fill `review.json` (authoritative):
   - `attribution.reviewer`, `attribution.reviewed_at` (ISO date)
   - `dimensions.musical_interpretation_accuracy.status`
   - `dimensions.human_correction_effort.status`
   - optional acoustic / export / notes / per-version ratings
7. Optionally annotate `REVIEW_FORM.md` (human-owned; rebuilds preserve it).
8. Ask an engineer (or yourself) to run **report-only** (does not rebuild scores,
   rewrite fingerprints, or touch your review files):
   `python -m evaluation.musical_baseline --report-reviews evaluation/musical_baseline/review_package`
9. Confirm your case appears under `review_complete` / `musically_accepted` in
   `package_report.md` as appropriate. If validation lists `changed_files` /
   `missing_files`, the scores on disk no longer match the review binding.

## Rebuild safety

- `python -m evaluation.musical_baseline --package …` and `--render` regenerate
  scores and `artifact_fingerprint.json` but **never overwrite** existing
  `review.json` or filled `REVIEW_FORM.md` (including malformed files).
- `--report-reviews` updates generated reports only; it never rewrites reviews,
  scores, source MIDI, or fingerprints to hide mismatches.
- Fresh blank templates are written only when those files are absent.
- `REVIEW_FORM.template.md` is always refreshed as a generated reference.

## Contracts

- Default remains `performance-score-1`; `performance-score-2` is opt-in.
- Preserve original MIDI bytes, source identities, performed timing, tuplets,
  ties, accepted corrections, and user locks.
- Compare staff, musical-voice grouping, and printed lanes separately.
- Do not retune the engine merely because case 138 printed lanes move.

## Supplemental + real samples

- `supplemental_p2b/` holds synthetic corrected voice pairs (sustained
  resume, short-line continues) with matched renders/playback. Not part of
  the 15-candidate set; not musician-validated.
- `dev-pickup` (and related tempo cases in the package) remain the pickup /
  tempo review examples.
- For live jobs, use `REAL_SAMPLE_REVIEW_CHECKLIST.md` (job ID, engine
  evidence, audio, unedited/corrected outputs, timestamp/measure, edits,
  correction time).
"""


def _markdown_report(report: dict[str, Any]) -> str:
    summary = report.get("review_summary") or {}
    lines = [
        "# P1 musical baseline review package",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Mode: `{report.get('mode', 'package')}`",
        f"- Cases packaged: **{report['candidate_count']}** "
        f"(development {report['development_count']}, "
        f"held-out {report['held_out_count']})",
        f"- Default algorithm: `{report['default_algorithm_version']}`",
        f"- Opt-in algorithm: `{report['opt_in_algorithm_version']}`",
        f"- Splits disjoint: `{report['splits_disjoint']}`",
        f"- Review complete: **{report['musician_reviewed_complete']}**",
        f"- Musically accepted: **{report.get('musically_accepted_count', 0)}**",
        f"- Reviewed but not accepted: **{report.get('reviewed_but_not_accepted_count', 0)}**",
        f"- Stale reviews: **{summary.get('stale_count', 0)}**",
        f"- P1 complete: **{report['p1_complete']}**",
        f"- Reason: {report['p1_complete_reason']}",
        "",
        "## Supplemental P2b export evidence",
        "",
        "- Synthetic voice-continuity pairs (multi-channel) live under "
        "`supplemental_p2b/`. They are **not** P1 candidates and do not "
        "alter held-out splits.",
        "- Real-sample workflow: `REAL_SAMPLE_REVIEW_CHECKLIST.md`.",
        "",
        "## Family coverage",
        "",
    ]
    coverage = report["family_coverage"]
    for family, ids in coverage["covered"].items():
        mark = "ok" if ids else "MISSING"
        lines.append(
            f"- `{family}`: {mark} ({', '.join(f'`{i}`' for i in ids) or '—'})"
        )
    lines.extend(["", "## Cases", ""])
    lines.append(
        "| Example | Split | Complete | Accepted | Stale | Interp | Export | Correction | Acoustic |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for row in report["cases"]:
        dims = row.get("dimensions") or {}
        review = row.get("review") or {}
        validation = review.get("validation") or {}
        lines.append(
            "| `{eid}` | `{split}` | `{complete}` | `{accepted}` | `{stale}` | "
            "`{interp}` | `{export}` | `{corr}` | `{ac}` |".format(
                eid=row["example_id"],
                split=row["split"],
                complete=review.get("review_complete"),
                accepted=review.get("musically_accepted"),
                stale=validation.get("binding_stale"),
                interp=(dims.get("musical_interpretation_accuracy") or {}).get(
                    "status"
                ),
                export=(dims.get("export_integrity") or {}).get("status"),
                corr=(dims.get("human_correction_effort") or {}).get("status"),
                ac=(dims.get("acoustic_accuracy") or {}).get("status"),
            )
        )
    lines.extend(["", "## Gaps", ""])
    for gap in report["inventory_summary"]["gaps"]:
        lines.append(f"- `{gap['id']}` ({gap['status']}): {gap['detail']}")
    lines.extend(["", "## Commands", "", "```bash"])
    lines.extend(report["commands"])
    lines.extend(["```", ""])
    return "\n".join(lines)


def inventory_markdown(inventory: dict[str, Any] | None = None) -> str:
    inv = inventory if inventory is not None else asset_inventory()
    lines = [
        "# P1 asset inventory",
        "",
        f"- Package-eligible candidates: **{inv['candidate_counts']['package_eligible']}**",
        f"- Musician-reviewed: **{inv['candidate_counts']['musician_reviewed']}**",
        f"- Splits disjoint: `{inv['splits_disjoint']}`",
        f"- P1 complete: `{inv['p1_complete']}`",
        f"- Reason: {inv['p1_complete_reason']}",
        "",
        "## Candidates",
        "",
        "| Example | Split | Composition | Families | License | Reviewed | Acoustic labels |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in inv["candidates"]:
        lines.append(
            "| `{eid}` | `{split}` | `{comp}` | {fam} | `{use}` | `{rev}` | `{ac}` |".format(
                eid=row["example_id"],
                split=row["split"],
                comp=row["composition_id"],
                fam=", ".join(row["families"]),
                use=row["permitted_use"],
                rev=row["musician_reviewed"],
                ac=row["acoustic_labels_available"],
            )
        )
    lines.extend(["", "## Gaps", ""])
    for gap in inv["gaps"]:
        lines.append(
            f"- `{gap['id']}` @ `{gap['location']}` — **{gap['status']}**: {gap['detail']}"
        )
    lines.extend(
        [
            "",
            "## NotaTestSamples (present, not package-claimed as licensed)",
            "",
        ]
    )
    samples = inv["assets"]["nota_test_samples"]
    if not samples:
        lines.append("- none found")
    for sample in samples:
        lines.append(
            f"- `{sample['id']}` audio=`{sample.get('audio')}` "
            f"license=`{sample.get('license')}` reviewed=`{sample.get('musician_reviewed')}`"
        )
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_OUT",
    "build_case",
    "build_package",
    "inventory_markdown",
    "report_reviews",
]
