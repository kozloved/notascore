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
                "- Rating (pass / fail / needs_work / not_reviewed): ________",
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

    (case_dir / "REVIEW_FORM.md").write_text(
        _review_form_markdown(candidate, dimensions), encoding="utf-8"
    )
    review_json = {
        "example_id": candidate.example_id,
        "composition_id": candidate.composition_id,
        "performance_id": candidate.performance_id,
        "split": candidate.split,
        "attribution": {
            "reviewer": None,
            "role": None,
            "reviewed_at": None,
            "contact": None,
        },
        "dimensions": dimensions,
        "musician_reviewed": False,
        "invented_scores_forbidden": True,
    }
    (case_dir / "review.json").write_text(
        json.dumps(review_json, indent=2) + "\n", encoding="utf-8"
    )

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
        "musician_reviewed": False,
        "midi_sha256": midi_sha,
        "performance_sha256": ingested.performance.midi_sha256,
        "source_midi_unchanged": midi_path.read_bytes() == original,
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
        "dimensions": dimensions,
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
            "review_form": str((case_dir / "REVIEW_FORM.md").relative_to(out_dir)),
            "review_json": str((case_dir / "review.json").relative_to(out_dir)),
            "phrases": str((case_dir / "phrases").relative_to(out_dir)),
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
        },
    }
    (case_dir / "case_report.json").write_text(
        json.dumps(row, indent=2) + "\n", encoding="utf-8"
    )
    return row


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

    # Interpretation + correction must be human-attributed for P1 completion.
    human_complete = 0
    for row in case_rows:
        interp = row["dimensions"]["musical_interpretation_accuracy"]
        effort = row["dimensions"]["human_correction_effort"]
        if (
            interp.get("reviewer")
            and effort.get("reviewer")
            and interp.get("status") not in {"unreviewed", "automated_pending"}
            and effort.get("status") not in {"unreviewed", "automated_pending"}
        ):
            human_complete += 1

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(dest),
        "default_algorithm_version": ALGORITHM_VERSION_CURRENT,
        "opt_in_algorithm_version": ALGORITHM_VERSION_READABLE,
        "candidate_count": len(case_rows),
        "development_count": sum(1 for r in case_rows if r["split"] == "development"),
        "held_out_count": sum(1 for r in case_rows if r["split"] == "held_out"),
        "family_coverage": family_coverage(),
        "split_leakage": [],
        "splits_disjoint": True,
        "musician_reviewed_complete": human_complete,
        "p1_complete": False,
        "p1_complete_reason": (
            f"{human_complete}/{len(case_rows)} cases have attributed interpretation "
            "and correction-effort reviews. Do not mark P1 complete without them."
        ),
        "inventory_summary": {
            "gaps": inventory["gaps"],
            "candidate_counts": inventory["candidate_counts"],
            "nota_test_samples": len(inventory["assets"]["nota_test_samples"]),
        },
        "cases": case_rows,
        "commands": [
            "cd audio2score-week4/backend",
            "python -m evaluation.musical_baseline --inventory",
            "python -m evaluation.musical_baseline --package evaluation/musical_baseline/review_package",
            "python -m evaluation.musical_baseline --package evaluation/musical_baseline/review_package --render",
            "python -m pytest -q tests/test_musical_baseline.py",
        ],
    }
    (dest / "inventory.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "package_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (dest / "package_report.md").write_text(_markdown_report(report), encoding="utf-8")
    (dest / "REVIEW_INSTRUCTIONS.md").write_text(_instructions(), encoding="utf-8")
    return report


def _instructions() -> str:
    return """# P1 musical baseline — review instructions

## Purpose

Assess short examples on **four independent dimensions**. Do not collapse them
into one pass/fail. Export success is not musical quality.

## Dimensions

1. **Acoustic accuracy** — only when suitable audio and reference labels exist.
   Most synthetic package cases mark this `not_applicable`.
2. **Musical interpretation accuracy** — meter, pickup, voices, rests,
   articulation, duration spelling.
3. **Export integrity** — mechanical MusicXML/MIDI identity (may be pre-filled).
4. **Human correction effort** — minutes/edits to make the score usable.

Unreviewed dimensions must stay unreviewed. Do not invent scores.

## How to review

1. Open each case under `development/` or `held_out/`.
2. Play `v1.score.mid` / `v2.score.mid` when present.
3. Open `v1.musicxml` / `v2.musicxml` (and OSMD HTML if generated with `--render`).
4. Use `note_index.json` and phrase extracts; cite `source_note_id`.
5. Fill `REVIEW_FORM.md` and copy attribution + ratings into `review.json`.

## Contracts

- Default remains `performance-score-1`; `performance-score-2` is opt-in.
- Preserve original MIDI bytes, source identities, performed timing, tuplets,
  ties, accepted corrections, and user locks.
- Compare staff, musical-voice grouping, and printed lanes separately.
- Do not retune the engine merely because case 138 printed lanes move.

## Attribution required

Every completed review needs reviewer name, date, and which dimensions were
actually assessed. Gaps stay listed in `inventory.json`.
"""


def _markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# P1 musical baseline review package",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Cases packaged: **{report['candidate_count']}** "
        f"(development {report['development_count']}, "
        f"held-out {report['held_out_count']})",
        f"- Default algorithm: `{report['default_algorithm_version']}`",
        f"- Opt-in algorithm: `{report['opt_in_algorithm_version']}`",
        f"- Splits disjoint: `{report['splits_disjoint']}`",
        f"- Musician-reviewed complete: **{report['musician_reviewed_complete']}**",
        f"- P1 complete: **{report['p1_complete']}**",
        f"- Reason: {report['p1_complete_reason']}",
        "",
        "## Family coverage",
        "",
    ]
    coverage = report["family_coverage"]
    for family, ids in coverage["covered"].items():
        mark = "ok" if ids else "MISSING"
        lines.append(f"- `{family}`: {mark} ({', '.join(f'`{i}`' for i in ids) or '—'})")
    lines.extend(["", "## Cases", ""])
    lines.append(
        "| Example | Split | Source | Meter | Interp | Export | Correction | Acoustic |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in report["cases"]:
        dims = row["dimensions"]
        lines.append(
            "| `{eid}` | `{split}` | `{src}` | {meter} | `{interp}` | `{export}` | `{corr}` | `{ac}` |".format(
                eid=row["example_id"],
                split=row["split"],
                src=row["source_id"],
                meter=row["meter"],
                interp=dims["musical_interpretation_accuracy"]["status"],
                export=dims["export_integrity"]["status"],
                corr=dims["human_correction_effort"]["status"],
                ac=dims["acoustic_accuracy"]["status"],
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
]
