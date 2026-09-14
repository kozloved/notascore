"""Paired audio / score / performed-note corpus (10 now, 100 later)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from evaluation.corpus import PACKAGE_DIR, check_split_leakage, discover_cases
from evaluation.schema import CaseSpec

PAIRED_ROOT = Path(__file__).resolve().parent
INITIAL_TARGET = 10
EXPANDED_TARGET = 100

# Planned first ten recordings. Inputs are not invented here.
INITIAL_SLOTS: tuple[dict[str, Any], ...] = (
    {
        "slot": 1,
        "case_id": "piano_simple_meter",
        "composition_id": "tba-simple-piano",
        "instrument": "piano",
        "challenges": ["meter", "duration"],
        "reuse": "evaluation/human_reviewed + development fixtures",
    },
    {
        "slot": 2,
        "case_id": "piano_rubato",
        "composition_id": "tba-rubato",
        "instrument": "piano",
        "challenges": ["rubato", "expressive_timing"],
        "reuse": "evaluation/human_reviewed/rubato",
    },
    {
        "slot": 3,
        "case_id": "piano_ornaments",
        "composition_id": "tba-ornaments",
        "instrument": "piano",
        "challenges": ["ornaments", "short_notes"],
        "reuse": "evaluation/human_reviewed/ornaments",
    },
    {
        "slot": 4,
        "case_id": "piano_pedal",
        "composition_id": "tba-pedal",
        "instrument": "piano",
        "challenges": ["pedal", "written_vs_sounding"],
        "reuse": "evaluation/human_reviewed/pedal",
    },
    {
        "slot": 5,
        "case_id": "piano_repeated_notes",
        "composition_id": "tba-repeats",
        "instrument": "piano",
        "challenges": ["repeated_attacks"],
        "reuse": "evaluation/human_reviewed/repeated_notes",
    },
    {
        "slot": 6,
        "case_id": "piano_meter_changes",
        "composition_id": "tba-meter-changes",
        "instrument": "piano",
        "challenges": ["meter_changes"],
        "reuse": "evaluation/human_reviewed/meter_changes",
    },
    {
        "slot": 7,
        "case_id": "piano_high_register",
        "composition_id": "tba-high-piano",
        "instrument": "piano",
        "challenges": ["high_piano"],
        "reuse": None,
    },
    {
        "slot": 8,
        "case_id": "bass_low_register",
        "composition_id": "tba-bass",
        "instrument": "bass",
        "challenges": ["bass"],
        "reuse": None,
    },
    {
        "slot": 9,
        "case_id": "piano_quiet_passages",
        "composition_id": "tba-quiet",
        "instrument": "piano",
        "challenges": ["quiet_passages"],
        "reuse": None,
    },
    {
        "slot": 10,
        "case_id": "piano_polyphonic_mt3",
        "composition_id": "tba-polyphonic",
        "instrument": "piano",
        "challenges": ["polyphony", "hands"],
        "reuse": None,
    },
)


def slot_status(slot: dict[str, Any], cases: list[CaseSpec]) -> dict[str, Any]:
    match = next((c for c in cases if c.case_id == slot["case_id"]), None)
    if match is None:
        return {
            **slot,
            "present": False,
            "missing_inputs": [
                "audio",
                "performed_note_reference",
                "score_musicxml",
                "alignment",
                "source",
                "permitted_use",
            ],
            "notes": "Slot reserved. Do not invent labels or download recordings.",
        }
    return {
        **slot,
        "present": True,
        "split": match.split,
        "missing_inputs": match.inventory_gaps(),
        "reference_kind": match.reference_kind,
        "composition_id": match.composition_id,
        "performance_id": match.performance_id,
    }


def paired_inventory(*, root: Path | None = None) -> dict[str, Any]:
    cases = discover_cases(root=root)
    slots = [slot_status(slot, cases) for slot in INITIAL_SLOTS]
    leakage = check_split_leakage(cases)
    complete = [s for s in slots if s.get("present") and not s.get("missing_inputs")]
    return {
        "initial_target": INITIAL_TARGET,
        "expanded_target": EXPANDED_TARGET,
        "complete_slots": len(complete),
        "slots": slots,
        "leakage_warnings": leakage,
        "quality_claims_allowed": False,
        "reason": (
            "No paired recordings with performed-note references are checked in. "
            "Do not claim transcription quality gains until those inputs exist "
            "and evaluation has been run on the production path."
        ),
    }
