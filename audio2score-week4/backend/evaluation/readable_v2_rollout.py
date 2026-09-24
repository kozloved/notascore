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
    measure_validity,
)
from evaluation.notation_fixtures import FIXTURE_META, FIXTURES
from evaluation.readable_v2_cases import (
    EXPECTED_NOTATION,
    HELDOUT_CASES,
    HELDOUT_META,
    READABLE_V2_CASES,
)
from mir.midi_ingest import ingest_midi
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
NOTA_SAMPLES = EVALUATION / "development" / "NotaTestSamples"

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
    ("grand_staff_pagination", HELDOUT_CASES, "readable_v2", HELDOUT_META["grand_staff_pagination"], "synthetic_heldout", True),
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
        "grand_staff_pagination",
        "unison_crossing",
        "short_rests_repeats",
        "irregular_triplet_intervals",
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


def _note_identity(note: dict) -> str:
    return str(note.get("source_note_id") or note.get("id") or "")


def _note_staff(note: dict) -> int:
    """Editor model staff is ``track`` (0=treble, 1=bass). ``hand`` is absent."""
    if note.get("track") is not None:
        return int(note["track"])
    return 0


def _assignments(result) -> dict:
    notes = list(result.editor_model.get("notes") or [])
    rows = []
    for note in notes:
        ident = _note_identity(note)
        rows.append(
            {
                "id": ident,
                "pitch": int(note["pitch"]),
                "start": round(float(note["start"]), 4),
                "duration": round(float(note["duration"]), 4),
                "staff": _note_staff(note),
                "voice": int(note.get("voice") or 0),
            }
        )
    return {
        "count": len(rows),
        "notes": rows,
        "source_ids": [row["id"] for row in rows],
        "starts": [row["start"] for row in rows],
        "durations": [row["duration"] for row in rows],
        "pitches": [row["pitch"] for row in rows],
        "staves": sorted({row["staff"] for row in rows}),
        "voices": sorted({row["voice"] for row in rows}),
    }


def _canonical_voice_groups(notes: list[dict]) -> dict[int, list[frozenset[str]]]:
    """Staff -> voice partitions, labels discarded.

    Matches existing voice metrics: a global voice-number permutation on one
    staff is the same grouping. A note moving staff or changing companions is not.
    """
    by_staff: dict[int, dict[int, list[str]]] = {}
    for note in notes:
        by_staff.setdefault(note["staff"], {}).setdefault(note["voice"], []).append(note["id"])
    groups: dict[int, list[frozenset[str]]] = {}
    for staff, voices in by_staff.items():
        ordered = sorted(
            (frozenset(members) for members in voices.values()),
            key=lambda members: tuple(sorted(members)),
        )
        groups[staff] = ordered
    return groups


