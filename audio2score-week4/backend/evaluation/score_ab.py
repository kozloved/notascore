"""Offline quantizer comparison on MIDI pairs, including exported score timing."""

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from time import perf_counter

from evaluation.matching import match_notes
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.types import NoteEvent, ScoreMeta
from notation_engine.writer import NotationWriter
from notation_engine.integrity import musicxml_attacks


def exported_notes(path, tempo_map):
    """Reconstruct source attacks by joining only contiguous same-voice ties."""
    return [NoteEvent(pitch, tempo_map.beats_to_seconds(start), tempo_map.beats_to_seconds(end))
            for pitch, start, end in musicxml_attacks(path)]


def compare_case(source, reference, output):
    source_midi, reference_midi = ingest_midi(source), ingest_midi(reference)
    events = notes_to_events(source_midi.notes, source_midi.tempo_map)
    meta = ScoreMeta(time_sig_hint=source_midi.time_sig_hint,
                     tempo_map=source_midi.tempo_map,
                     display_tempo_bpm=round(source_midi.tempo_map.bpm_at(0)))
    rows = []
    output.mkdir(parents=True, exist_ok=True)
    for mode in ("adaptive", "performance"):
        started = perf_counter()
        row = {"mode": mode, "source": str(source), "reference": str(reference)}
        writer = NotationWriter()
        try:
            with redirect_stdout(io.StringIO()):
                score = writer.write_from_events_direct(events, meta, quantization_mode=mode)
                path = output / f"{mode}.musicxml"
                writer._export_musicxml(score, path)
            predicted = exported_notes(path, source_midi.tempo_map)
            intended = [NoteEvent(ev.pitch, source_midi.tempo_map.beats_to_seconds(ev.start_beat),
                                  source_midi.tempo_map.beats_to_seconds(ev.start_beat + ev.duration_beats))
                        for ev in writer.last_quantized_events]
            row.update(status="ok", reference_metrics=match_notes(predicted, reference_midi.notes).to_dict(),
                       export_preservation=match_notes(predicted, intended, onset_tolerance_sec=1e-5,
                                                       offset_tolerance_sec=1e-5).to_dict())
        except Exception as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        row.update(seconds=perf_counter() - started, diagnostics=writer.notation_debug_payload())
        rows.append(row)
    return rows


def discover(root):
    for source in sorted(root.rglob("input.mid")):
        reference = source.with_name("reference.mid")
        if reference.exists():
            yield source, reference
    for source in sorted(root.rglob("*_raw.mid")):
        reference = source.with_name(source.name.removesuffix("_raw.mid") + "_q.mid")
        if reference.exists():
            yield source, reference


def run(root, output):
    pairs = list(discover(root))
    if not pairs:
        raise ValueError(f"No MIDI pairs under {root}")
    rows = []
    for index, (source, reference) in enumerate(pairs):
        case_rows = compare_case(source, reference, output / f"case-{index:03d}")
        rows.extend(case_rows)
        print(f"{source.parent.name}: " + ", ".join(f"{r['mode']}={r['status']}" for r in case_rows), flush=True)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    lines = ["# Score Engine Comparison", "", "Timing metrics use the source MIDI tempo map; no alignment to the reference is fitted.",
             "These are objective timing checks, not musician readability ratings.", "",
             "| Case | Engine | Status | Onset/pitch F1 | Offset F1 | Export fidelity F1 |",
             "|---|---|---|---:|---:|---:|"]
    for row in rows:
        metrics, fidelity = row.get("reference_metrics", {}), row.get("export_preservation", {})
        def fmt(value):
            return "n/a" if value is None else f"{value:.3f}"
        lines.append(f"| {Path(row['source']).parent.name} | {row['mode']} | {row['status']} | "
                     f"{fmt(metrics.get('onset_pitch_f1'))} | {fmt(metrics.get('onset_pitch_offset_f1'))} | "
                     f"{fmt(fidelity.get('onset_pitch_offset_f1'))} |")
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.out)


if __name__ == "__main__":
    main()
