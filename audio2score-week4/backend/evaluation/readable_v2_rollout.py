"""Broader readable-v1 vs opt-in v2 comparison on existing evaluation material.

Does not change production defaults. Real-audio transcription accuracy is out
of scope. Fewer rests or ties are reported, not scored as better.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmark.fixtures.catalog import all_cases
from benchmark.fixtures.generate import write_midi
from evaluation.notation_correctness_evidence import (
    _build,
    _frontend_pdf,
    _pdf_record,
    _render_osmd,
    _settings,
    _visual_record,
    expected_osmd_pages,
    inspect_xml,
)
from evaluation.notation_fixtures import FIXTURE_META, FIXTURES
from evaluation.readable_v2_cases import (
    EXPECTED_NOTATION,
    HELDOUT_CASES,
    HELDOUT_META,
    READABLE_V2_CASES,
)
from mir.notation_settings import (
    ALGORITHM_VERSION_CURRENT,
    ALGORITHM_VERSION_READABLE,
    NotationSettings,
)

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
EVALUATION = HERE
PAIRED = HERE / "paired_corpus"
REALWORLD_LOCAL = BACKEND / "benchmark" / "realworld" / "local"

# Last-note triplet-pulse fill was tuned on these. Everything else is held-out
# of that heuristic, including unused fixtures and the synthetic corpus.
TUNING_SET = frozenset(
    {
        "I_detached_triplet_groups",
        "J_intentional_short_triplet_rests",
        "K_repeated_triplet_pitches",
        "L_held_voice_under_triplets",
        "mixed_tuplets",
    }
)

# Representative musical families requested for this milestone.
ROLLOUT_CASES = [
    # monophonic phrases and intentional rests
    ("A_detached_regular_line", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}, "synthetic_fixture", False),
    ("B_short_notes_with_rests", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}, "synthetic_fixture", False),
    ("humanized_quarters", FIXTURES, "notation", FIXTURE_META["humanized_quarters"], "synthetic_fixture", True),
    ("short_rests_repeats", FIXTURES, "notation", FIXTURE_META["short_rests_repeats"], "synthetic_fixture", True),
    # mixed straight/triplet
    ("mixed_tuplets", FIXTURES, "notation", FIXTURE_META["mixed_tuplets"], "synthetic_fixture", False),
    ("I_detached_triplet_groups", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}, "synthetic_fixture", False),
    ("J_intentional_short_triplet_rests", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}, "synthetic_fixture", False),
    ("mixed_families_after_bar", HELDOUT_CASES, "readable_v2", HELDOUT_META["mixed_families_after_bar"], "synthetic_heldout", True),
    ("irregular_triplet_intervals", HELDOUT_CASES, "readable_v2", HELDOUT_META["irregular_triplet_intervals"], "synthetic_heldout", True),
    # phrase endings and tempo variation
    ("final_short_then_silence", HELDOUT_CASES, "readable_v2", HELDOUT_META["final_short_then_silence"], "synthetic_heldout", True),
    ("rubato_pickup", FIXTURES, "notation", FIXTURE_META["rubato_pickup"], "synthetic_fixture", True),
    # syncopation and 6/8
    ("syncopation", FIXTURES, "notation", FIXTURE_META["syncopation"], "synthetic_fixture", True),
    ("meter_6_8", FIXTURES, "notation", FIXTURE_META["meter_6_8"], "synthetic_fixture", True),
    # repeated notes and sustain pedal
    ("C_repeated_attacks_under_pedal", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}, "synthetic_fixture", False),
    ("E_repeated_attacks_no_pedal", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}, "synthetic_fixture", False),
    # independent held voices
    ("G_held_voice_same_staff", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}, "synthetic_fixture", False),
    ("L_held_voice_under_triplets", READABLE_V2_CASES, "readable_v2", {"meter": "4/4", "tempo": 120}, "synthetic_fixture", False),
    ("independent_voices_mixed_release", HELDOUT_CASES, "readable_v2", HELDOUT_META["independent_voices_mixed_release"], "synthetic_heldout", True),
    # mixed-release chords and crossing hands
    ("mixed_release_chord", FIXTURES, "notation", FIXTURE_META["mixed_release_chord"], "synthetic_fixture", True),
    ("unison_crossing", FIXTURES, "notation", FIXTURE_META["unison_crossing"], "synthetic_fixture", True),
    ("near_barline_short_release", HELDOUT_CASES, "readable_v2", HELDOUT_META["near_barline_short_release"], "synthetic_heldout", True),
    ("long_monophonic_phrase", HELDOUT_CASES, "readable_v2", HELDOUT_META["long_monophonic_phrase"], "synthetic_heldout", True),
]

RENDER_LABELS = frozenset(
    {
        "B_short_notes_with_rests",
        "mixed_tuplets",
        "meter_6_8",
        "mixed_release_chord",
        "final_short_then_silence",
        "near_barline_short_release",
        "independent_voices_mixed_release",
        "long_monophonic_phrase",
        "unison_crossing",
    }
)

CORPUS_FOCUS = (
    "c_major_quarters",
    "melody_and_bass",
    "hand_crossing",
    "triplets",
    "syncopation",
    "compound_6_8",
    "midi_chords_and_melody",
)


def _assignments(result) -> dict:
    notes = result.editor_model.get("notes") or []
    return {
        "count": len(notes),
        "hands": sorted({str(n.get("hand") or "") for n in notes}),
        "voices": sorted({int(n.get("voice") or 0) for n in notes}),
        "source_ids": [n.get("source_note_id") or n.get("id") for n in notes],
        "starts": [round(float(n["start"]), 4) for n in notes],
        "durations": [round(float(n["duration"]), 4) for n in notes],
        "pitches": [int(n["pitch"]) for n in notes],
    }


def _surface(xml_text: str) -> dict:
    inspected = inspect_xml(xml_text)
    return {
        "printed_notes": inspected["printed_notes"],
        "rest_count": inspected.get("rest_count", 0),
        "tied_fragments": inspected["tied_fragments"],
        "tuplet_notes": inspected["tuplet_notes"],
        "mixed_chord_marks": inspected["mixed_chord_marks"],
        "measure_count": inspected["shape"]["measure_count"],
        "time_signatures": inspected["shape"]["time_signatures"],
        "trailing_empty_measures": inspected["shape"]["trailing_empty_measures"],
        "part_count": inspected["shape"]["part_count"],
    }


def _timing_delta(left: dict, right: dict) -> dict:
    return {
        "starts_equal": left["starts"] == right["starts"],
        "durations_equal": left["durations"] == right["durations"],
        "pitches_equal": left["pitches"] == right["pitches"],
        "source_ids_equal": left["source_ids"] == right["source_ids"],
        "hands_equal": left["hands"] == right["hands"],
        "voices_equal": left["voices"] == right["voices"],
        "duration_changes": [
            {
                "index": i,
                "pitch": left["pitches"][i] if i < len(left["pitches"]) else None,
                "v1": left["durations"][i] if i < len(left["durations"]) else None,
                "v2": right["durations"][i] if i < len(right["durations"]) else None,
            }
            for i in range(max(len(left["durations"]), len(right["durations"])))
            if (
                i >= len(left["durations"])
                or i >= len(right["durations"])
                or left["durations"][i] != right["durations"][i]
            )
        ],
    }


def _real_midi_available() -> dict:
    """Look for licensed/reference performances. Do not relabel synthetics."""
    eval_audio = []
    for split in ("development", "holdout", "real_world", "human_reviewed"):
        root = EVALUATION / split
        if not root.exists():
            continue
        eval_audio.extend(
            str(path.relative_to(BACKEND))
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".wav", ".mp3", ".flac", ".mid", ".midi"}
        )
    realworld = []
    if REALWORLD_LOCAL.exists():
        realworld = [
            str(path.relative_to(BACKEND))
            for path in REALWORLD_LOCAL.rglob("*")
            if path.is_file() and path.suffix.lower() in {".wav", ".mp3", ".flac", ".mid", ".midi"}
        ]
    paired_slots_empty = not any(
        (PAIRED / name).is_dir() and any((PAIRED / name).iterdir())
        for name in ("development", "holdout", "real_world", "human_reviewed")
        if (PAIRED / name).exists()
    )
    return {
        "evaluation_audio_or_midi": eval_audio,
        "realworld_local": realworld,
        "paired_corpus_populated": not paired_slots_empty and bool(eval_audio),
        "real_performances_available": bool(eval_audio or realworld),
        "gap": (
            None
            if eval_audio or realworld
            else (
                "No licensed or reference performance MIDI/audio is present in "
                "this checkout. Committed material is synthetic_midi from "
                "evaluation fixtures and benchmark.fixtures.catalog. "
                "evaluation/paired_corpus slots are empty. "
                "benchmark/realworld/local is gitignored."
            )
        ),
    }


def inventory() -> dict:
    real = _real_midi_available()
    fixtures = []
    for name, meta in FIXTURE_META.items():
        fixtures.append(
            {
                "id": name,
                "kind": "synthetic_midi",
                "source": "evaluation.notation_fixtures",
                "performance": "synthetic_fixture",
                "held_out_of_last_note_tune": name not in TUNING_SET,
                "meter": meta["meter"],
                "tempo": meta["tempo"],
            }
        )
    cases = []
    for name in READABLE_V2_CASES:
        cases.append(
            {
                "id": name,
                "kind": "synthetic_midi",
                "source": "evaluation.readable_v2_cases",
                "performance": "synthetic_fixture",
                "held_out_of_last_note_tune": name not in TUNING_SET,
                "meter": "4/4",
                "tempo": 120,
            }
        )
    heldout = []
    for name, meta in HELDOUT_META.items():
        heldout.append(
            {
                "id": name,
                "kind": "synthetic_midi",
                "source": "evaluation.readable_v2_cases.HELDOUT_CASES",
                "performance": "synthetic_heldout",
                "held_out_of_last_note_tune": True,
                "meter": meta["meter"],
                "tempo": meta["tempo"],
            }
        )
    corpus = []
    for spec in all_cases():
        corpus.append(
            {
                "id": spec.case_id,
                "kind": "synthetic_midi",
                "source": "benchmark.fixtures.catalog",
                "performance": "synthetic_corpus",
                "held_out_of_last_note_tune": True,
                "meter": spec.time_signature,
                "tempo": spec.tempo_bpm,
                "category": spec.category,
                "copyrighted": False,
            }
        )
    return {
        "evidence_kind": "synthetic_midi",
        "real_audio_evidence": False,
        "real_material": real,
        "default_algorithm_version": NotationSettings().algorithm_version,
        "opt_in_algorithm_version": NotationSettings.readable_opt_in().algorithm_version,
        "tuning_set": sorted(TUNING_SET),
        "fixtures": fixtures,
        "readable_v2_cases": cases,
        "heldout_cases": heldout,
        "corpus": corpus,
        "note": (
            "All committed MIDI is generated. Do not describe these as real "
            "performances. Real-audio transcription accuracy is a separate "
            "evaluation and is not used for this rollout decision."
        ),
    }


def _compare_pair(midi_path: Path, *, meter: str, tempo: float) -> dict:
    original = midi_path.read_bytes()
    v1, ingested = _build(midi_path, _settings("notation"), meter=meter, tempo=tempo)
    assert midi_path.read_bytes() == original
    v2, _ = _build(midi_path, _settings("readable_v2"), meter=meter, tempo=tempo)
    assert midi_path.read_bytes() == original
    assign1 = _assignments(v1)
    assign2 = _assignments(v2)
    surface1 = _surface(v1.musicxml)
    surface2 = _surface(v2.musicxml)
    timing = _timing_delta(assign1, assign2)
    rest_delta = surface2["rest_count"] - surface1["rest_count"]
    tie_delta = surface2["tied_fragments"] - surface1["tied_fragments"]
    return {
        "midi_sha256": hashlib.sha256(original).hexdigest(),
        "performance_sha256": ingested.performance.midi_sha256,
        "source_midi_unchanged": midi_path.read_bytes() == original,
        "ingested_meter": ingested.time_sig_hint,
        "v1": {
            "algorithm_version": v1.settings.algorithm_version,
            "assignments": assign1,
            "surface": surface1,
            "musicxml": v1.musicxml,
        },
        "v2": {
            "algorithm_version": v2.settings.algorithm_version,
            "assignments": assign2,
            "surface": surface2,
            "musicxml": v2.musicxml,
        },
        "timing": timing,
        "measure_integrity": {
            "v1": surface1["time_signatures"],
            "v2": surface2["time_signatures"],
            "equal": surface1["time_signatures"] == surface2["time_signatures"]
            and surface1["measure_count"] == surface2["measure_count"],
        },
        "hand_voice": {
            "v1_hands": assign1["hands"],
            "v2_hands": assign2["hands"],
            "v1_voices": assign1["voices"],
            "v2_voices": assign2["voices"],
            "equal": assign1["hands"] == assign2["hands"]
            and assign1["voices"] == assign2["voices"],
        },
        "rest_count": {"v1": surface1["rest_count"], "v2": surface2["rest_count"], "delta": rest_delta},
        "tie_count": {
            "v1": surface1["tied_fragments"],
            "v2": surface2["tied_fragments"],
            "delta": tie_delta,
        },
        "fewer_rests_not_better": True,
        "fewer_ties_not_better": True,
        "identical_written": timing["starts_equal"]
        and timing["durations_equal"]
        and surface1 == surface2,
    }


def _write_render(case_dir: Path, label: str, xml_text: str, version: str) -> dict:
    xml_path = case_dir / f"{version}.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")
    osmd_dir = case_dir / f"{version}_osmd"
    render = _render_osmd(xml_path, osmd_dir)
    visual = _visual_record(render, osmd_dir)
    html = osmd_dir / "osmd_preview.html"
    pdf = {"skipped": True, "reason": "OSMD HTML missing"}
    pdf_path = case_dir / f"{version}_sheetresult.pdf"
    if html.exists():
        pdf = _frontend_pdf(html, pdf_path)
    record = _pdf_record(pdf, pdf_path, expected_pages=expected_osmd_pages(osmd_dir))
    return {
        "label": label,
        "version": version,
        "osmd": {key: render.get(key) for key in ("returncode", "html", "png", "svg")},
        "visual": visual,
        "pdf": record,
        "mixed_chord_renderer_limitation": label == "mixed_release_chord",
    }


def _corpus_row(spec, tmp: Path) -> dict:
    midi_path = tmp / f"{spec.case_id}.mid"
    write_midi(spec, midi_path)
    compared = _compare_pair(
        midi_path, meter=spec.time_signature, tempo=float(spec.tempo_bpm)
    )
    compared.pop("v1")
    compared.pop("v2")
    return {
        "label": spec.case_id,
        "fixture": spec.case_id,
        "family": spec.category,
        "provenance": {
            "kind": "synthetic_midi",
            "source": "benchmark.fixtures.catalog",
            "performance": "synthetic_corpus",
            "copyrighted": False,
            "held_out_of_last_note_tune": True,
        },
        "expected_meter": spec.time_signature,
        **compared,
    }


def compare_case(label: str, catalog, meta: dict, provenance: str, held_out: bool, tmp: Path) -> dict:
    midi_path = tmp / f"{label}.mid"
    catalog[label](midi_path)
    compared = _compare_pair(midi_path, meter=str(meta["meter"]), tempo=float(meta["tempo"]))
    musicxml_v1 = compared["v1"].pop("musicxml")
    musicxml_v2 = compared["v2"].pop("musicxml")
    row = {
        "label": label,
        "fixture": label,
        "provenance": {
            "kind": "synthetic_midi",
            "source": provenance,
            "performance": provenance,
            "held_out_of_last_note_tune": held_out or label not in TUNING_SET,
        },
        "tuning_set": label in TUNING_SET,
        "expected": EXPECTED_NOTATION.get(label),
        "expected_meter": str(meta["meter"]),
        **compared,
        "musicxml": {"v1": musicxml_v1, "v2": musicxml_v2},
    }
    return row


def recommend(report: dict) -> dict:
    """Recommend continued opt-in unless the held-out set is clean."""
    remaining = []
    for row in report["cases"]:
        if row.get("identical_written"):
            continue
        label = row["label"]
        expected = (row.get("expected") or {}).get("release") or ""
        durations_changed = not row["timing"]["durations_equal"]
        if label == "final_short_then_silence" and durations_changed:
            last_v2 = (row["v2"]["assignments"]["durations"] or [None])[-1]
            last_v1 = (row["v1"]["assignments"]["durations"] or [None])[-1]
            if last_v2 is not None and last_v1 is not None and last_v2 > last_v1 + 0.05:
                remaining.append(
                    {
                        "case": label,
                        "issue": "v2 lengthens the intentional final short note",
                        "v1_last": last_v1,
                        "v2_last": last_v2,
                    }
                )
        if label == "near_barline_short_release" and durations_changed:
            last_v2 = (row["v2"]["assignments"]["durations"] or [None])[-1]
            if last_v2 is not None and last_v2 >= 0.24:
                remaining.append(
                    {
                        "case": label,
                        "issue": "v2 fills a short near-barline note to the bar",
                        "v2_last": last_v2,
                    }
                )
        if label == "irregular_triplet_intervals" and durations_changed:
            remaining.append(
                {
                    "case": label,
                    "issue": "v2 changed irregular intervals; confirm it did not invent 1/3",
                    "duration_changes": row["timing"]["duration_changes"],
                }
            )
        if label == "independent_voices_mixed_release":
            bass_v1 = next(
                (d for p, d in zip(row["v1"]["assignments"]["pitches"], row["v1"]["assignments"]["durations"]) if p == 48),
                None,
            )
            bass_v2 = next(
                (
                    d
                    for p, d in zip(row["v2"]["assignments"]["pitches"], row["v2"]["assignments"]["durations"])
                    if p == 48
                ),
                None,
            )
            if bass_v1 and bass_v2 and bass_v2 + 1e-6 < bass_v1:
                remaining.append(
                    {
                        "case": label,
                        "issue": "v2 clipped the independent held bass",
                        "v1_bass": bass_v1,
                        "v2_bass": bass_v2,
                    }
                )
    if report["inventory"]["real_material"]["gap"]:
        remaining.append(
            {
                "case": "real_performances",
                "issue": report["inventory"]["real_material"]["gap"],
            }
        )
    default_is_v1 = (
        report["inventory"]["default_algorithm_version"] == ALGORITHM_VERSION_CURRENT
    )
    if remaining or not default_is_v1:
        decision = "continued_opt_in"
        rationale = (
            "Keep performance-score-2 opt-in. Remaining regressions or missing "
            "real-performance evidence are listed below. Do not migrate existing "
            "jobs or change the default because synthetic tests pass."
        )
    else:
        decision = "controlled_new_job_default"
        rationale = (
            "Held-out synthetic comparison is clean. A reversible versioned "
            "setting could default new jobs to performance-score-2. Existing "
            "jobs stay on performance-score-1."
        )
    return {
        "decision": decision,
        "rationale": rationale,
        "remaining": remaining,
        "default_algorithm_version": report["inventory"]["default_algorithm_version"],
        "opt_in_setting": {
            "interpretation": "readable",
            "algorithm_version": ALGORITHM_VERSION_READABLE,
        },
        "reversible": True,
        "migrate_existing_jobs": False,
    }


def _markdown(report: dict) -> str:
    rec = report["recommendation"]
    lines = [
        "# readable-v2 rollout comparison",
        "",
        "Production default remains `performance-score-1`. `performance-score-2` is opt-in.",
        "Fewer rests or ties are not treated as better. Real-audio transcription is out of scope.",
        "",
        "## Provenance",
        "",
        f"- Evidence kind: `{report['inventory']['evidence_kind']}`",
        f"- Real performances available: `{report['inventory']['real_material']['real_performances_available']}`",
        f"- Default algorithm: `{report['inventory']['default_algorithm_version']}`",
        f"- Opt-in algorithm: `{report['inventory']['opt_in_algorithm_version']}`",
        f"- Tuning set (last-note pulse): {', '.join(f'`{name}`' for name in report['inventory']['tuning_set'])}",
        "",
    ]
    if report["inventory"]["real_material"]["gap"]:
        lines.extend(
            [
                "### Real-material gap",
                "",
                report["inventory"]["real_material"]["gap"],
                "",
            ]
        )
    lines.extend(
        [
            "## Recommendation",
            "",
            f"**{rec['decision']}**",
            "",
            rec["rationale"],
            "",
        ]
    )
    if rec["remaining"]:
        lines.append("### Remaining issues")
        lines.append("")
        for item in rec["remaining"]:
            lines.append(f"- `{item['case']}`: {item['issue']}")
        lines.append("")
    lines.extend(
        [
            "## Cases",
            "",
            "| Case | Held-out | MIDI preserved | Written identical | Rests v1→v2 | Ties v1→v2 | Measures | Hands/voices |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in report["cases"] + report["corpus"]:
        lines.append(
            "| `{label}` | {held} | {midi} | {ident} | {r1}→{r2} | {t1}→{t2} | {meas} | {hv} |".format(
                label=row["label"],
                held="yes" if row.get("provenance", {}).get("held_out_of_last_note_tune") else "no",
                midi="yes" if row.get("source_midi_unchanged") else "NO",
                ident="yes" if row.get("identical_written") else "no",
                r1=row["rest_count"]["v1"],
                r2=row["rest_count"]["v2"],
                t1=row["tie_count"]["v1"],
                t2=row["tie_count"]["v2"],
                meas="ok" if row["measure_integrity"]["equal"] else "DIFF",
                hv="ok" if row["hand_voice"]["equal"] else "DIFF",
            )
        )
    lines.extend(["", "## Duration changes (not an automatic improvement)", ""])
    for row in report["cases"]:
        changes = row["timing"]["duration_changes"]
        if not changes:
            continue
        lines.append(f"### `{row['label']}`")
        if row.get("expected"):
            lines.append(f"- Expected release: {row['expected']['release']}")
        for change in changes[:12]:
            lines.append(
                f"- index {change['index']} pitch {change['pitch']}: "
                f"v1={change['v1']} v2={change['v2']}"
            )
        lines.append("")
    if report.get("renders"):
        lines.extend(["## Rendered exports", ""])
        for render in report["renders"]:
            pdf = render["pdf"]
            visual = render["visual"]
            lines.append(
                f"- `{render['label']}` {render['version']}: export_completed="
                f"{pdf.get('export_completed')} parsed={pdf.get('pdf_parsed')} "
                f"page_count_verified={pdf.get('page_count_verified')} "
                f"pages_rendered={visual.get('pages_rendered')} "
                f"visual_review_completed={visual.get('visual_review_completed')} "
                f"status={pdf.get('status')} reason={pdf.get('reason')}"
            )
            if render.get("mixed_chord_renderer_limitation"):
                lines.append(
                    "  - OSMD mixed-chord limitation: per-member marks are in "
                    "MusicXML; the renderer may still show a unioned chord mark."
                )
        lines.append("")
    lines.extend(
        [
            "## Commands",
            "",
            "```bash",
            "cd audio2score-week4/backend",
            "python -m pytest -q tests/test_export_evidence_structure.py tests/test_readable_v2_rollout.py tests/test_readable_v2_cases.py",
            "python -m evaluation.readable_v2_rollout evaluation/readable_v2_rollout/out",
            "python -m evaluation.readable_v2_rollout evaluation/readable_v2_rollout/out --render",
            "```",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def run(out_dir: Path, *, render: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    inv = inventory()
    cases = []
    renders = []
    for label, catalog, _kind, meta, provenance, held_out in ROLLOUT_CASES:
        case_dir = out_dir / label
        case_dir.mkdir(parents=True, exist_ok=True)
        row = compare_case(label, catalog, meta, provenance, held_out, case_dir)
        (case_dir / "v1.musicxml").write_text(row["musicxml"]["v1"], encoding="utf-8")
        (case_dir / "v2.musicxml").write_text(row["musicxml"]["v2"], encoding="utf-8")
        if render and label in RENDER_LABELS:
            renders.append(_write_render(case_dir, label, row["musicxml"]["v1"], "v1"))
            renders.append(_write_render(case_dir, label, row["musicxml"]["v2"], "v2"))
        row.pop("musicxml")
        cases.append(row)
    corpus = []
    corpus_dir = out_dir / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    specs = {spec.case_id: spec for spec in all_cases()}
    for case_id in CORPUS_FOCUS:
        corpus.append(_corpus_row(specs[case_id], corpus_dir / case_id))
    report = {
        "inventory": inv,
        "cases": cases,
        "corpus": corpus,
        "renders": renders,
        "evidence_kind": "synthetic_midi",
        "real_audio_evidence": False,
        "mixed_chord_renderer_limitation": (
            "OSMD may union per-member articulations on a chord. MusicXML "
            "keeps ownership; compare_engraving now fails a swapped pair."
        ),
    }
    report["recommendation"] = recommend(report)
    (out_dir / "rollout_report.json").write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    (out_dir / "rollout_report.md").write_text(_markdown(report), encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out_dir", nargs="?", default=str(HERE / "readable_v2_rollout" / "out"))
    parser.add_argument(
        "--render",
        action="store_true",
        help="Also run production OSMD + frontend PDF export for representative cases",
    )
    args = parser.parse_args(argv)
    report = run(Path(args.out_dir), render=args.render)
    rec = report["recommendation"]
    print(f"wrote {args.out_dir}/rollout_report.md decision={rec['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
