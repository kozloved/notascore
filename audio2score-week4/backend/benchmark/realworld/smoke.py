"""Generate a tiny local smoke corpus. Not a copyrighted-audio substitute."""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.fixtures.audio import render_notes_wav
from benchmark.fixtures.catalog import all_cases
from benchmark.fixtures.generate import note_to_ref, write_midi
from benchmark.realworld.schema import DEFAULT_LOCAL_ROOT

# Framework proof only: three synthetic textures, no production targets.
SMOKE_CASES = (
    {
        "id": "smoke_solo_quarters",
        "catalog_id": "c_major_quarters",
        "title": "Smoke: solo quarters",
        "instrumentation": "synthetic monophonic sine tones (not a recording)",
        "notes": "Framework smoke. Additive synthesis, not real-world piano.",
    },
    {
        "id": "smoke_compound_6_8",
        "catalog_id": "compound_6_8",
        "title": "Smoke: compound 6/8",
        "instrumentation": "synthetic two-hand sine tones",
        "notes": "Framework smoke. Bass on dotted-quarter pulses.",
    },
    {
        "id": "smoke_waltz_3_4",
        "catalog_id": "waltz_3_4",
        "title": "Smoke: waltz 3/4",
        "instrumentation": "synthetic bass+melody sine tones",
        "notes": "Framework smoke. Bass on the downbeat of each 3/4 bar.",
    },
)


def smoke_manifest_payload() -> dict:
    cases = []
    for row in SMOKE_CASES:
        spec = next(c for c in all_cases() if c.case_id == row["catalog_id"])
        cases.append(
            {
                "id": row["id"],
                "title": row["title"],
                "audio": f"{row['id']}.wav",
                "reference_performance_midi": f"{row['id']}_performance.mid",
                "reference_score_midi": f"{row['id']}_score.mid",
                "expected_meter": spec.time_signature,
                "instrumentation": row["instrumentation"],
                "notes": row["notes"],
            }
        )
    return {
        "version": 1,
        "description": (
            "Minimal 3-case smoke corpus generated locally. "
            "Audio is not committed. Not a real-world music set."
        ),
        "local_root": "local",
        "cases": cases,
    }


def prepare_smoke(local_root: Path | None = None) -> Path:
    """Write 3 short synthetic WAV+MIDI files into the gitignored local root."""
    root = Path(local_root) if local_root is not None else DEFAULT_LOCAL_ROOT
    root.mkdir(parents=True, exist_ok=True)
    catalog = {c.case_id: c for c in all_cases()}
    for row in SMOKE_CASES:
        spec = catalog[row["catalog_id"]]
        notes = [note_to_ref(n, float(spec.tempo_bpm)) for n in spec.notes]
        render_notes_wav(notes, root / f"{row['id']}.wav", sample_rate=22050)
        write_midi(spec, root / f"{row['id']}_performance.mid")
        write_midi(spec, root / f"{row['id']}_score.mid")
    manifest_path = root / "smoke.generated.json"
    payload = smoke_manifest_payload()
    payload["local_root"] = str(root)
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path
