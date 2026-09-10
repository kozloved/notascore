"""Adaptive notation quantizer: raw vs notation, chords, patterns, triplets."""

from __future__ import annotations

import pretty_midi

from mir.models import MeterHypothesis, PlannedNote, PlannedRest
from mir.pipeline import UnderstandingPipeline
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.plan import NotationPlanner


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


def _meter_44():
    return MeterHypothesis(
        time_signature="4/4",
        numerator=4,
        denominator=4,
        measure_quarter_length=4.0,
        score=1.0,
        confidence=1.0,
    )


def test_raw_events_remain_unchanged_after_quantization():
    events = [
        _ev(60, 0.03, 0.47, note_id="a"),
        _ev(64, 0.07, 0.44, note_id="b"),
        _ev(67, 0.51, 0.48, note_id="c"),
    ]
    original = [(e.note_id, e.pitch, e.start_beat, e.duration_beats) for e in events]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    after = [(e.note_id, e.pitch, e.start_beat, e.duration_beats) for e in events]
    assert after == original
    raw_snap = [
        (e.note_id, e.pitch, e.start_beat, e.duration_beats) for e in q.last_raw_events
    ]
    assert raw_snap == original
    assert q.last_notation_events is not q.last_raw_events
    assert [e.start_beat for e in q.last_notation_events] != [
        e.start_beat for e in q.last_raw_events
    ] or [e.duration_beats for e in q.last_notation_events] != [
        e.duration_beats for e in q.last_raw_events
    ]
    assert len(notation) == len(events)


def test_quantization_produces_separate_notation_representation():
    events = [_ev(72, i * 0.5 + 0.04, 0.46, note_id=f"n{i}") for i in range(8)]
    q = MeasureQuantizer(mode="adaptive")
    notation, decisions = q.quantize(events, _meter_44())
    assert q.last_raw_events
    assert q.last_notation_events
    assert [id(e) for e in q.last_raw_events] != [id(e) for e in q.last_notation_events]
    assert all(d.get("quantized_start") is not None for d in decisions)
    starts = [round(e.start_beat, 6) for e in notation]
    assert starts[0] == 0.0
    assert all(abs(b - a - 0.5) < 0.02 for a, b in zip(starts, starts[1:]))


