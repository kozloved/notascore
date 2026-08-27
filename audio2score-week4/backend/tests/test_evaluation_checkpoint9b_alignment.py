"""Checkpoint 9B alignment forensics tests.

Proves MIDI seconds conversion and that the evaluator responds correctly to
controlled timing transforms. Does not change production tolerances.
"""

from __future__ import annotations

from pathlib import Path

import pretty_midi
import pytest

from evaluation.alignment.analyze import classify_corpus
from evaluation.alignment.midi_time import (
    audit_midi_file,
    conversion_method_doc,
    load_notes_seconds,
    write_constant_tempo_midi,
)
from evaluation.alignment.transforms import (
    EXACT_MATCH,
    MISSED_REFERENCE,
    SPURIOUS,
    WRONG_OCTAVE,
    correspondence_analysis,
    f1_at,
    offset_search,
    scale_notes,
    scale_search,
    shift_notes,
    tolerance_sweep,
)
from mir.midi_ingest import ingest_midi
from mir.types import NoteEvent


def _n(pitch: int, start: float, end: float) -> NoteEvent:
    return NoteEvent(pitch=pitch, start_time=start, end_time=end, velocity=80)


def test_conversion_method_documented():
    doc = conversion_method_doc()
    assert "pretty_midi" in doc
    assert "ticks" in doc.lower() or "tempo" in doc.lower()


@pytest.mark.parametrize("bpm", [60.0, 120.0, 160.0])
def test_constant_tempo_midi_roundtrip_seconds(tmp_path: Path, bpm: float):
    """Known absolute seconds must survive write→ingest at constant tempo."""
    notes = [
        (60, 0.0, 0.5),
        (62, 1.0, 1.5),
        (64, 2.0, 2.25),
    ]
    path = write_constant_tempo_midi(tmp_path / f"t{int(bpm)}.mid", notes, bpm=bpm)
    loaded = load_notes_seconds(path)
    assert len(loaded) == 3
    for (pitch, start, end), got in zip(notes, sorted(loaded, key=lambda n: n.start_time)):
        assert int(got.pitch) == pitch
        assert abs(float(got.start_time) - start) < 1e-3
        assert abs(float(got.end_time) - end) < 1e-3
    audit = audit_midi_file(path)
    assert abs(audit.tempo_events[0][1] - bpm) < 1e-6


def test_tempo_change_midi_absolute_seconds(tmp_path: Path):
    """Notes authored in absolute seconds remain absolute after ingest."""
    # Write via pretty_midi with tempo change using initial tempo then patch
    path = tmp_path / "change.mid"
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    # Manually create a tempo change at 1.0s by adjusting tick scales
    # 120 BPM → 0.5s per beat; at resolution default
    res = pm.resolution
    tick_at_1s = int(round(1.0 / (60.0 / (120.0 * res))))
    pm._tick_scales = [
        (0, 60.0 / (120.0 * res)),
        (tick_at_1s, 60.0 / (90.0 * res)),
    ]
    pm._update_tick_to_time(tick_at_1s + res * 8)
    inst = pretty_midi.Instrument(program=0)
    # Place notes at known absolute seconds
    for pitch, start, end in ((60, 0.0, 0.4), (62, 1.2, 1.6), (64, 2.0, 2.3)):
        inst.notes.append(
            pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=end)
        )
    pm.instruments.append(inst)
    pm.write(str(path))

    loaded = ingest_midi(path).notes
    loaded = sorted(loaded, key=lambda n: n.start_time)
    assert abs(loaded[0].start_time - 0.0) < 2e-2
    assert abs(loaded[1].start_time - 1.2) < 2e-2
    assert abs(loaded[2].start_time - 2.0) < 2e-2


def test_perfect_prediction_f1_is_one():
    ref = [_n(60, 0.0, 0.5), _n(64, 1.0, 1.5)]
    pred = [_n(60, 0.0, 0.5), _n(64, 1.0, 1.5)]
    m = f1_at(pred, ref, onset_tolerance_sec=0.05)
    assert m["onset_pitch_f1"] == pytest.approx(1.0)


def test_shift_50ms_within_official_tolerance():
    ref = [_n(60, 0.0, 0.5), _n(64, 1.0, 1.5)]
    # Stay strictly inside the closed 50 ms window (avoid float edge cases).
    pred = shift_notes(ref, 0.049)
    m = f1_at(pred, ref, onset_tolerance_sec=0.05)
    assert m["onset_pitch_f1"] == pytest.approx(1.0)


def test_shift_100ms_outside_50ms_tolerance():
    ref = [_n(60, 0.0, 0.5), _n(64, 1.0, 1.5)]
    pred = shift_notes(ref, 0.100)
    m50 = f1_at(pred, ref, onset_tolerance_sec=0.05)
    m150 = f1_at(pred, ref, onset_tolerance_sec=0.15)
    assert m50["onset_pitch_f1"] == pytest.approx(0.0)
    assert m150["onset_pitch_f1"] == pytest.approx(1.0)


