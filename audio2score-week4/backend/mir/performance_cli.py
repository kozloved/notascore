"""Convert a reference or transcribed MIDI without audio models or cloud services."""

import argparse
import json
from pathlib import Path

from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.types import ScoreMeta
from notation_engine.writer import NotationWriter


def convert(source: Path, output: Path, meter=None, settings=None):
    from mir.notation_settings import parse_notation_settings

    report_path = output.with_suffix(".decisions.json")
    snapshot_path = output.with_suffix(".performance.json")
    midi_path = output.with_suffix(".score.mid")
    settings_path = output.with_suffix(".notation_settings.json")
    settings = parse_notation_settings(settings)
    paths = [output, report_path, snapshot_path, midi_path, settings_path]
    if source.resolve() in {p.resolve() for p in paths}:
        raise ValueError("Output must not replace the source MIDI")
    if len({p.resolve() for p in paths}) != len(paths):
        raise ValueError("Output paths collide; use a .musicxml output")
    ingested = ingest_midi(source)
    if len(ingested.performance.meter_changes) > 1:
        raise ValueError("Changing meter is not yet supported by the solo score planner")
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    meta = ScoreMeta(time_sig_hint=settings.meter or meter or ingested.time_sig_hint,
                     tempo_map=ingested.tempo_map,
                     display_tempo_bpm=round(ingested.tempo_map.bpm_at(0)))
    meta.extra = {
        "notation_settings": settings.to_dict(),
        "pedal_events": list(ingested.pedal_events or []),
        "preserve_midi_tempo": True,
    }
    writer = NotationWriter()
    score = writer.write_from_events_direct(events, meta, quantization_mode="performance")
    output.parent.mkdir(parents=True, exist_ok=True)
    writer._export_musicxml(score, output)
    score.write("midi", fp=str(midi_path))
    ingested.performance.verify_midi(source.read_bytes())
    ingested.performance.write_json(snapshot_path)
    from mir.interpretation_context import InterpretationContext
    from timing.tempo_map import MusicalTimeMap

    duration = max((n.end_time for n in ingested.notes), default=4.0)
    time_map = MusicalTimeMap.from_tempo_map(ingested.tempo_map, duration_sec=max(duration, 1.0))
    accepted = tuple(n.note_id for n in ingested.notes if n.note_id)
    context = InterpretationContext(
        time_map=time_map,
        selected_meter=str(settings.meter or meter or ingested.time_sig_hint or "4/4"),
        display_bpm=float(ingested.tempo_map.bpm_at(0)),
        accepted_source_note_ids=accepted,
        has_recorded_selection=True,
        layout_decisions=tuple(writer.last_quantization_decisions or ()),
        pedal_events=tuple((float(t), int(v)) for t, v in (ingested.pedal_events or [])),
        midi_sha256=ingested.performance.midi_sha256,
        source_backend=ingested.performance.source_backend or "midi",
    )
    context.write_json(output.with_suffix(".interpretation_context.json"))
    context_digest = context.identity_digest()
    settings_path.write_text(
        json.dumps(
            {
                "notation_settings": settings.to_dict(),
                "algorithm_version": settings.algorithm_version,
                "midi_sha256": ingested.performance.midi_sha256,
                "notation_cache_key": settings.cache_key(
                    ingested.performance.midi_sha256, context_digest=context_digest
                ),
                "interpretation_context_digest": context_digest,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    report_path.write_text(json.dumps(writer.notation_debug_payload(), indent=2, default=str),
                           encoding="utf-8")
    return report_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--meter", help="Explicit meter, e.g. 4/4 or 6/8")
    parser.add_argument(
        "--interpretation",
        choices=("readable", "literal"),
        help="Notation interpretation (default: readable / current engine)",
    )
    parser.add_argument(
        "--display-grid",
        dest="display_grid",
        choices=("auto", "eighth", "sixteenth", "thirty-second"),
    )
    parser.add_argument(
        "--readable-v2",
        action="store_true",
        help="Opt in to improved readable policies (performance-score-2)",
    )
    args = parser.parse_args()
    payload = {}
    if args.interpretation:
        payload["interpretation"] = args.interpretation
    if args.display_grid:
        payload["display_grid"] = args.display_grid
    if args.meter:
        payload["meter"] = args.meter
    if args.readable_v2:
        payload["algorithm_version"] = "performance-score-2"
        payload["interpretation"] = payload.get("interpretation") or "readable"
    report = convert(args.source, args.output, args.meter, settings=payload or None)
    print(f"Score: {args.output}\nDecisions: {report}")


if __name__ == "__main__":
    main()
