"""Regression fixtures for dangerous cleaner / notation rules.

These lock the MVP contract: transcription fidelity first. Notation may
re-notate timing; it must not delete valid events. Hand assignment must
not rewrite pitch or performance time.
"""

from __future__ import annotations

from mir.hand_separator import HandSeparator
from mir.meter import MeterEstimator
from mir.midi_cleaner import MIDICleaner
from mir.models import CleaningAction
from mir.pipeline_config import ValidationMode
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent, NoteEvent


def _n(pitch, start, end, vel=80, conf=0.9, **kwargs):
    return NoteEvent(
        pitch=pitch,
        start_time=start,
        end_time=end,
        velocity=vel,
        confidence=conf,
        **kwargs,
    )


def _ev(pitch, start, dur, hand=Hand.RIGHT, **kwargs):
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        hand=hand,
        voice=0,
        velocity=80,
        **kwargs,
    )


def test_safe_mode_keeps_legitimate_octave():
    notes = [
        _n(48, 0.0, 1.0, vel=80, conf=0.85),
        _n(60, 0.0, 1.0, vel=78, conf=0.82),
    ]
    cleaned, report = MIDICleaner(mode=ValidationMode.STRICT_SAFE).clean_with_report(notes)
    assert {n.pitch for n in cleaned} == {48, 60}
    assert all(d.action != CleaningAction.SUPPRESS for d in report if "octave" in d.reason)


def test_safe_mode_keeps_quiet_legitimate_octave():
    notes = [
        _n(48, 0.0, 1.0, vel=80, conf=0.9),
        _n(60, 0.01, 1.0, vel=28, conf=0.4),
    ]
    cleaned, _ = MIDICleaner(mode=ValidationMode.STRICT_SAFE).clean_with_report(notes)
    assert {n.pitch for n in cleaned} == {48, 60}


def test_conservative_may_drop_quiet_octave_ghost_not_real_doubling():
    ghost = [
        _n(60, 0.0, 1.0, vel=90, conf=0.8),
        _n(72, 0.02, 0.9, vel=30, conf=0.2),
    ]
    doubling = [
        _n(48, 0.0, 1.0, vel=80, conf=0.7),
        _n(60, 0.01, 1.0, vel=78, conf=0.68),
    ]
    cons = MIDICleaner(mode=ValidationMode.CONSERVATIVE)
    assert {n.pitch for n in cons.clean(ghost)} == {60}
    assert {n.pitch for n in cons.clean(doubling)} == {48, 60}


def test_safe_mode_keeps_grace_like_short_notes():
    notes = [
        _n(71, 0.0, 0.03, vel=88, conf=0.8),
        _n(72, 0.10, 0.50, vel=80, conf=0.9),
    ]
    cleaned, report = MIDICleaner(mode=ValidationMode.STRICT_SAFE).clean_with_report(notes)
    assert {n.pitch for n in cleaned} == {71, 72}
    assert any("micro_note" in d.reason for d in report)


def test_safe_mode_preserves_repeated_notes():
    notes = [
        _n(60, 0.0, 0.20, vel=80),
        _n(60, 0.22, 0.42, vel=80),
    ]
    cleaned = MIDICleaner(mode=ValidationMode.STRICT_SAFE).clean(notes)
    assert len(cleaned) == 2


def test_safe_mode_does_not_collapse_dense_chords():
    notes = [
        _n(60, 0.500, 1.0, vel=80),
        _n(64, 0.512, 1.0, vel=75),
        _n(67, 0.525, 1.0, vel=70),
        _n(71, 0.530, 1.0, vel=68),
    ]
    cleaned, report = MIDICleaner(mode=ValidationMode.STRICT_SAFE).clean_with_report(notes)
    assert len(cleaned) == 4
    starts = {round(n.start_time, 6) for n in cleaned}
    assert len(starts) == 4
    assert any(d.reason == "chord_start_snap_skipped" for d in report)


def test_safe_mode_preserves_expressive_timing():
    notes = [
        _n(60, 0.103, 0.410, vel=80),
        _n(64, 0.487, 0.801, vel=76),
        _n(67, 0.912, 1.205, vel=70),
    ]
    raw_starts = [n.start_time for n in notes]
    cleaned = MIDICleaner(mode=ValidationMode.STRICT_SAFE).clean(notes)
    assert [n.start_time for n in cleaned] == raw_starts


def test_exact_duplicate_still_removed_in_safe_mode():
    notes = [
        _n(60, 0.0, 0.5, vel=80, conf=0.9),
        _n(60, 0.0004, 0.5, vel=40, conf=0.4),
    ]
    cleaned, report = MIDICleaner(mode=ValidationMode.STRICT_SAFE).clean_with_report(notes)
    assert len(cleaned) == 1
    assert any(d.reason == "duplicate_same_pitch_onset" for d in report)


def test_invalid_midi_clamped_in_safe_mode():
    notes = [
        _n(200, 0.0, 0.5, vel=200),
        _n(60, 0.5, 0.5, vel=80),  # zero duration
    ]
    cleaned, report = MIDICleaner(mode=ValidationMode.STRICT_SAFE).clean_with_report(notes)
    assert len(cleaned) == 2
    assert all(0 <= n.pitch <= 127 for n in cleaned)
    assert all(n.duration > 0 for n in cleaned)
    assert any(d.reason == "invalid_midi_clamped" for d in report)


