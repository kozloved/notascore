"""Dummy Quality/MT3 command: write a one-note MIDI file.

A real command should run MR-MT3 (or similar) on {input} and write MIDI to
{output}. This stub exists so Quality mode can be wired without GPU weights.

Usage:
  python scripts/example_mt3.py <input_audio> <output_midi>
"""

from __future__ import annotations

import sys
from pathlib import Path

import pretty_midi


def write_dummy_midi(output_path: Path, input_name: str = "") -> None:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    piano = pretty_midi.Instrument(program=0, name="MT3")
    piano.notes.append(
        pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5)
    )
    midi.instruments.append(piano)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    midi.write(str(output_path))
    suffix = f" from {input_name}" if input_name else ""
    print(f"Wrote example MIDI{suffix} to {output_path}")


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python example_mt3.py <input_audio> <output_midi>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        sys.exit(1)

    write_dummy_midi(output_path, input_path.name)


if __name__ == "__main__":
    main()
