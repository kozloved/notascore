"""Diagnostic MIDI writers for Checkpoint 8 forensics."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pretty_midi

from mir.types import NoteEvent


def _note(n: NoteEvent, *, velocity: int | None = None) -> pretty_midi.Note:
    start = float(n.start_time)
    end = max(start + 0.01, float(n.end_time))
    vel = int(velocity if velocity is not None else n.velocity)
    return pretty_midi.Note(
        velocity=max(1, min(127, vel)),
        pitch=int(n.pitch),
        start=start,
        end=end,
    )


def write_single_track_midi(
    notes: Sequence[NoteEvent],
    path: Path,
    *,
    track_name: str = "Notes",
    bpm: float = 120.0,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = pretty_midi.PrettyMIDI(initial_tempo=float(bpm) if bpm else 120.0)
    inst = pretty_midi.Instrument(program=0, name=track_name)
    for n in notes:
        inst.notes.append(_note(n))
    midi.instruments.append(inst)
    midi.write(str(path))
    return path


def write_indexed_notes_midi(
    all_notes: Sequence[NoteEvent],
    indices: Sequence[int],
    path: Path,
    *,
    track_name: str,
    bpm: float = 120.0,
) -> Path:
    selected = [all_notes[i] for i in indices if 0 <= i < len(all_notes)]
    return write_single_track_midi(selected, path, track_name=track_name, bpm=bpm)


def write_overlay_midi(
    *,
    reference: Sequence[NoteEvent],
    correct_preds: Sequence[NoteEvent],
    false_positives: Sequence[NoteEvent],
    false_negatives: Sequence[NoteEvent],
    timing_errors: Sequence[NoteEvent],
    path: Path,
    bpm: float = 120.0,
) -> Path:
    """Combined multi-track diagnostic overlay."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    midi = pretty_midi.PrettyMIDI(initial_tempo=float(bpm) if bpm else 120.0)
    tracks = [
        ("Reference", reference, 90),
        ("Correct", correct_preds, 100),
        ("FalsePositives", false_positives, 110),
        ("FalseNegatives", false_negatives, 80),
        ("TimingErrors", timing_errors, 95),
    ]
    for name, notes, vel in tracks:
        inst = pretty_midi.Instrument(program=0, name=name)
        for n in notes:
            inst.notes.append(_note(n, velocity=vel))
        midi.instruments.append(inst)
    midi.write(str(path))
    return path


def export_stage_diagnostic_midis(
    *,
    out_dir: Path,
    reference: Sequence[NoteEvent],
    predicted: Sequence[NoteEvent],
    classification,
    bpm: float = 120.0,
    prefix: str = "",
) -> dict[str, str]:
    """Write category MIDIs for one stage. Empty categories still get empty files."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    def _p(name: str) -> Path:
        return out_dir / f"{prefix}{name}"

    paths["reference_raw"] = str(
        write_single_track_midi(reference, _p("reference_raw.mid"), track_name="Reference", bpm=bpm)
    )
    paths["prediction"] = str(
        write_single_track_midi(predicted, _p("prediction.mid"), track_name="Prediction", bpm=bpm)
    )
    paths["matches"] = str(
        write_indexed_notes_midi(
            predicted,
            classification.match_pred_indices,
            _p("matches.mid"),
            track_name="Matches",
            bpm=bpm,
        )
    )
    paths["false_negatives"] = str(
        write_indexed_notes_midi(
            reference,
            classification.fn_ref_indices,
            _p("false_negatives.mid"),
            track_name="FalseNegatives",
            bpm=bpm,
        )
    )
    paths["false_positives"] = str(
        write_indexed_notes_midi(
            predicted,
            classification.fp_pred_indices,
            _p("false_positives.mid"),
            track_name="FalsePositives",
            bpm=bpm,
        )
    )
    pitch_preds = [j for _, j in classification.pitch_error_pairs]
    paths["pitch_errors"] = str(
        write_indexed_notes_midi(
            predicted, pitch_preds, _p("pitch_errors.mid"), track_name="PitchErrors", bpm=bpm
        )
    )
    timing_preds = [j for _, j in classification.timing_error_pairs]
    paths["timing_errors"] = str(
        write_indexed_notes_midi(
            predicted, timing_preds, _p("timing_errors.mid"), track_name="TimingErrors", bpm=bpm
        )
    )
    paths["fragmented_notes"] = str(
        write_indexed_notes_midi(
            reference,
            classification.fragmented_ref_indices,
            _p("fragmented_notes.mid"),
            track_name="Fragmented",
            bpm=bpm,
        )
    )
    paths["duplicate_notes"] = str(
        write_indexed_notes_midi(
            predicted,
            classification.duplicate_pred_indices,
            _p("duplicate_notes.mid"),
            track_name="Duplicates",
            bpm=bpm,
        )
    )

    correct = [predicted[i] for i in classification.match_pred_indices if i < len(predicted)]
    fps = [predicted[i] for i in classification.fp_pred_indices if i < len(predicted)]
    fns = [reference[i] for i in classification.fn_ref_indices if i < len(reference)]
    timing = [predicted[i] for i in timing_preds if i < len(predicted)]
    paths["diagnostic_overlay"] = str(
        write_overlay_midi(
            reference=reference,
            correct_preds=correct,
            false_positives=fps,
            false_negatives=fns,
            timing_errors=timing,
            path=_p("diagnostic_overlay.mid"),
            bpm=bpm,
        )
    )
    return paths
