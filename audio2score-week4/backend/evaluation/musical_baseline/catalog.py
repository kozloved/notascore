"""P1 reviewed musical baseline: inventory, candidate set, and split rules.

Does not invent licenses, musician reviews, or quality scores. Synthetic
fixtures are eligible for interpretation / export / correction-effort review
packages; acoustic accuracy requires suitable audio and documented labels.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from benchmark.fixtures.catalog import all_cases as catalog_all_cases
from benchmark.fixtures.generate import write_midi as write_catalog_midi
from evaluation.notation_fixtures import FIXTURE_META, FIXTURES
from evaluation.readable_v2_cases import (
    EXPECTED_NOTATION,
    HELDOUT_CASES,
    HELDOUT_META,
    READABLE_V2_CASES,
)
from evaluation.readable_v2_rollout import TUNING_SET, _nota_sample_pairs
from mir.notation_settings import NotationSettings

HERE = Path(__file__).resolve().parent
EVALUATION = HERE.parent
BACKEND = EVALUATION.parent
PAIRED = EVALUATION / "paired_corpus"
REALWORLD_LOCAL = BACKEND / "benchmark" / "realworld" / "local"
HUMAN_REVIEWED = EVALUATION / "human_reviewed"
PRODUCTION_SMOKE = EVALUATION / "production_smoke"

Split = Literal["development", "held_out"]
SourceKind = Literal[
    "readable_v2",
    "notation_fixture",
    "readable_v2_heldout",
    "benchmark_catalog",
    "nota_test_sample",
]

REVIEW_DIMENSIONS = (
    "acoustic_accuracy",
    "musical_interpretation_accuracy",
    "export_integrity",
    "human_correction_effort",
)

REQUIRED_FAMILIES = (
    "solo_line",
    "piano_accompaniment",
    "independent_voices",
    "pedal_repeated_notes",
    "intentional_rests",
    "detached_articulation",
    "triplets",
    "syncopation",
    "pickup",
    "meter_3_4",
    "meter_6_8",
)


@dataclass(frozen=True)
class CandidateExample:
    """One short example in the P1 candidate set."""

    example_id: str
    composition_id: str
    performance_id: str
    split: Split
    source_kind: SourceKind
    source_id: str
    instrument: str
    families: tuple[str, ...]
    meter: str
    tempo: float
    title: str
    # Synthetic fixtures are repo-safe; real samples need documented license.
    permitted_use: str
    copyrighted: bool | None
    musician_reviewed: bool
    # Eligible for packaging into the review set (not the same as reviewed).
    package_eligible: bool
    acoustic_labels_available: bool
    reference_score_available: bool
    audio_available: bool
    notes: str = ""
    expected_notation: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WriterSpec:
    write: Callable[[Path], Any]
    meter: str
    tempo: float


def _writer_for(candidate: CandidateExample) -> WriterSpec:
    sid = candidate.source_id
    if candidate.source_kind == "readable_v2":
        return WriterSpec(READABLE_V2_CASES[sid], "4/4", 120.0)
    if candidate.source_kind == "readable_v2_heldout":
        meta = HELDOUT_META[sid]
        return WriterSpec(HELDOUT_CASES[sid], str(meta["meter"]), float(meta["tempo"]))
    if candidate.source_kind == "notation_fixture":
        meta = FIXTURE_META[sid]
        return WriterSpec(FIXTURES[sid], str(meta["meter"]), float(meta["tempo"]))
    if candidate.source_kind == "benchmark_catalog":
        specs = {spec.case_id: spec for spec in catalog_all_cases()}
        spec = specs[sid]

        def _write(path: Path) -> None:
            write_catalog_midi(spec, path)

        return WriterSpec(_write, spec.time_signature, float(spec.tempo_bpm))
    if candidate.source_kind == "nota_test_sample":
        raise ValueError(
            f"{candidate.example_id} is a local sample path, not a MIDI writer"
        )
    raise ValueError(f"unknown source_kind {candidate.source_kind!r}")


def resolve_midi_writer(candidate: CandidateExample) -> WriterSpec:
    return _writer_for(candidate)


# ---------------------------------------------------------------------------
# Candidate set (15 examples). Compositions are disjoint across splits.
# Tuning-set cases stay in development only.
# ---------------------------------------------------------------------------

CANDIDATES: tuple[CandidateExample, ...] = (
    # --- development ---
    CandidateExample(
        example_id="dev-solo-detached",
        composition_id="p1-comp-detached-line",
        performance_id="p1-perf-detached-line-synth",
        split="development",
        source_kind="readable_v2",
        source_id="A_detached_regular_line",
        instrument="piano",
        families=("solo_line", "detached_articulation"),
        meter="4/4",
        tempo=120.0,
        title="Detached regular solo line",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        notes="Synthetic. Acoustic accuracy not applicable.",
        expected_notation=EXPECTED_NOTATION.get("A_detached_regular_line"),
    ),
    CandidateExample(
        example_id="dev-intentional-rests",
        composition_id="p1-comp-short-rests",
        performance_id="p1-perf-short-rests-synth",
        split="development",
        source_kind="readable_v2",
        source_id="B_short_notes_with_rests",
        instrument="piano",
        families=("intentional_rests", "solo_line"),
        meter="4/4",
        tempo=120.0,
        title="Short notes with intentional rests",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        expected_notation=EXPECTED_NOTATION.get("B_short_notes_with_rests"),
    ),
    CandidateExample(
        example_id="dev-melody-bass",
        composition_id="p1-comp-melody-over-bass",
        performance_id="p1-perf-melody-over-bass-synth",
        split="development",
        source_kind="notation_fixture",
        source_id="melody_over_bass",
        instrument="piano",
        families=("piano_accompaniment", "pedal_repeated_notes"),
        meter="4/4",
        tempo=120.0,
        title="Melody over bass with pedal",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
    ),
    CandidateExample(
        example_id="dev-pedal-repeats",
        composition_id="p1-comp-pedal-repeats",
        performance_id="p1-perf-pedal-repeats-synth",
        split="development",
        source_kind="readable_v2",
        source_id="C_repeated_attacks_under_pedal",
        instrument="piano",
        families=("pedal_repeated_notes",),
        meter="4/4",
        tempo=120.0,
        title="Repeated attacks under sustain pedal",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        expected_notation=EXPECTED_NOTATION.get("C_repeated_attacks_under_pedal"),
    ),
    CandidateExample(
        example_id="dev-independent-voices",
        composition_id="p1-comp-held-voice-same-staff",
        performance_id="p1-perf-held-voice-same-staff-synth",
        split="development",
        source_kind="readable_v2",
        source_id="G_held_voice_same_staff",
        instrument="piano",
        families=("independent_voices",),
        meter="4/4",
        tempo=120.0,
        title="Held voice under moving notes (same staff)",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        expected_notation=EXPECTED_NOTATION.get("G_held_voice_same_staff"),
    ),
    CandidateExample(
        example_id="dev-detached-triplets",
        composition_id="p1-comp-detached-triplets",
        performance_id="p1-perf-detached-triplets-synth",
        split="development",
        source_kind="readable_v2",
        source_id="I_detached_triplet_groups",
        instrument="piano",
        families=("triplets", "detached_articulation"),
        meter="4/4",
        tempo=120.0,
        title="Detached triplet groups (last-note-tune development)",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        notes="TUNING_SET member; must remain development-only.",
        expected_notation=EXPECTED_NOTATION.get("I_detached_triplet_groups"),
    ),
    CandidateExample(
        example_id="dev-syncopation",
        composition_id="p1-comp-syncopation",
        performance_id="p1-perf-syncopation-synth",
        split="development",
        source_kind="notation_fixture",
        source_id="syncopation",
        instrument="piano",
        families=("syncopation",),
        meter="4/4",
        tempo=120.0,
        title="Off-beat syncopation with barline sustain",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
    ),
    CandidateExample(
        example_id="dev-pickup",
        composition_id="p1-comp-rubato-pickup",
        performance_id="p1-perf-rubato-pickup-synth",
        split="development",
        source_kind="notation_fixture",
        source_id="rubato_pickup",
        instrument="piano",
        families=("pickup",),
        meter="4/4",
        tempo=120.0,
        title="Pickup eighth with rubato tempo map",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
    ),
    CandidateExample(
        example_id="dev-meter-3-4",
        composition_id="p1-comp-meter-3-4",
        performance_id="p1-perf-meter-3-4-synth",
        split="development",
        source_kind="notation_fixture",
        source_id="meter_3_4",
        instrument="piano",
        families=("meter_3_4", "solo_line"),
        meter="3/4",
        tempo=120.0,
        title="Simple 3/4 line",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
    ),
    # --- held-out (disjoint compositions; no TUNING_SET members) ---
    CandidateExample(
        example_id="hold-repeats-no-pedal",
        composition_id="p1-comp-repeats-no-pedal",
        performance_id="p1-perf-repeats-no-pedal-synth",
        split="held_out",
        source_kind="readable_v2",
        source_id="E_repeated_attacks_no_pedal",
        instrument="piano",
        families=("pedal_repeated_notes",),
        meter="4/4",
        tempo=120.0,
        title="Repeated attacks without pedal",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        expected_notation=EXPECTED_NOTATION.get("E_repeated_attacks_no_pedal"),
    ),
    CandidateExample(
        example_id="hold-independent-mixed",
        composition_id="p1-comp-independent-mixed-release",
        performance_id="p1-perf-independent-mixed-release-synth",
        split="held_out",
        source_kind="readable_v2_heldout",
        source_id="independent_voices_mixed_release",
        instrument="piano",
        families=("independent_voices", "intentional_rests"),
        meter="4/4",
        tempo=120.0,
        title="Independent voices with mixed releases",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        expected_notation=EXPECTED_NOTATION.get("independent_voices_mixed_release"),
    ),
    CandidateExample(
        example_id="hold-meter-6-8",
        composition_id="p1-comp-meter-6-8",
        performance_id="p1-perf-meter-6-8-synth",
        split="held_out",
        source_kind="notation_fixture",
        source_id="meter_6_8",
        instrument="piano",
        families=("meter_6_8",),
        meter="6/8",
        tempo=90.0,
        title="Compound 6/8 pulse",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
    ),
    CandidateExample(
        example_id="hold-final-short",
        composition_id="p1-comp-final-short-silence",
        performance_id="p1-perf-final-short-silence-synth",
        split="held_out",
        source_kind="readable_v2_heldout",
        source_id="final_short_then_silence",
        instrument="piano",
        families=("intentional_rests", "solo_line"),
        meter="4/4",
        tempo=120.0,
        title="Final short note then silence",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        expected_notation=EXPECTED_NOTATION.get("final_short_then_silence"),
    ),
    CandidateExample(
        example_id="hold-catalog-triplets",
        composition_id="p1-comp-catalog-triplets",
        performance_id="p1-perf-catalog-triplets-synth",
        split="held_out",
        source_kind="benchmark_catalog",
        source_id="triplets",
        instrument="piano",
        families=("triplets",),
        meter="4/4",
        tempo=120.0,
        title="Catalog eighth-note triplets",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        notes="Held-out of last-note-tune; not a TUNING_SET member.",
    ),
    CandidateExample(
        example_id="hold-catalog-melody-bass",
        composition_id="p1-comp-catalog-melody-bass",
        performance_id="p1-perf-catalog-melody-bass-synth",
        split="held_out",
        source_kind="benchmark_catalog",
        source_id="melody_and_bass",
        instrument="piano",
        families=("piano_accompaniment",),
        meter="4/4",
        tempo=120.0,
        title="Catalog RH melody over LH bass",
        permitted_use="synthetic_repo_fixture",
        copyrighted=False,
        musician_reviewed=False,
        package_eligible=True,
        acoustic_labels_available=False,
        reference_score_available=False,
        audio_available=False,
        notes="Disjoint from development melody_over_bass composition.",
    ),
)


def candidates(*, split: Split | None = None, eligible_only: bool = False) -> list[CandidateExample]:
    rows = list(CANDIDATES)
    if split is not None:
        rows = [c for c in rows if c.split == split]
    if eligible_only:
        rows = [c for c in rows if c.package_eligible]
    return rows


def composition_split_map(examples: list[CandidateExample] | None = None) -> dict[str, set[str]]:
    rows = examples if examples is not None else list(CANDIDATES)
    by_comp: dict[str, set[str]] = {}
    for row in rows:
        by_comp.setdefault(row.composition_id, set()).add(row.split)
    return by_comp


def split_leakage(examples: list[CandidateExample] | None = None) -> list[str]:
    """Compositions must not appear in both development and held_out."""
    warnings: list[str] = []
    for composition_id, splits in sorted(composition_split_map(examples).items()):
        if "development" in splits and "held_out" in splits:
            warnings.append(
                f"composition {composition_id} appears in both development and held_out"
            )
    for row in examples if examples is not None else CANDIDATES:
        if row.split == "held_out" and row.source_id in TUNING_SET:
            warnings.append(
                f"TUNING_SET case {row.source_id} must not be held_out "
                f"(example {row.example_id})"
            )
    return warnings


def family_coverage(examples: list[CandidateExample] | None = None) -> dict[str, Any]:
    rows = examples if examples is not None else [c for c in CANDIDATES if c.package_eligible]
    covered: dict[str, list[str]] = {name: [] for name in REQUIRED_FAMILIES}
    for row in rows:
        for family in row.families:
            if family in covered:
                covered[family].append(row.example_id)
    missing = [name for name, ids in covered.items() if not ids]
    return {
        "required_families": list(REQUIRED_FAMILIES),
        "covered": covered,
        "missing_families": missing,
        "complete": not missing,
    }


def empty_dimension(name: str, *, status: str, reason: str) -> dict[str, Any]:
    return {
        "dimension": name,
        "status": status,
        "reason": reason,
        "score": None,
        "reviewer": None,
        "reviewed_at": None,
        "notes": "",
    }


def dimension_status_for(candidate: CandidateExample) -> dict[str, dict[str, Any]]:
    """Four tracks, kept separate. Never invent a quality score."""
    dims: dict[str, dict[str, Any]] = {}
    if candidate.acoustic_labels_available and candidate.audio_available:
        dims["acoustic_accuracy"] = empty_dimension(
            "acoustic_accuracy",
            status="unreviewed",
            reason="Audio/reference present; musician acoustic rating still required",
        )
    elif candidate.audio_available and not candidate.acoustic_labels_available:
        dims["acoustic_accuracy"] = empty_dimension(
            "acoustic_accuracy",
            status="blocked",
            reason="Audio present but acoustic labels / permitted-use documentation missing",
        )
    else:
        dims["acoustic_accuracy"] = empty_dimension(
            "acoustic_accuracy",
            status="not_applicable",
            reason="No suitable audio/reference labels for acoustic accuracy",
        )
    dims["musical_interpretation_accuracy"] = empty_dimension(
        "musical_interpretation_accuracy",
        status="unreviewed",
        reason="Musician interpretation rating required; export success is not a substitute",
    )
    dims["export_integrity"] = empty_dimension(
        "export_integrity",
        status="automated_pending",
        reason="Filled by package generation (mechanical MusicXML/MIDI integrity)",
    )
    dims["human_correction_effort"] = empty_dimension(
        "human_correction_effort",
        status="unreviewed",
        reason="Musician correction-effort estimate required",
    )
    return dims


def _dir_empty_or_placeholder(path: Path) -> bool:
    if not path.is_dir():
        return True
    children = [p for p in path.iterdir() if not p.name.startswith(".")]
    return not any(p.is_dir() or (p.is_file() and p.suffix in {".wav", ".mid", ".musicxml", ".yaml"}) for p in children)


def asset_inventory() -> dict[str, Any]:
    """Honest inventory of evaluation/benchmark assets. Gaps stay gaps."""
    samples = _nota_sample_pairs()
    for row in samples:
        row["composition_id"] = "not_documented"
        row["instrument"] = "piano_from_filename_only"
        row["reference_score"] = "missing"
        row["labels"] = {
            dim: "missing" for dim in REVIEW_DIMENSIONS
        }
        row["review_status"] = "not_musician_reviewed"
        row["permitted_use"] = row.get("license") or "undocumented_in_repo"

    synthetic_fixtures = []
    for name, meta in FIXTURE_META.items():
        synthetic_fixtures.append(
            {
                "id": name,
                "location": "evaluation.notation_fixtures",
                "kind": "synthetic_midi",
                "instrument": "piano",
                "audio": "missing",
                "midi": "generated_on_demand",
                "reference_score": "missing",
                "provenance": "evaluation.notation_fixtures",
                "permitted_use": "synthetic_repo_fixture",
                "copyrighted": False,
                "labels": {dim: "missing" for dim in REVIEW_DIMENSIONS},
                "review_status": "not_musician_reviewed",
                "meter": meta["meter"],
                "tempo": meta["tempo"],
            }
        )

    readable = []
    for name in READABLE_V2_CASES:
        readable.append(
            {
                "id": name,
                "location": "evaluation.readable_v2_cases",
                "kind": "synthetic_midi",
                "instrument": "piano",
                "audio": "missing",
                "midi": "generated_on_demand",
                "reference_score": "missing",
                "provenance": "evaluation.readable_v2_cases",
                "permitted_use": "synthetic_repo_fixture",
                "copyrighted": False,
                "labels": {dim: "missing" for dim in REVIEW_DIMENSIONS},
                "review_status": "not_musician_reviewed",
                "tuning_set": name in TUNING_SET,
            }
        )

    heldout = []
    for name, meta in HELDOUT_META.items():
        heldout.append(
            {
                "id": name,
                "location": "evaluation.readable_v2_cases.HELDOUT_CASES",
                "kind": "synthetic_midi",
                "instrument": "piano",
                "audio": "missing",
                "midi": "generated_on_demand",
                "reference_score": "missing",
                "provenance": "synthetic_heldout_of_last_note_tune",
                "permitted_use": "synthetic_repo_fixture",
                "copyrighted": False,
                "labels": {dim: "missing" for dim in REVIEW_DIMENSIONS},
                "review_status": "not_musician_reviewed",
                "meter": meta["meter"],
                "tempo": meta["tempo"],
            }
        )

    corpus = []
    for spec in catalog_all_cases():
        corpus.append(
            {
                "id": spec.case_id,
                "location": f"benchmark/corpus/{spec.category}/{spec.case_id}/",
                "kind": "synthetic_midi",
                "instrument": "piano",
                "audio": "missing_unless_generated",
                "midi": "input.mid+reference.mid",
                "reference_score": "reference.json_only",
                "provenance": "benchmark.fixtures.catalog",
                "permitted_use": "synthetic_repo_fixture",
                "copyrighted": False,
                "labels": {dim: "missing" for dim in REVIEW_DIMENSIONS},
                "review_status": "not_musician_reviewed",
                "category": spec.category,
                "meter": spec.time_signature,
                "tempo": spec.tempo_bpm,
            }
        )

    gaps = [
        {
            "id": "paired_corpus_recordings",
            "location": str(PAIRED.relative_to(BACKEND)),
            "status": "missing",
            "detail": "Slot templates exist; complete_slots=0; no audio/MIDI/score.",
        },
        {
            "id": "evaluation_holdout_cases",
            "location": "evaluation/holdout",
            "status": "missing",
            "detail": "Directory present; no case assets committed.",
        },
        {
            "id": "evaluation_real_world_cases",
            "location": "evaluation/real_world",
            "status": "missing",
            "detail": "Directory present; no case assets committed.",
        },
        {
            "id": "benchmark_realworld_local",
            "location": str(REALWORLD_LOCAL.relative_to(BACKEND)),
            "status": "missing" if _dir_empty_or_placeholder(REALWORLD_LOCAL) else "present_local",
            "detail": "Ad-hoc local audio slot; empty or gitignored.",
        },
        {
            "id": "human_reviewed_ratings",
            "location": str(HUMAN_REVIEWED.relative_to(BACKEND)),
            "status": "missing",
            "detail": "Generators and rubric exist; no attributed musician ratings.",
        },
        {
            "id": "production_smoke_audio",
            "location": str(PRODUCTION_SMOKE.relative_to(BACKEND)),
            "status": "missing",
            "detail": "cases.json names expected WAVs; audio not committed.",
        },
        {
            "id": "nota_test_sample_licenses",
            "location": "evaluation/development/NotaTestSamples",
            "status": "undocumented",
            "detail": (
                f"{len(samples)} local raw/quantized/audio pairs present; "
                "license and composition identity not documented; not musician-reviewed."
            ),
        },
        {
            "id": "acoustic_accuracy_labels",
            "location": "n/a",
            "status": "missing",
            "detail": "No reviewed acoustic-accuracy labels on any asset.",
        },
        {
            "id": "correction_effort_labels",
            "location": "n/a",
            "status": "missing",
            "detail": "No human correction-effort ratings on any asset.",
        },
    ]

    candidate_rows = [c.to_dict() for c in CANDIDATES]
    coverage = family_coverage()
    leaks = split_leakage()
    reviewed_count = sum(1 for c in CANDIDATES if c.musician_reviewed)
    eligible = [c for c in CANDIDATES if c.package_eligible]

    return {
        "baseline_sha_hint": "origin/main at generation time",
        "default_algorithm_version": NotationSettings().algorithm_version,
        "opt_in_algorithm_version": NotationSettings.readable_opt_in().algorithm_version,
        "evidence_rules": {
            "no_invented_licenses": True,
            "no_invented_reviews": True,
            "no_invented_quality_scores": True,
            "export_success_is_not_musical_quality": True,
            "printed_lanes_are_not_musical_voices": True,
        },
        "candidates": candidate_rows,
        "candidate_counts": {
            "total": len(CANDIDATES),
            "package_eligible": len(eligible),
            "development": len([c for c in CANDIDATES if c.split == "development"]),
            "held_out": len([c for c in CANDIDATES if c.split == "held_out"]),
            "musician_reviewed": reviewed_count,
        },
        "family_coverage": coverage,
        "split_leakage": leaks,
        "splits_disjoint": not leaks,
        "assets": {
            "nota_test_samples": samples,
            "notation_fixtures": synthetic_fixtures,
            "readable_v2_cases": readable,
            "readable_v2_heldout": heldout,
            "benchmark_catalog": corpus,
            "paired_corpus": {"complete_slots": 0, "location": str(PAIRED.relative_to(BACKEND))},
            "human_reviewed": {
                "location": str(HUMAN_REVIEWED.relative_to(BACKEND)),
                "attributed_reviews": 0,
            },
        },
        "gaps": gaps,
        "p1_complete": False,
        "p1_complete_reason": (
            "Candidate inventory and review package infrastructure exist, but "
            f"musician_reviewed={reviewed_count}. P1 acceptance requires attributed "
            "reviews; do not mark complete without them."
        ),
    }