def compare_staff_voice(left: dict, right: dict) -> dict:
    left_by = {row["id"]: row for row in left["notes"]}
    right_by = {row["id"]: row for row in right["notes"]}
    ids = sorted(set(left_by) | set(right_by))
    staff_changes = []
    voice_membership_changes = []
    for ident in ids:
        a = left_by.get(ident)
        b = right_by.get(ident)
        if a is None or b is None:
            staff_changes.append({"id": ident, "v1": None if a is None else a["staff"], "v2": None if b is None else b["staff"]})
            continue
        if a["staff"] != b["staff"]:
            staff_changes.append({"id": ident, "v1": a["staff"], "v2": b["staff"]})
        if a["voice"] != b["voice"] and a["staff"] == b["staff"]:
            # Label change only; grouping check decides if membership changed.
            pass
    left_groups = _canonical_voice_groups(left["notes"])
    right_groups = _canonical_voice_groups(right["notes"])
    grouping_equal = left_groups == right_groups
    if not grouping_equal:
        for staff in sorted(set(left_groups) | set(right_groups)):
            if left_groups.get(staff) != right_groups.get(staff):
                voice_membership_changes.append(
                    {
                        "staff": staff,
                        "v1": [sorted(group) for group in left_groups.get(staff, [])],
                        "v2": [sorted(group) for group in right_groups.get(staff, [])],
                    }
                )
    staff_equal = not staff_changes
    return {
        "staff_equal": staff_equal,
        "grouping_equal": grouping_equal,
        "assignments_unchanged": staff_equal and grouping_equal,
        "staff_changes": staff_changes,
        "voice_membership_changes": voice_membership_changes,
        "v1_staves": left["staves"],
        "v2_staves": right["staves"],
        "v1_voice_labels": left["voices"],
        "v2_voice_labels": right["voices"],
        "equal": staff_equal and grouping_equal,
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
    left_by = {row["id"]: row for row in left["notes"]}
    right_by = {row["id"]: row for row in right["notes"]}
    ids = sorted(set(left_by) | set(right_by))
    duration_changes = []
    start_changes = []
    for ident in ids:
        a = left_by.get(ident)
        b = right_by.get(ident)
        if a is None or b is None or a["duration"] != b["duration"]:
            duration_changes.append(
                {
                    "id": ident,
                    "pitch": (a or b or {}).get("pitch"),
                    "v1": None if a is None else a["duration"],
                    "v2": None if b is None else b["duration"],
                }
            )
        if a is None or b is None or a["start"] != b["start"]:
            start_changes.append(
                {
                    "id": ident,
                    "pitch": (a or b or {}).get("pitch"),
                    "v1": None if a is None else a["start"],
                    "v2": None if b is None else b["start"],
                }
            )
    return {
        "starts_equal": not start_changes,
        "durations_equal": not duration_changes,
        "pitches_equal": left["pitches"] == right["pitches"],
        "source_ids_equal": left["source_ids"] == right["source_ids"],
        "matched_by": "source_note_id_or_editor_id",
        "duration_changes": duration_changes,
        "start_changes": start_changes,
    }


def _nota_sample_pairs() -> list[dict]:
    """Local development raw/quantized MIDI pairs. Not licensed commercial recordings."""
    rows = []
    if not NOTA_SAMPLES.exists():
        return rows
    for raw in sorted(NOTA_SAMPLES.rglob("*_raw.mid")):
        quantized = raw.with_name(raw.name.replace("_raw.mid", "_q.mid"))
        audio = raw.with_name(raw.name.replace("_raw.mid", "_audio.wav"))
        rows.append(
            {
                "id": raw.stem.replace("_raw", ""),
                "kind": "local_reference_midi",
                "source": "evaluation/development/NotaTestSamples",
                "performance": "development_raw_quantized_pair",
                "held_out_of_last_note_tune": True,
                "raw_midi": str(raw.relative_to(BACKEND)),
                "quantized_midi": str(quantized.relative_to(BACKEND)) if quantized.exists() else None,
                "audio": str(audio.relative_to(BACKEND)) if audio.exists() else None,
                "license": "undocumented_in_repo",
                "musician_reviewed": False,
                "note": (
                    "Development raw/quantized pair with matching audio. "
                    "Not documented as a licensed commercial recording and not "
                    "musician-reviewed score ground truth. Used only as "
                    "performed-MIDI input to the shared planner."
                ),
            }
        )
    return rows


def _real_midi_available() -> dict:
    """Look for licensed/reference performances. Do not relabel synthetics."""
    samples = _nota_sample_pairs()
    realworld = []
    if REALWORLD_LOCAL.exists():
        realworld = [
            str(path.relative_to(BACKEND))
            for path in REALWORLD_LOCAL.rglob("*")
            if path.is_file() and path.suffix.lower() in {".wav", ".mp3", ".flac", ".mid", ".midi"}
        ]
    licensed = False
    gap_parts = []
    if not licensed:
        gap_parts.append(
            "No documented licensed commercial recordings or paired-corpus "
            "performances are present."
        )
    if samples:
        gap_parts.append(
            f"{len(samples)} local NotaTestSamples raw/quantized pairs are available "
            "and are labeled development reference MIDI, not licensed performances."
        )
    else:
        gap_parts.append(
            "Committed fixtures and benchmark.fixtures.catalog are synthetic_midi."
        )
    if not realworld:
        gap_parts.append("benchmark/realworld/local has no extra audio/MIDI.")
    return {
        "nota_test_samples": samples,
        "realworld_local": realworld,
        "paired_corpus_populated": False,
        "licensed_performances_available": False,
        "local_reference_midi_available": bool(samples),
        "real_performances_available": False,
        "gap": " ".join(gap_parts),
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
        "local_reference_midi": real["nota_test_samples"],
        "corpus": corpus,
        "note": (
            "Catalog and fixture MIDI is generated. Local NotaTestSamples are "
            "development raw/quantized pairs with undocumented license; they are "
            "not musician-reviewed ground truth. Do not claim real-performance "
            "accuracy from synthetic fixtures. Real-audio transcription is a "
            "separate evaluation."
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
    staff_voice = compare_staff_voice(assign1, assign2)
    valid1 = measure_validity(v1.musicxml)
    valid2 = measure_validity(v2.musicxml)
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
            "time_signatures": {
                "v1": surface1["time_signatures"],
                "v2": surface2["time_signatures"],
            },
            "measure_count": {
                "v1": surface1["measure_count"],
                "v2": surface2["measure_count"],
            },
            "structural_similar": surface1["time_signatures"] == surface2["time_signatures"]
            and surface1["measure_count"] == surface2["measure_count"],
            "v1_musical_valid": valid1["musical_valid"],
            "v2_musical_valid": valid2["musical_valid"],
            "v1": valid1,
            "v2": valid2,
            "equal": surface1["time_signatures"] == surface2["time_signatures"]
            and surface1["measure_count"] == surface2["measure_count"]
            and valid1["musical_valid"]
            and valid2["musical_valid"],
        },
        "hand_voice": staff_voice,
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
        "gap_fill": _gap_fill_analysis(assign1, assign2),
    }


def _gap_fill_analysis(left: dict, right: dict) -> list[dict]:
    """Explain per-note leftover vs the relative fill rule."""
    left_by = {row["id"]: row for row in left["notes"]}
    rows = []
    ordered = sorted(left["notes"], key=lambda row: (row["staff"], row["start"], row["pitch"], row["id"]))
    for index, note in enumerate(ordered):
        later = [
            other
            for other in ordered[index + 1 :]
            if other["staff"] == note["staff"]
        ]
        next_start = later[0]["start"] if later else None
        raw = note["duration"]
        if next_start is not None:
            slot = next_start - note["start"]
        else:
            slot = None
        remaining = None if slot is None else round(slot - raw, 4)
        v2 = left_by and {row["id"]: row for row in right["notes"]}.get(note["id"])
        rows.append(
            {
                "id": note["id"],
                "pitch": note["pitch"],
                "staff": note["staff"],
                "v1": raw,
                "v2": None if v2 is None else v2["duration"],
                "next_start": next_start,
                "remaining_to_next": remaining,
                "remaining_ratio": None if not slot else round(remaining / slot, 4),
                "filled": False if v2 is None else v2["duration"] > raw + 1e-6,
                "why": (
                    "v2 wrote a longer value through the leftover to the next attack or bar"
                    if v2 is not None and v2["duration"] > raw + 1e-6
                    else (
                        "kept written duration; leftover/slot >= 0.20 is not enough intent to fill"
                        if remaining is not None and slot and 0 <= remaining < 0.25 and remaining / slot >= 0.20
                        else (
                            "kept written duration; leftover smaller than a sixteenth is not enough intent"
                            if remaining is not None and 0 <= remaining < 0.25
                            else "no small leftover to next attack"
                        )
                    )
                ),
            }
        )
    return rows


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


def compare_midi_path(path: Path, *, label: str, provenance: dict) -> dict:
    ingested_probe = ingest_midi(path)
    meter = ingested_probe.time_sig_hint or "4/4"
    points = list(getattr(ingested_probe.tempo_map, "points", None) or [])
    tempo = float(points[0].bpm) if points else 120.0
    compared = _compare_pair(path, meter=meter, tempo=tempo)
    return {
        "label": label,
        "fixture": label,
        "family": "local_reference_midi",
        "provenance": provenance,
        "expected_meter": meter,
        "musicxml": {
            "v1": compared["v1"].pop("musicxml"),
            "v2": compared["v2"].pop("musicxml"),
        },
        **compared,
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
    for row in report["cases"] + report.get("reference_midi", []):
        if row.get("identical_written"):
            continue
        label = row["label"]
        expected = (row.get("expected") or {}).get("release") or ""
        durations_changed = not row["timing"]["durations_equal"]
        if label == "final_short_then_silence" and durations_changed:
            last_v1 = (row["v1"]["assignments"]["notes"] or [{}])[-1]
            last_v2 = (row["v2"]["assignments"]["notes"] or [{}])[-1]
            if last_v1.get("id") == last_v2.get("id") and last_v2.get("duration", 0) > last_v1.get("duration", 0) + 0.05:
                remaining.append(
                    {
                        "case": label,
                        "issue": "v2 lengthens the intentional final short note",
                        "id": last_v1.get("id"),
                        "v1_last": last_v1.get("duration"),
                        "v2_last": last_v2.get("duration"),
                    }
                )
        if label == "near_barline_short_release" and durations_changed:
            last_v2 = (row["v2"]["assignments"]["notes"] or [{}])[-1]
            if last_v2.get("duration") is not None and last_v2["duration"] >= 0.24:
                remaining.append(
                    {
                        "case": label,
                        "issue": "v2 fills a short near-barline note to the bar",
                        "id": last_v2.get("id"),
                        "v2_last": last_v2.get("duration"),
                    }
                )
        if label == "irregular_triplet_intervals" and durations_changed:
            invented = any(
                change.get("v2") is not None and abs(float(change["v2"]) - (1 / 3)) < 1e-3
                for change in row["timing"]["duration_changes"]
            )
            remaining.append(
                {
                    "case": label,
                    "issue": (
                        "v2 invented regular triplet eighths (1/3) on irregular attacks"
                        if invented
                        else (
                            "v2 filled leftover < sixteenth to the next attack "
                            "(0.25→0.375), not a 1/3 tuplet. Ambiguous silence; "
                            "not used to retune."
                        )
                    ),
                    "duration_changes": row["timing"]["duration_changes"],
                }
            )
        if label == "short_rests_repeats" and row["rest_count"]["delta"] < 0:
            remaining.append(
                {
                    "case": label,
                    "issue": (
                        f"v2 rest count {row['rest_count']['v1']}→{row['rest_count']['v2']}. "
                        "Fewer rests are not automatically better; musician review needed."
                    ),
                }
            )
        if not row.get("hand_voice", {}).get("assignments_unchanged", True):
            remaining.append(
                {
                    "case": label,
                    "issue": (
                        "v2 changed per-note staff or voice grouping. "
                        "Voice-number permutation alone is not this signal."
                    ),
                    "staff_changes": row["hand_voice"].get("staff_changes"),
                    "voice_membership_changes": row["hand_voice"].get("voice_membership_changes"),
                }
            )
        if label == "independent_voices_mixed_release":
            bass_v1 = next(
                (n["duration"] for n in row["v1"]["assignments"]["notes"] if n["pitch"] == 48),
                None,
            )
            bass_v2 = next(
                (n["duration"] for n in row["v2"]["assignments"]["notes"] if n["pitch"] == 48),
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
    for render in report.get("renders") or []:
        if render["label"] != "grand_staff_pagination":
            continue
        pages = render.get("pdf", {}).get("parsed_pages") or 0
        if pages < 2:
            remaining.append(
                {
                    "case": "grand_staff_pagination",
                    "issue": (
                        f"Expected at least two real PDF pages, parsed {pages}. "
                        "Whole-score shrinking or missing systems would be a defect."
                    ),
                }
            )
            break
    default_is_v1 = (
        report["inventory"]["default_algorithm_version"] == ALGORITHM_VERSION_CURRENT
    )
    licensed = bool(
        report["inventory"].get("real_material", {}).get("licensed_performances_available")
    )
    # Synthetic cleanliness is not enough to change the default. Keep v2
    # opt-in; development MIDI is not musician-reviewed ground truth.
    if remaining or not default_is_v1 or not licensed:
        decision = "continued_opt_in"
        rationale = (
            "Keep performance-score-2 opt-in. Remaining regressions are listed "
            "below when present. Synthetic fixtures and undocumented "
            "development MIDI are not enough to migrate existing jobs or "
            "change the default."
        )
    else:
        decision = "controlled_new_job_default"
        rationale = (
            "Held-out comparison is clean and licensed reference material is "
            "available. A reversible versioned setting could default new jobs "
            "to performance-score-2. Existing jobs stay on performance-score-1."
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
        f"- Licensed performances available: `{report['inventory']['real_material']['licensed_performances_available']}`",
        f"- Local reference MIDI available: `{report['inventory']['real_material']['local_reference_midi_available']}`",
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
            "| Case | Held-out | MIDI preserved | Written identical | Rests v1→v2 | Ties v1→v2 | Structural | Musical valid | Staff/voice |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for row in report["cases"] + report.get("reference_midi", []) + report["corpus"]:
        integrity = row["measure_integrity"]
        lines.append(
            "| `{label}` | {held} | {midi} | {ident} | {r1}→{r2} | {t1}→{t2} | {struct} | {valid} | {hv} |".format(
                label=row["label"],
                held="yes" if row.get("provenance", {}).get("held_out_of_last_note_tune") else "no",
                midi="yes" if row.get("source_midi_unchanged") else "NO",
                ident="yes" if row.get("identical_written") else "no",
                r1=row["rest_count"]["v1"],
                r2=row["rest_count"]["v2"],
                t1=row["tie_count"]["v1"],
                t2=row["tie_count"]["v2"],
                struct="similar" if integrity.get("structural_similar") else "DIFF",
                valid=(
                    "ok"
                    if integrity.get("v1_musical_valid") and integrity.get("v2_musical_valid")
                    else "INVALID"
                ),
                hv="ok" if row["hand_voice"].get("assignments_unchanged", row["hand_voice"].get("equal")) else "DIFF",
            )
        )
    lines.extend(["", "## Duration changes (not an automatic improvement)", ""])
    for row in report["cases"] + report.get("reference_midi", []):
        changes = row["timing"]["duration_changes"]
        if not changes:
            continue
        lines.append(f"### `{row['label']}`")
        if row.get("expected"):
            lines.append(f"- Expected release: {row['expected']['release']}")
        for change in changes[:12]:
            ident = change.get("id") or change.get("index")
            lines.append(
                f"- id `{ident}` pitch {change['pitch']}: "
                f"v1={change['v1']} v2={change['v2']}"
            )
        lines.append("")
    if report.get("renders"):
        lines.extend(
            [
                "## Pagination",
                "",
                "Bar count alone is not a pagination defect. "
                "`grand_staff_pagination` is the representative score that must "
                "exceed usable page height at normal staff size and produce at "
                "least two real PDF pages without shrinking the whole score.",
                "",
            ]
        )
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
    reference = []
    for sample in inv["real_material"]["nota_test_samples"]:
        raw = BACKEND / sample["raw_midi"]
        ref_dir = out_dir / "reference" / sample["id"]
        ref_dir.mkdir(parents=True, exist_ok=True)
        row = compare_midi_path(
            raw,
            label=sample["id"],
            provenance={
                "kind": sample["kind"],
                "source": sample["source"],
                "performance": sample["performance"],
                "held_out_of_last_note_tune": True,
                "license": sample["license"],
                "musician_reviewed": False,
            },
        )
        (ref_dir / "v1.musicxml").write_text(row["musicxml"]["v1"], encoding="utf-8")
        (ref_dir / "v2.musicxml").write_text(row["musicxml"]["v2"], encoding="utf-8")
        if render:
            renders.append(_write_render(ref_dir, sample["id"], row["musicxml"]["v1"], "v1"))
            renders.append(_write_render(ref_dir, sample["id"], row["musicxml"]["v2"], "v2"))
        row.pop("musicxml")
        reference.append(row)
    report = {
        "inventory": inv,
        "cases": cases,
        "corpus": corpus,
        "reference_midi": reference,
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