def test_quantizer_does_not_delete_events():
    events = [
        _ev(72, i * 0.25, 0.22, note_id=f"n{i:04d}")
        for i in range(16)
    ]
    meter = MeterEstimator().select(events)
    q = MeasureQuantizer()
    quantized, decisions = q.quantize(events, meter)
    assert len(quantized) == 16
    assert q.last_summary["events_removed"] == 0
    assert q.last_summary["raw_events"] == 16
    ids = {e.note_id for e in quantized}
    assert ids == {f"n{i:04d}" for i in range(16)}


def test_triplets_remain_triplets():
    events = [
        _ev(72, 0.0, 1.0 / 3.0, note_id="a"),
        _ev(74, 1.0 / 3.0, 1.0 / 3.0, note_id="b"),
        _ev(76, 2.0 / 3.0, 1.0 / 3.0, note_id="c"),
        _ev(77, 1.0, 1.0 / 3.0, note_id="d"),
        _ev(79, 4.0 / 3.0, 1.0 / 3.0, note_id="e"),
        _ev(81, 5.0 / 3.0, 1.0 / 3.0, note_id="f"),
    ]
    meter = MeterEstimator().select(events)
    q = MeasureQuantizer()
    quantized, _ = q.quantize(events, meter)
    assert len(quantized) == 6
    starts = [round(e.start_beat, 3) for e in quantized]
    assert starts[0] == 0.0
    # Genuine triplet onsets stay off the 16th grid or on 1/3.
    third_like = sum(1 for e in quantized if abs((e.start_beat * 3) - round(e.start_beat * 3)) < 0.05)
    assert third_like >= 4


def test_straight_sixteenths_not_converted_to_tuplets():
    events = [_ev(72, i * 0.25, 0.25, note_id=f"s{i}") for i in range(16)]
    meter = MeterEstimator().select(events)
    q = MeasureQuantizer()
    quantized, _ = q.quantize(events, meter)
    assert q.last_summary["triplet_decisions"] == 0
    starts = [round(e.start_beat, 3) for e in quantized]
    assert all(abs(b - a - 0.25) < 0.02 for a, b in zip(starts, starts[1:]))


def test_syncopation_survives_quantization():
    events = [
        _ev(72, 0.0, 0.5, note_id="a"),
        _ev(74, 0.5, 1.0, note_id="b"),
        _ev(76, 1.5, 0.5, note_id="c"),
        _ev(77, 2.0, 1.0, note_id="d"),
        _ev(79, 3.0, 1.0, note_id="e"),
    ]
    meter = MeterEstimator().select(events)
    quantized, _ = MeasureQuantizer().quantize(events, meter)
    mid = [e for e in quantized if e.note_id == "b"][0]
    assert abs(mid.start_beat - 0.5) < 0.13


def test_hand_separator_does_not_mutate_pitch_or_timing():
    events = [
        _ev(48, 0.0, 0.5, hand=Hand.UNKNOWN, note_id="l", start_time_sec=0.11),
        _ev(72, 0.0, 0.5, hand=Hand.UNKNOWN, note_id="r", start_time_sec=0.11),
        _ev(50, 1.0, 0.5, hand=Hand.UNKNOWN, note_id="l2", start_time_sec=0.61),
        _ev(74, 1.0, 0.5, hand=Hand.UNKNOWN, note_id="r2", start_time_sec=0.61),
    ]
    original = [(e.note_id, e.pitch, e.start_beat, e.duration_beats, e.velocity, e.start_time_sec) for e in events]
    out = HandSeparator().separate(events)
    after = [(e.note_id, e.pitch, e.start_beat, e.duration_beats, e.velocity, e.start_time_sec) for e in out]
    assert after == original
    assert {e.hand for e in out} <= {Hand.LEFT, Hand.RIGHT, Hand.AMBIGUOUS}


def test_midi_roundtrip_preserves_pitches_and_counts(tmp_path):
    import pretty_midi

    from mir.midi_ingest import ingest_midi
    from mir.pipeline import UnderstandingPipeline

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    for i, pitch in enumerate([60, 64, 67, 72]):
        inst.notes.append(
            pretty_midi.Note(velocity=80, pitch=pitch, start=i * 0.5, end=i * 0.5 + 0.4)
        )
    inst.notes.append(pretty_midi.Note(velocity=70, pitch=48, start=0.0, end=2.0))
    midi.instruments.append(inst)
    path = tmp_path / "roundtrip.mid"
    midi.write(str(path))

    ingested = ingest_midi(path)
    xml = UnderstandingPipeline().transcribe_midi(path, "roundtrip")
    assert "score-partwise" in xml.lower() or "<?xml" in xml
    score = tmp_path / "bp_roundtrip" / "roundtrip.score.mid"
    raw = tmp_path / "bp_roundtrip" / "roundtrip.raw.mid"
    validated = tmp_path / "bp_roundtrip" / "roundtrip.validated.mid"
    assert raw.exists() and validated.exists() and score.exists()
    out = pretty_midi.PrettyMIDI(str(score))
    pitches = sorted(n.pitch for inst in out.instruments for n in inst.notes)
    assert set(pitches) >= {48, 60, 64, 67, 72}
    assert len(ingested.notes) == 5


def test_ab_safe_does_not_reduce_legitimate_texture():
    from evaluation.ab import compare_cleaner_variants

    notes = [
        _n(48, 0.0, 1.0, vel=80),
        _n(60, 0.0, 1.0, vel=78),
        _n(64, 0.02, 1.0, vel=76),
        _n(67, 0.03, 1.0, vel=74),
        _n(72, 0.5, 0.53, vel=90, conf=0.9),  # grace-like
        _n(71, 0.55, 0.90, vel=80),
    ]
    results = compare_cleaner_variants(notes)
    assert results["B"].note_count >= results["A"].note_count
    assert results["B"].note_count == 6