def test_chord_notes_remain_aligned():
    events = [
        _ev(60, 0.000, 1.0, note_id="c", hand=Hand.LEFT),
        _ev(64, 0.031, 0.95, note_id="e"),
        _ev(67, 0.048, 0.92, note_id="g"),
        _ev(72, 0.055, 0.90, note_id="c2"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    starts = {round(e.start_beat, 6) for e in notation}
    assert len(starts) == 1
    assert list(starts)[0] == 0.0


def test_repeated_eighth_pattern_stays_consistent():
    # Performance jitter around a repeated eighth pulse — not sixteenths.
    raw_starts = [0.00, 0.52, 0.97, 1.48, 2.03, 2.49, 3.02, 3.47]
    events = [
        _ev(72, s, 0.42, note_id=f"n{i}") for i, s in enumerate(raw_starts)
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    starts = [round(e.start_beat, 6) for e in notation]
    expected = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]
    assert starts == expected
    assert q.last_summary.get("triplet_decisions", 0) == 0


def test_triplets_recognized_only_when_justified():
    meter = _meter_44()
    # One slightly late eighth must not become a triplet grid.
    eighths = [
        _ev(72, 0.0, 0.5, note_id="a"),
        _ev(74, 0.5, 0.5, note_id="b"),
        _ev(76, 1.0, 0.5, note_id="c"),
        _ev(77, 1.33, 0.5, note_id="d"),  # closer to 1/3 of beat 1, still one outlier
        _ev(79, 2.0, 0.5, note_id="e"),
        _ev(81, 2.5, 0.5, note_id="f"),
        _ev(83, 3.0, 0.5, note_id="g"),
        _ev(84, 3.5, 0.5, note_id="h"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    outlier, _ = q.quantize(eighths, meter)
    by_id = {e.note_id: e for e in outlier}
    assert abs((by_id["d"].start_beat * 3) - round(by_id["d"].start_beat * 3)) > 0.05 or round(
        by_id["d"].start_beat, 3
    ) in (1.25, 1.5, 1.0)
    assert q.last_summary.get("triplet_decisions", 0) == 0

    genuine = [
        _ev(72, 0.0, 1.0 / 3.0, note_id="a"),
        _ev(74, 1.0 / 3.0, 1.0 / 3.0, note_id="b"),
        _ev(76, 2.0 / 3.0, 1.0 / 3.0, note_id="c"),
        _ev(77, 1.0, 1.0 / 3.0, note_id="d"),
        _ev(79, 4.0 / 3.0, 1.0 / 3.0, note_id="e"),
        _ev(81, 5.0 / 3.0, 1.0 / 3.0, note_id="f"),
    ]
    q2 = MeasureQuantizer(mode="adaptive")
    tripped, _ = q2.quantize(genuine, meter)
    third_like = sum(
        1 for e in tripped if abs((e.start_beat * 3) - round(e.start_beat * 3)) < 0.05
    )
    assert third_like >= 4


def test_tiny_rests_and_odd_durations_are_cleaned():
    events = [
        _ev(72, 0.0, 0.47, note_id="a"),
        _ev(74, 0.50, 0.47, note_id="b"),
        _ev(76, 1.0, 0.47, note_id="c"),
        _ev(77, 1.5, 0.47, note_id="d"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, _meter_44())
    durs = [round(e.duration_beats, 6) for e in notation]
    assert all(abs(d - 0.5) < 0.02 for d in durs)
    assert not any(abs(d - 0.47) < 1e-9 for d in durs)

    plan, _ = NotationPlanner().build(
        events,
        meta=ScoreMeta(display_tempo_bpm=120, time_sig_hint="4/4"),
        quantization_mode="adaptive",
    )
    rests = [
        el
        for measure in plan.measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedRest)
    ]
    tiny = [r for r in rests if 0 < r.duration_q < 0.2]
    assert tiny == []


def test_bar_boundaries_remain_musically_valid():
    meter = _meter_44()
    events = [
        _ev(60, 0.0, 1.0, note_id="a"),
        _ev(62, 1.0, 1.0, note_id="b"),
        _ev(64, 2.0, 1.0, note_id="c"),
        _ev(65, 3.0, 1.0, note_id="d"),
        _ev(67, 3.996, 1.0, note_id="e"),
        _ev(69, 5.0, 1.0, note_id="f"),
        _ev(71, 6.0, 1.0, note_id="g"),
        _ev(72, 7.0, 1.0, note_id="h"),
    ]
    q = MeasureQuantizer(mode="adaptive")
    notation, _ = q.quantize(events, meter)
    by_id = {e.note_id: e for e in notation}
    assert abs(by_id["e"].start_beat - 4.0) < 0.02
    # Downbeat of bar 2 must not also exist as a last-16th of bar 1.
    assert by_id["e"].start_beat >= 4.0 - 1e-9
    held = [_ev(72, 3.0, 2.0, note_id="hold")]
    q2 = MeasureQuantizer(mode="adaptive")
    held_out, _ = q2.quantize(held, meter)
    assert abs(held_out[0].start_beat - 3.0) < 0.02
    assert held_out[0].duration_beats >= 1.9


def test_pipeline_keeps_raw_midi_and_quantizes_notation(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "adaptive")
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    # Jittered C-major chord then eighths.
    for pitch, start in ((60, 0.00), (64, 0.03), (67, 0.05)):
        inst.notes.append(
            pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=start + 0.45)
        )
    for i, pitch in enumerate((72, 74, 76, 77)):
        start = 0.5 + i * 0.5 + 0.03
        inst.notes.append(
            pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=start + 0.4)
        )
    midi.instruments.append(inst)
    path = tmp_path / "fixture.mid"
    midi.write(str(path))

    pipe = UnderstandingPipeline()
    xml = pipe.transcribe(path, "raw-vs-notation")
    assert "score-partwise" in xml.lower()
    assert pipe.last_raw_notes is not None
    assert pipe.last_notation_notes is not None
    assert pipe.last_quantized_events is not None
    raw_starts = [round(n.start_time, 4) for n in pipe.last_raw_notes]
    assert 0.03 in raw_starts or any(abs(t - 0.03) < 1e-3 for t in raw_starts)
    raw_midi = tmp_path / "bp_raw-vs-notation" / "raw-vs-notation.raw.mid"
    score_midi = tmp_path / "bp_raw-vs-notation" / "raw-vs-notation.score.mid"
    assert raw_midi.exists()
    assert score_midi.exists()
    raw_pm = pretty_midi.PrettyMIDI(str(raw_midi))
    raw_pm_starts = sorted(
        round(n.start, 3) for inst in raw_pm.instruments for n in inst.notes
    )
    assert any(abs(t - 0.03) < 0.02 for t in raw_pm_starts)
    q_starts = [e.start_beat for e in pipe.last_notation_notes]
    chord = [e for e in pipe.last_notation_notes if e.pitch in (60, 64, 67)]
    if len(chord) >= 3:
        chord_starts = {round(e.start_beat, 6) for e in chord}
        assert len(chord_starts) == 1
    planner = NotationPlanner()
    plan, _ = planner.build(
        list(pipe.last_quantized_events),
        meta=ScoreMeta(display_tempo_bpm=120, time_sig_hint="4/4"),
        quantization_mode="off",
    )
    notes = [
        el
        for measure in plan.measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedNote)
    ]
    assert notes
    assert all(el.duration_q >= 0.25 - 1e-9 for el in notes)
