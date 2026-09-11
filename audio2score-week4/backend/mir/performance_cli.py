"""Convert a reference or transcribed MIDI without audio models or cloud services."""

import argparse
import json
from pathlib import Path

from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.types import ScoreMeta
from notation_engine.writer import NotationWriter


def convert(source: Path, output: Path, meter=None):
    report_path = output.with_suffix(".decisions.json")
    snapshot_path = output.with_suffix(".performance.json")
    midi_path = output.with_suffix(".score.mid")
    paths = [output, report_path, snapshot_path, midi_path]
    if source.resolve() in {p.resolve() for p in paths}:
        raise ValueError("Output must not replace the source MIDI")
    if len({p.resolve() for p in paths}) != len(paths):
        raise ValueError("Output paths collide; use a .musicxml output")
    ingested = ingest_midi(source)
    if len(ingested.performance.meter_changes) > 1:
        raise ValueError("Changing meter is not yet supported by the solo score planner")
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    meta = ScoreMeta(time_sig_hint=meter or ingested.time_sig_hint,
                     tempo_map=ingested.tempo_map,
                     display_tempo_bpm=round(ingested.tempo_map.bpm_at(0)))
    writer = NotationWriter()
    score = writer.write_from_events_direct(events, meta, quantization_mode="performance")
    output.parent.mkdir(parents=True, exist_ok=True)
    writer._export_musicxml(score, output)
    score.write("midi", fp=str(midi_path))
    ingested.performance.verify_midi(source.read_bytes())
    ingested.performance.write_json(snapshot_path)
    report_path.write_text(json.dumps(writer.notation_debug_payload(), indent=2, default=str),
                           encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--meter", help="Explicit meter, e.g. 4/4 or 6/8")
    args = parser.parse_args()
    report = convert(args.source, args.output, args.meter)
    print(f"Score: {args.output}\nDecisions: {report}")


if __name__ == "__main__":
    main()
