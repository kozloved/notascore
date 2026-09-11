"""Independent offline quality gates for score interpretation and transcription.

Score references must be annotated/quantized MIDI. Transcription references
must describe the performed timing. Neither path aligns to the reference or
calls a cloud service. Thresholds are engineering targets, not quality claims.
"""

import argparse
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path

from evaluation.matching import match_notes
from evaluation.score_ab import exported_notes
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.types import NoteEvent, ScoreMeta
from notation_engine.writer import NotationWriter


def evaluate(source, reference, output, *, stage="score", onset_floor=0.98, offset_floor=0.95):
    source, reference, output = Path(source), Path(reference), Path(output)
    if stage not in ("score", "transcription"):
        raise ValueError("stage must be score or transcription")
    if not all(0 <= value <= 1 for value in (onset_floor, offset_floor)):
        raise ValueError("F1 floors must be between 0 and 1")
    targets = [output / "score.musicxml", output / "result.json"]
    if any(p.resolve() in {source.resolve(), reference.resolve()} for p in targets):
        raise ValueError("Evaluation outputs must not overwrite input files")
    output.mkdir(parents=True, exist_ok=True)
    original = source.read_bytes()
    truth_bytes = reference.read_bytes()
    result = {"stage": stage, "source_sha256": hashlib.sha256(original).hexdigest(),
              "reference_sha256": hashlib.sha256(truth_bytes).hexdigest(),
              "thresholds": {"onset_pitch_f1": onset_floor, "onset_pitch_offset_f1": offset_floor},
              "checks": {}, "limitations": ["No musician readability or real audio inference evaluated"]}
    checks = result["checks"]
    try:
        raw, truth = ingest_midi(source), ingest_midi(reference)
        predicted = raw.notes
        if stage == "score":
            if len(raw.performance.meter_changes) > 1:
                raise ValueError("Changing meter is not yet supported")
            events = notes_to_events(raw.notes, raw.tempo_map)
            meta = ScoreMeta(time_sig_hint=raw.time_sig_hint, tempo_map=raw.tempo_map,
                             display_tempo_bpm=round(raw.tempo_map.bpm_at(0)))
            writer = NotationWriter()
            with redirect_stdout(io.StringIO()):
                score = writer.write_from_events_direct(events, meta, quantization_mode="performance")
                writer._export_musicxml(score, targets[0])
            predicted = exported_notes(targets[0], raw.tempo_map)
            selected = writer.last_quantized_events
            checks["source_note_identity"] = (
                len(selected) == len(events) and
                {e.note_id: (e.pitch, e.velocity, e.source_track_id, e.source_program) for e in selected}
                == {e.note_id: (e.pitch, e.velocity, e.source_track_id, e.source_program) for e in events})
            intended = [NoteEvent(e.pitch, raw.tempo_map.beats_to_seconds(e.start_beat),
                                  raw.tempo_map.beats_to_seconds(e.start_beat + e.duration_beats)) for e in selected]
            fidelity = match_notes(predicted, intended, onset_tolerance_sec=1e-5,
                                   offset_tolerance_sec=1e-5).to_dict()
            result["export_fidelity"] = fidelity
            checks["export_fidelity"] = fidelity["onset_pitch_offset_f1"] == 1.0
            checks["valid_measure_timelines"] = not writer.last_invariant_issues
            checks["no_fallback"] = not writer.last_fallback_used
            result["score_profile"] = writer.last_quantization_summary["score_profile"]
        else:
            # Separate per-program acoustic metrics: a pitch-correct but
            # instrument-wrong transcription must not pass as perfect.
            programs = sorted({n.source_program for n in raw.notes + truth.notes})
            by_program = {str(p): match_notes([n for n in raw.notes if n.source_program == p],
                                              [n for n in truth.notes if n.source_program == p]).to_dict()
                          for p in programs}
            result["instrument_metrics"] = by_program
            checks["instrument_onsets"] = all(m["onset_pitch_f1"] >= onset_floor for m in by_program.values())
            checks["instrument_offsets"] = all(m["onset_pitch_offset_f1"] >= offset_floor for m in by_program.values())
        metrics = match_notes(predicted, truth.notes).to_dict()
        result["reference_metrics"] = metrics
        checks["reference_onsets"] = metrics["onset_pitch_f1"] >= onset_floor
        checks["reference_offsets"] = metrics["onset_pitch_offset_f1"] >= offset_floor
        result["excluded_drum_notes"] = sum(n.is_drum for n in raw.performance.notes)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        checks["completed"] = False
    checks["source_bytes_unchanged"] = source.read_bytes() == original
    checks["reference_bytes_unchanged"] = reference.read_bytes() == truth_bytes
    result["passed"] = all(checks.values())
    targets[1].write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("score", "transcription"))
    parser.add_argument("source", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--onset-floor", type=float, default=0.98)
    parser.add_argument("--offset-floor", type=float, default=0.95)
    args = parser.parse_args()
    result = evaluate(args.source, args.reference, args.out, stage=args.stage,
                      onset_floor=args.onset_floor, offset_floor=args.offset_floor)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