def test_shift_200ms_requires_wide_tolerance():
    ref = [_n(60, 0.0, 0.5)]
    pred = shift_notes(ref, 0.200)
    assert f1_at(pred, ref, onset_tolerance_sec=0.05)["onset_pitch_f1"] == 0.0
    assert f1_at(pred, ref, onset_tolerance_sec=0.20)["onset_pitch_f1"] == pytest.approx(1.0)


def test_exact_2x_time_scale():
    ref = [_n(60, 0.0, 0.5), _n(62, 1.0, 1.5), _n(64, 2.0, 2.4)]
    pred = scale_notes(ref, 2.0, anchor_sec=0.0)
    # Anchor note at t=0 still matches; later notes do not → F1 < 1.
    assert f1_at(pred, ref)["onset_pitch_f1"] < 0.7
    recovered = scale_search(pred, ref)
    assert recovered["best_scale"] == pytest.approx(0.5)
    assert recovered["f1_at_best_scale"] == pytest.approx(1.0)


def test_exact_half_time_scale():
    ref = [_n(60, 0.0, 0.5), _n(62, 1.0, 1.5)]
    pred = scale_notes(ref, 0.5, anchor_sec=0.0)
    recovered = scale_search(pred, ref)
    assert recovered["best_scale"] == pytest.approx(2.0)
    assert recovered["f1_at_best_scale"] == pytest.approx(1.0)


def test_wrong_octave_classification():
    ref = [_n(60, 0.0, 0.5)]
    pred = [_n(72, 0.0, 0.5)]
    corr = correspondence_analysis(ref, pred)
    assert corr["categories"][WRONG_OCTAVE] >= 1
    assert f1_at(pred, ref)["onset_pitch_f1"] == pytest.approx(0.0)


def test_correct_onset_wrong_pitch():
    ref = [_n(60, 0.0, 0.5)]
    pred = [_n(62, 0.0, 0.5)]
    m = f1_at(pred, ref)
    assert m["onset_f1"] > 0.9
    assert m["onset_pitch_f1"] == pytest.approx(0.0)


def test_leading_offset_found_by_search():
    ref = [_n(60, 1.0, 1.5), _n(62, 2.0, 2.5)]
    pred = [_n(60, 0.0, 0.5), _n(62, 1.0, 1.5)]  # 1.0s early
    off = offset_search(pred, ref, range_ms=(-1500, 1500), step_ms=50)
    assert off["best_offset_ms"] == pytest.approx(1000.0)
    assert off["f1_at_best_offset"] == pytest.approx(1.0)


def test_tempo_metadata_alone_does_not_alter_absolute_note_timing(tmp_path: Path):
    """Same absolute note seconds at 60 vs 120 BPM → identical F1 vs a fixed ref."""
    notes = [(60, 0.0, 0.5), (64, 1.0, 1.4)]
    p60 = write_constant_tempo_midi(tmp_path / "a60.mid", notes, bpm=60.0)
    p120 = write_constant_tempo_midi(tmp_path / "a120.mid", notes, bpm=120.0)
    n60 = load_notes_seconds(p60)
    n120 = load_notes_seconds(p120)
    ref = [_n(60, 0.0, 0.5), _n(64, 1.0, 1.4)]
    assert f1_at(n60, ref)["onset_pitch_f1"] == pytest.approx(1.0)
    assert f1_at(n120, ref)["onset_pitch_f1"] == pytest.approx(1.0)
    # Absolute starts match across tempo meta
    assert abs(n60[0].start_time - n120[0].start_time) < 1e-3


def test_tolerance_sweep_monotonic_for_shifted_perfect():
    ref = [_n(60, 0.0, 0.5), _n(64, 1.0, 1.5), _n(67, 2.0, 2.5)]
    pred = shift_notes(ref, 0.12)
    rows = tolerance_sweep(pred, ref)
    f1s = [r["onset_pitch_f1"] for r in rows]
    # Non-decreasing as tolerance widens
    assert all(f1s[i] <= f1s[i + 1] + 1e-12 for i in range(len(f1s) - 1))
    assert f1s[0] < 0.1  # 25ms
    assert f1s[-1] == pytest.approx(1.0)  # 300ms


def test_correspondence_exact_and_spurious():
    ref = [_n(60, 0.0, 0.5)]
    pred = [_n(60, 0.01, 0.5), _n(70, 3.0, 3.5)]
    corr = correspondence_analysis(ref, pred)
    assert corr["categories"][EXACT_MATCH] == 1
    assert corr["categories"][SPURIOUS] == 1
    assert corr["categories"][MISSED_REFERENCE] == 0


def test_classify_corpus_genuine_when_no_alignment_gain():
    payload = {
        "case_id": "X",
        "status": "ok",
        "case_root_cause_hint": "GENUINE_TRANSCRIPTION_FAILURE",
        "alignment_deltas": {
            "delta_f1_tol_300_vs_50": 0.02,
            "delta_f1_best_offset": 0.01,
            "delta_f1_best_scale": 0.0,
            "delta_f1_best_combined": 0.02,
        },
    }
    d = classify_corpus([payload])
    assert d["decision"] == "A"
