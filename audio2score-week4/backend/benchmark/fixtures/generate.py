"""Write deterministic corpus files from the synthetic catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pretty_midi

from benchmark.fixtures.catalog import CaseSpec, NoteSpec, all_cases

BACKEND_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = BACKEND_ROOT / "benchmark" / "corpus"
REFERENCE_ROOT = BACKEND_ROOT / "benchmark" / "reference"


def beat_to_sec(beat: float, bpm: float) -> float:
    return float(beat) * 60.0 / float(bpm)


def note_to_ref(spec: NoteSpec, bpm: float) -> dict:
    start = beat_to_sec(spec.start_beat, bpm)
    end = beat_to_sec(spec.start_beat + spec.duration_beats, bpm)
    return {
        "pitch": spec.pitch,
        "start_beat": spec.start_beat,
        "duration_beats": spec.duration_beats,
        "start_time": round(start, 6),
        "end_time": round(end, 6),
        "velocity": spec.velocity,
        "hand": spec.hand,
        "voice": spec.voice,
        "role": spec.role,
        "keep": spec.keep,
    }


def _parse_ts(ts: str) -> tuple[int, int]:
    num, den = ts.split("/", 1)
    return int(num), int(den)


def write_midi(spec: CaseSpec, path: Path) -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=float(spec.tempo_bpm))
    rh = pretty_midi.Instrument(program=0, name="RH")
    lh = pretty_midi.Instrument(program=0, name="LH")
    bpm = float(spec.tempo_bpm)
    for note in spec.notes:
        start = beat_to_sec(note.start_beat, bpm)
        end = beat_to_sec(note.start_beat + note.duration_beats, bpm)
        midi_note = pretty_midi.Note(
            velocity=int(note.velocity),
            pitch=int(note.pitch),
            start=start,
            end=max(start + 0.02, end),
        )
        if note.hand == "left":
            lh.notes.append(midi_note)
        else:
            rh.notes.append(midi_note)
    if rh.notes:
        midi.instruments.append(rh)
    if lh.notes:
        midi.instruments.append(lh)
    if not midi.instruments:
        midi.instruments.append(pretty_midi.Instrument(program=0, name="Music"))
    num, den = _parse_ts(spec.time_signature)
    midi.time_signature_changes.append(
        pretty_midi.TimeSignature(numerator=num, denominator=den, time=0.0)
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(path))


def case_payload(spec: CaseSpec) -> tuple[dict, dict]:
    bpm = float(spec.tempo_bpm)
    notes = [note_to_ref(n, bpm) for n in spec.notes]
    expected_hands = {}
    for n in spec.notes:
        expected_hands[str(n.pitch)] = n.hand
    metadata = {
        "id": spec.case_id,
        "category": spec.category,
        "description": spec.description,
        "tempo_bpm": spec.tempo_bpm,
        "time_signature": spec.time_signature,
        "key": spec.key,
        "ci": spec.ci,
        "generation": {
            "kind": "synthetic_midi",
            "seed": 0,
            "sample_rate": 22050,
            "copyrighted": False,
            "source": "benchmark.fixtures.catalog",
        },
        "expected": {
            "meter": spec.time_signature,
            "key": spec.key,
            "voice_count_rh": spec.voice_count_rh,
            "keep_all_octaves": spec.keep_all_octaves,
            "notation_plan_required": spec.notation_plan_required,
            "check_hands": spec.check_hands,
        },
    }
    reference = {
        "notes": notes,
        "expected": metadata["expected"],
        "expected_hands": expected_hands,
        "expected_meter": spec.time_signature,
        "expected_key": spec.key,
        "expected_voice_assignments": [
            {
                "pitch": n.pitch,
                "start_beat": n.start_beat,
                "voice": n.voice,
                "hand": n.hand,
            }
            for n in spec.notes
        ],
    }
    return metadata, reference


def write_case(spec: CaseSpec, corpus_root: Path = CORPUS_ROOT) -> Path:
    case_dir = corpus_root / spec.category / spec.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    metadata, reference = case_payload(spec)
    (case_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    (case_dir / "reference.json").write_text(
        json.dumps(reference, indent=2) + "\n", encoding="utf-8"
    )
    write_midi(spec, case_dir / "reference.mid")
    write_midi(spec, case_dir / "input.mid")
    return case_dir


def write_corpus(corpus_root: Path = CORPUS_ROOT) -> list[Path]:
    REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
    index = []
    written: list[Path] = []
    for spec in all_cases():
        path = write_case(spec, corpus_root)
        written.append(path)
        index.append(
            {
                "id": spec.case_id,
                "category": spec.category,
                "path": str(path.relative_to(corpus_root.parent)),
                "ci": spec.ci,
            }
        )
    (REFERENCE_ROOT / "index.json").write_text(
        json.dumps({"cases": index, "count": len(index)}, indent=2) + "\n",
        encoding="utf-8",
    )
    return written


def main() -> int:
    paths = write_corpus()
    print(f"Wrote {len(paths)} corpus cases under {CORPUS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
