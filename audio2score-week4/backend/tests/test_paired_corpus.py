"""Paired-corpus schema, leakage, and inventory."""

from __future__ import annotations

from pathlib import Path

import pretty_midi

from evaluation.corpus import check_split_leakage, discover_cases
from evaluation.paired_corpus import INITIAL_SLOTS, paired_inventory
from evaluation.schema import parse_case_dir


def _write_midi(path: Path) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.4))
    midi.instruments.append(inst)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))


def test_paired_manifest_distinguishes_score_and_performed(tmp_path: Path):
    d = tmp_path / "development" / "piano_ornaments"
    d.mkdir(parents=True)
    (d / "case.yaml").write_text(
        "\n".join(
            [
                "id: piano_ornaments",
                "composition_id: work-orn",
                "performance_id: work-orn-take-1",
                "instrument: piano",
                "reference:",
                "  kind: performed",
                "  midi: reference.mid",
                "score:",
                "  musicxml: score.musicxml",
                "alignment:",
                "  repeats: []",
                "  ornaments: [grace]",
                "challenges: [ornaments, short_notes]",
                "provenance:",
                "  source: self-performed",
                "  permitted_use: evaluation only",
            ]
        ),
        encoding="utf-8",
    )
    (d / "input.wav").write_bytes(b"RIFF")
    _write_midi(d / "reference.mid")
    (d / "score.musicxml").write_text("<score-partwise/>", encoding="utf-8")
    spec = parse_case_dir(d, "development")
    assert spec.composition_id == "work-orn"
    assert spec.reference_kind == "performed"
    assert spec.score_musicxml and spec.score_musicxml.name == "score.musicxml"
    assert spec.alignment.get("ornaments") == ["grace"]
    assert "ornaments" in spec.challenges
    assert spec.inventory_gaps() == []


def test_composition_must_not_span_development_and_holdout(tmp_path: Path):
    for split in ("development", "holdout"):
        d = tmp_path / split / f"{split}_take"
        d.mkdir(parents=True)
        (d / "case.yaml").write_text(
            "id: x\ncomposition_id: shared-work\nperformance_id: "
            f"{split}-take\n",
            encoding="utf-8",
        )
        (d / "input.wav").write_bytes(b"RIFF")
        _write_midi(d / "reference.mid")
    warnings = check_split_leakage(discover_cases(root=tmp_path))
    assert any("composition" in w for w in warnings)


def test_inventory_reports_missing_inputs_without_claiming_quality(tmp_path: Path):
    payload = paired_inventory(root=tmp_path)
    assert payload["initial_target"] == 10
    assert payload["complete_slots"] == 0
    assert payload["quality_claims_allowed"] is False
    assert len(payload["slots"]) == len(INITIAL_SLOTS)
    assert all(slot["present"] is False for slot in payload["slots"])
    assert "performed_note_reference" in payload["slots"][0]["missing_inputs"]
