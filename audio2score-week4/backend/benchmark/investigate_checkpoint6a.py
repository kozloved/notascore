#!/usr/bin/env python3
"""Checkpoint 6A investigation: meter, Fast F1, and hand-assignment evidence.

Read-only against production algorithms. Writes a JSON dump for the report.
Run from audio2score-week4/backend:

  .venv/bin/python -m benchmark.investigate_checkpoint6a
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from audio_engine.madmom_beats import _processors, result_from_beat_array
from audio_engine.normalizer import AudioNormalizer
from benchmark.evaluate import _events_from_notes
from benchmark.fixtures.audio import render_notes_wav
from benchmark.fixtures.catalog import all_cases
from benchmark.fixtures.generate import write_corpus
from benchmark.load import load_cases
from benchmark.metrics import hand_metrics, match_notes, notes_from_reference_dicts
from benchmark.note_extract import notes_from_midi
from mir.hand_separator import HandSeparator
from mir.meter import MeterEstimator
from mir.midi_cleaner import MIDICleaner
from mir.midi_ingest import ingest_midi
from mir.pipeline import UnderstandingPipeline
from mir.types import MusicalEvent

WORK = BACKEND_ROOT / "benchmark" / "results" / "_work" / "investigate_6a"
OUT_JSON = BACKEND_ROOT / "benchmark" / "results" / "checkpoint6a_investigation.json"

METER_CASES = (
    "midi_6_8",
    "compound_6_8",
    "midi_rh_lh_tracks",
    "octave_doubling",
    "syncopation",
    "triplets",
    "waltz_3_4",
)

LOW_F1_CASES = (
    "midi_6_8",
    "midi_chords_and_melody",
    "octave_doubling",
    "hand_crossing",
    "middle_register",
    "polyphonic_rh",
    "compound_6_8",
    "dotted",
    "sixteenths",
    "triplets",
    "c_major_block_chords",
)

HAND_CASES = (
    "midi_chords_and_melody",
    "octave_doubling",
    "polyphonic_rh",
    "c_major_block_chords",
)


def _hyp_row(h) -> dict:
    return {
        "time_signature": h.time_signature,
        "score": round(float(h.score), 4),
        "confidence": round(float(h.confidence), 4),
        "measure_ql": h.measure_quarter_length,
        "evidence": h.evidence,
    }


def _events_from_ref(case, *, use_hands: bool) -> list[MusicalEvent]:
    return _events_from_notes(case, use_reference_hands=use_hands)


def inspect_madmom(wav_path: Path) -> dict:
    import soundfile as sf
    from madmom.audio.signal import Signal

    samples, sr = sf.read(str(wav_path), dtype="float32")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    norm = AudioNormalizer(target_sr=22050).normalize(samples, sr=sr)
    y = np.asarray(norm.samples, dtype=np.float32)
    rnn, dbn = _processors()
    act = rnn(Signal(y, sample_rate=int(norm.sample_rate)))
    tracked = np.asarray(dbn(act), dtype=float)
    parsed = result_from_beat_array(tracked)
    rows = np.atleast_2d(tracked)
    beats = [
        {"t": float(t), "position": int(round(float(p)))}
        for t, p in zip(rows[:, 0], rows[:, 1])
    ]
    return {
        "dbn_beats_per_bar_search": [3, 4],
        "dbn_cannot_emit_6_8": True,
        "raw_beats": beats,
        "parsed_meter": parsed.time_signature if parsed else None,
        "parsed_bpm": parsed.bpm if parsed else None,
        "parsed_beats_per_bar": parsed.beats_per_bar if parsed else None,
        "beat_count": len(parsed.beat_times) if parsed else 0,
        "downbeat_times": parsed.downbeat_times if parsed else [],
        "beat_times": parsed.beat_times if parsed else [],
        "clip_duration_sec": float(len(y) / norm.sample_rate),
        "clip_too_short_for_two_bars": bool(
            parsed is not None and len(parsed.downbeat_times) < 2
        ),
    }


def inspect_meter(case) -> dict:
    wav = WORK / "meter" / f"{case.case_id}.wav"
    render_notes_wav(case.reference_notes, wav)
    madmom = inspect_madmom(wav)

    ref_events = _events_from_ref(case, use_hands=True)
    ref_hyps = MeterEstimator().estimate(ref_events)

    unlabeled = _events_from_ref(case, use_hands=False)
    unlabeled_hyps = MeterEstimator().estimate(unlabeled)

    pipeline = UnderstandingPipeline(mode="fast")
    pipeline.transcribe(wav, case.case_id)
    debug = pipeline.last_debug
    plan = pipeline.notation.last_plan
    structure = pipeline.last_structure
    struct_hyps = []
    if structure is not None:
        struct_hyps = [_hyp_row(h) for h in structure.meter_hypotheses]

    hint = None
    if pipeline.last_debug is not None:
        hint = debug.extra.get("notation_time_signature") if debug else None
    meta_hint = None
    # BeatTracker owns Fast meter via time_sig_hint.
    beat_meter = pipeline.beat_tracker.last_time_signature
    beat_source = pipeline.beat_tracker.last_source

    origin = "unknown"
    if beat_meter and plan and plan.time_signature == beat_meter:
        origin = "beat_tracking_downbeat_hint"
        if madmom["dbn_cannot_emit_6_8"] and case.expected_meter in ("6/8", "12/8"):
            origin = "beat_tracking_cannot_represent_compound_meter"
        elif madmom["clip_too_short_for_two_bars"]:
            origin = "downbeat_detection_short_clip"
    elif debug and debug.selected_meter == (plan.time_signature if plan else None):
        origin = "meter_inference_MeterEstimator"
    elif beat_meter is None:
        origin = "fallback_default"

    return {
        "case_id": case.case_id,
        "expected": case.expected_meter,
        "predicted_plan": plan.time_signature if plan else None,
        "predicted_debug_estimator": debug.selected_meter if debug else None,
        "predicted_beat_tracker": beat_meter,
        "beat_tracker_source": beat_source,
        "notation_hint": hint,
        "root_pipeline_stage": origin,
        "short_onset_bias_applies_to_estimator": len(ref_events) < 8,
        "n_reference_onsets": len(ref_events),
        "madmom": madmom,
        "meter_estimator_on_reference_labeled": [_hyp_row(h) for h in ref_hyps],
        "meter_estimator_on_reference_unlabeled": [_hyp_row(h) for h in unlabeled_hyps],
        "meter_estimator_on_fast_structure": struct_hyps,
        "estimator_winner_reference": ref_hyps[0].time_signature if ref_hyps else None,
        "estimator_winner_fast": struct_hyps[0]["time_signature"] if struct_hyps else None,
    }


def _fmt_notes(notes) -> list[dict]:
    return [
        {
            "pitch": int(n.pitch),
            "start": round(float(n.start_time), 4),
            "end": round(float(n.end_time), 4),
            "vel": int(n.velocity or 0),
        }
        for n in notes
    ]


def inspect_f1(case) -> dict:
    wav = WORK / "f1" / f"{case.case_id}.wav"
    render_notes_wav(case.reference_notes, wav)
    reference = notes_from_reference_dicts(case.reference_notes)

    ingested = ingest_midi(case.input_midi)
    cleaned, decisions = MIDICleaner().clean_with_report(list(ingested.notes))

    pipeline = UnderstandingPipeline(mode="fast")
    pipeline.transcribe(wav, case.case_id)
    work = wav.parent / f"bp_{case.case_id}"
    raw_midi = work / f"{case.case_id}.raw.mid"
    raw_notes = notes_from_midi(raw_midi) if raw_midi.exists() else []
    debug = pipeline.last_debug
    structure_events = list(pipeline.last_structure.events) if pipeline.last_structure else []

    match_raw = match_notes(raw_notes, reference, onset_tolerance_sec=0.08)
    missing = []
    matched_ref = set()
    matched_pred = set()
    for ri, ref in enumerate(reference):
        best = None
        best_dt = 1e9
        for pi, pred in enumerate(raw_notes):
            if pi in matched_pred:
                continue
            if pred.pitch != ref.pitch:
                continue
            dt = abs(pred.start_time - ref.start_time)
            if dt <= 0.08 and dt < best_dt:
                best_dt = dt
                best = pi
        if best is None:
            missing.append(
                {
                    "pitch": ref.pitch,
                    "start_time": round(ref.start_time, 4),
                    "start_beat": next(
                        (
                            r.get("start_beat")
                            for r in case.reference_notes
                            if int(r["pitch"]) == ref.pitch
                            and abs(float(r["start_time"]) - ref.start_time) < 1e-4
                        ),
                        None,
                    ),
                }
            )
        else:
            matched_ref.add(ri)
            matched_pred.add(best)
    extra = [
        _fmt_notes([raw_notes[i]])[0]
        for i in range(len(raw_notes))
        if i not in matched_pred
    ]

    removed = list(debug.removed_notes) if debug else []
    loss_stage = "none"
    if len(raw_notes) < len(reference):
        if debug and debug.raw_note_count < len(reference) and not removed:
            loss_stage = "raw_transcription_basic_pitch"
        elif removed:
            loss_stage = "midi_cleaner"
        else:
            loss_stage = "raw_transcription_or_onset_mismatch"
    elif match_raw.f1 < 0.99:
        loss_stage = "timing_mismatch_vs_reference_seconds"

    return {
        "case_id": case.case_id,
        "n_reference": len(reference),
        "n_midi_ingest": len(ingested.notes),
        "n_cleaner_on_midi_ingest": len(cleaned),
        "cleaner_suppressions_on_midi": [
            {"pitch": d.pitch, "action": d.action.value, "reason": d.reason}
            for d in decisions
            if d.action.value == "suppress"
        ],
        "n_fast_raw_debug": debug.raw_note_count if debug else None,
        "n_fast_cleaned_debug": debug.cleaned_note_count if debug else None,
        "n_fast_raw_midi": len(raw_notes),
        "n_structure_events": len(structure_events),
        "removed_by_cleaner_fast": removed,
        "f1_raw_vs_reference": round(match_raw.f1, 4),
        "precision": round(match_raw.precision, 4),
        "recall": round(match_raw.recall, 4),
        "missing_vs_reference": missing,
        "extra_vs_reference": extra,
        "reference_notes": [
            {
                "pitch": r["pitch"],
                "start_time": r["start_time"],
                "start_beat": r["start_beat"],
                "hand": r.get("hand"),
            }
            for r in case.reference_notes
        ],
        "raw_notes": _fmt_notes(raw_notes),
        "loss_stage": loss_stage,
        "selected_tempo_bpm": debug.selected_tempo_bpm if debug else None,
        "catalog_tempo_bpm": case.tempo_bpm,
    }


def inspect_hands(case) -> dict:
    unlabeled = _events_from_ref(case, use_hands=False)
    separator = HandSeparator()
    predicted = separator.separate(list(unlabeled))
    metrics = hand_metrics(predicted, case.reference_notes)
    frames = separator._cluster(unlabeled)

    rows = []
    by_key = {(int(e.pitch), round(e.start_beat, 5)): e for e in predicted}
    for ref in case.reference_notes:
        key = (int(ref["pitch"]), round(float(ref["start_beat"]), 5))
        pred = by_key.get(key)
        # fallback: nearest
        if pred is None:
            for ev in predicted:
                if ev.pitch == int(ref["pitch"]) and abs(ev.start_beat - float(ref["start_beat"])) < 0.12:
                    pred = ev
                    break
        decision = next(
            (
                d
                for d in separator.last_decisions
                if d.pitch == int(ref["pitch"])
                and abs(d.start_beat - float(ref["start_beat"])) < 0.12
            ),
            None,
        )
        rows.append(
            {
                "pitch": ref["pitch"],
                "start_beat": ref["start_beat"],
                "reference_hand": ref.get("hand"),
                "catalog_role": ref.get("role"),
                "predicted_hand": pred.hand.value if pred else None,
                "predicted_role": pred.role if pred else None,
                "hand_confidence": pred.hand_confidence if pred else None,
                "hand_locked": bool(pred.hand_locked) if pred else False,
                "onset_group_size": next(
                    (
                        len(frame)
                        for frame in frames
                        if any(
                            ev.pitch == int(ref["pitch"])
                            and abs(ev.start_beat - float(ref["start_beat"])) < 0.08
                            for ev in frame
                        )
                    ),
                    None,
                ),
                "decision": None
                if decision is None
                else {
                    "selected": decision.selected,
                    "competing_hand": decision.competing_hand,
                    "competing_cost_delta": round(float(decision.competing_cost_delta), 4),
                    "confidence": round(float(decision.confidence), 4),
                    "factors": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in (decision.factors or {}).items()},
                },
            }
        )

    # cleaner onset groups
    groups = []
    for i, frame in enumerate(frames):
        groups.append(
            {
                "frame": i,
                "start_beat": frame[0].start_beat,
                "pitches": [e.pitch for e in frame],
                "roles": [e.role for e in frame],
                "incoming_hands": [e.hand.value for e in frame],
            }
        )

    spec = next(s for s in all_cases() if s.case_id == case.case_id)
    unique_hands = {n.hand for n in spec.notes}
    pitches_near_c4 = [n for n in spec.notes if 55 <= n.pitch <= 67]
    return {
        "case_id": case.case_id,
        "check_hands": spec.check_hands,
        "accuracy": metrics.accuracy,
        "confusion": metrics.confusion,
        "unique_catalog_hands": sorted(unique_hands),
        "notes_in_ambiguous_register_55_67": [
            {"pitch": n.pitch, "hand": n.hand, "role": n.role, "start": n.start_beat}
            for n in pitches_near_c4
        ],
        "onset_groups": groups,
        "rows": rows,
        "why_disabled_hypothesis": None
        if spec.check_hands
        else "catalog sets check_hands=False; see report for musical validity",
    }


def main() -> int:
    write_corpus()
    WORK.mkdir(parents=True, exist_ok=True)
    cases = {c.case_id: c for c in load_cases()}
    report = {
        "meter": [inspect_meter(cases[cid]) for cid in METER_CASES],
        "f1": [inspect_f1(cases[cid]) for cid in LOW_F1_CASES],
        "hands": [inspect_hands(cases[cid]) for cid in HAND_CASES],
        "all_check_hands": {
            s.case_id: s.check_hands for s in all_cases()
        },
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print("\n=== METER ===")
    for row in report["meter"]:
        print(
            f"{row['case_id']}: expected={row['expected']} plan={row['predicted_plan']} "
            f"madmom={row['predicted_beat_tracker']} estimator_ref={row['estimator_winner_reference']} "
            f"estimator_fast={row['estimator_winner_fast']} origin={row['root_pipeline_stage']}"
        )
        print("  estimator scores (reference labeled):")
        for h in row["meter_estimator_on_reference_labeled"]:
            print(f"    {h['time_signature']}: score={h['score']} conf={h['confidence']} ev={h['evidence']}")
        print(
            f"  madmom beats={[b['position'] for b in row['madmom']['raw_beats']]} "
            f"bpm={row['madmom']['parsed_bpm']} downbeats={row['madmom']['downbeat_times']}"
        )
    print("\n=== F1 ===")
    for row in report["f1"]:
        print(
            f"{row['case_id']}: ref={row['n_reference']} raw={row['n_fast_raw_midi']} "
            f"cleaned={row['n_fast_cleaned_debug']} struct={row['n_structure_events']} "
            f"f1={row['f1_raw_vs_reference']} stage={row['loss_stage']} missing={row['missing_vs_reference']}"
        )
    print("\n=== HANDS ===")
    for row in report["hands"]:
        print(
            f"{row['case_id']}: check_hands={row['check_hands']} acc={row['accuracy']} "
            f"confusion={row['confusion']}"
        )
        for note in row["rows"]:
            d = note.get("decision") or {}
            print(
                f"  p{note['pitch']} t={note['start_beat']} ref={note['reference_hand']} "
                f"pred={note['predicted_hand']} role={note['catalog_role']} "
                f"delta={d.get('competing_cost_delta')} conf={d.get('confidence')}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
