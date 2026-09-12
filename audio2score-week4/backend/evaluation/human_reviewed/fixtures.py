"""Repo-safe MIDI performances for the human-reviewed split.

These are generated engineering fixtures, not musician recordings. They exist
so CI can exercise the three evaluation tracks (acoustic / readability / export)
on rubato, ornaments, pedal, repeated notes, and meter changes.
"""

from __future__ import annotations

from pathlib import Path

import pretty_midi
import yaml

CASES = (
    {
        "id": "rubato",
        "title": "Rubato quarters",
        "tags": ["rubato", "piano", "human_reviewed"],
        "expected_meter": "4/4",
        "tempo_bpm": 80,
        "notes": "Performed quarters slow down; score time should still read as quarters.",
    },
    {
        "id": "ornaments",
        "title": "Grace-note ornament",
        "tags": ["ornaments", "piano", "human_reviewed"],
        "expected_meter": "4/4",
        "tempo_bpm": 100,
        "notes": "A short crushed note precedes a written quarter.",
    },
    {
        "id": "pedal",
        "title": "Sustain pedal overlap",
        "tags": ["pedal", "piano", "human_reviewed"],
        "expected_meter": "4/4",
        "tempo_bpm": 72,
        "notes": "CC64 holds through released keys; written durations stay shorter.",
    },
    {
        "id": "repeated_notes",
        "title": "Repeated same-pitch attacks",
        "tags": ["repeated_notes", "piano", "human_reviewed"],
        "expected_meter": "4/4",
        "tempo_bpm": 90,
        "notes": "Four C4 reattacks must remain four notes.",
    },
    {
        "id": "meter_changes",
        "title": "4/4 then 3/4",
        "tags": ["meter_changes", "piano", "human_reviewed"],
        "expected_meter": "4/4",
        "tempo_bpm": 120,
        "notes": "Meter changes mid-clip. Export may currently reject this; still review acoustics.",
    },
)


def _write_midi(
    path: Path,
    notes: list[tuple[int, float, float]],
    *,
    tempo: float = 120.0,
    meters: list[tuple[int, int, float]] | None = None,
    pedal: list[tuple[float, int]] | None = None,
) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    if meters:
        midi.time_signature_changes = [
            pretty_midi.TimeSignature(n, d, t) for n, d, t in meters
        ]
    inst = pretty_midi.Instrument(program=0, name="Piano")
    for pitch, start, end in notes:
        inst.notes.append(
            pretty_midi.Note(velocity=80, pitch=int(pitch), start=float(start), end=float(end))
        )
    if pedal:
        for time_sec, value in pedal:
            inst.control_changes.append(
                pretty_midi.ControlChange(number=64, value=int(value), time=float(time_sec))
            )
    midi.instruments.append(inst)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))


def _case_yaml(spec: dict) -> str:
    payload = {
        "id": spec["id"],
        "title": spec["title"],
        "instrument": "piano",
        "reference": {"midi": "reference.mid"},
        "expected": {"meter": spec["expected_meter"], "tempo_bpm": spec["tempo_bpm"]},
        "tags": list(spec["tags"]),
        "review": {
            "acoustic": {"status": "pending"},
            "readability": {"status": "pending"},
            "export": {"status": "mechanical"},
        },
        "notes": spec["notes"],
    }
    return yaml.safe_dump(payload, sort_keys=False)


def _performance_notes(case_id: str) -> dict:
    if case_id == "rubato":
        # Slowing quarters (~80 → 55 bpm) that should still read as 4/4 quarters.
        onsets = [0.0, 0.75, 1.62, 2.65]
        return {
            "notes": [(60 + i, t, t + 0.4) for i, t in enumerate(onsets)],
            "tempo": 80.0,
            "meters": [(4, 4, 0.0)],
        }
    if case_id == "ornaments":
        return {
            "notes": [(71, 0.97, 1.02), (72, 1.0, 1.6), (67, 2.0, 2.5)],
            "tempo": 100.0,
            "meters": [(4, 4, 0.0)],
        }
    if case_id == "pedal":
        return {
            "notes": [(60, 0.0, 0.4), (64, 0.5, 0.9), (67, 1.0, 1.4)],
            "tempo": 72.0,
            "meters": [(4, 4, 0.0)],
            "pedal": [(0.0, 127), (1.8, 0)],
        }
    if case_id == "repeated_notes":
        starts = [0.0, 0.18, 0.36, 0.54]
        return {
            "notes": [(60, t, t + 0.12) for t in starts],
            "tempo": 90.0,
            "meters": [(4, 4, 0.0)],
        }
    if case_id == "meter_changes":
        # Two 4/4 bars then two 3/4 bars of quarters.
        notes = []
        t = 0.0
        for _ in range(8):
            notes.append((60, t, t + 0.4))
            t += 0.5
        t = 4.0
        for _ in range(6):
            notes.append((64, t, t + 0.4))
            t += 0.5
        return {
            "notes": notes,
            "tempo": 120.0,
            "meters": [(4, 4, 0.0), (3, 4, 4.0)],
        }
    raise KeyError(case_id)


def prepare_human_reviewed(root: Path) -> list[Path]:
    """Write five MIDI cases under ``root`` (usually evaluation/human_reviewed)."""
    written: list[Path] = []
    for spec in CASES:
        case_dir = Path(root) / spec["id"]
        case_dir.mkdir(parents=True, exist_ok=True)
        payload = _performance_notes(spec["id"])
        midi_path = case_dir / "input.mid"
        ref_path = case_dir / "reference.mid"
        _write_midi(
            midi_path,
            payload["notes"],
            tempo=payload["tempo"],
            meters=payload.get("meters"),
            pedal=payload.get("pedal"),
        )
        ref_path.write_bytes(midi_path.read_bytes())
        (case_dir / "case.yaml").write_text(_case_yaml(spec), encoding="utf-8")
        written.append(case_dir)
    return written
