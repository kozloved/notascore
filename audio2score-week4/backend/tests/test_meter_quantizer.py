"""Meter-aware quantization and rhythm cases."""

from mir.meter import MeterEstimator
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.plan import NotationPlanner


def _ev(pitch, start, dur, hand=Hand.RIGHT):
    return MusicalEvent(
        pitch=pitch, start_beat=start, duration_beats=dur, hand=hand, voice=0, velocity=80
    )


def test_straight_eighths_prefer_4_4():
    events = [_ev(72, i * 0.5, 0.5) for i in range(16)]
    meter = MeterEstimator().select(events)
    assert meter.time_signature in ("4/4", "2/4")


def test_compound_meter_6_8():
    # Accents every dotted quarter: 0, 1.5, 3.0, 4.5...
    events = []
    for bar in range(4):
        base = bar * 3.0
        events.append(_ev(60, base + 0.0, 0.5, hand=Hand.LEFT))
        events.append(_ev(72, base + 0.0, 0.5))
        events.append(_ev(72, base + 0.5, 0.5))
        events.append(_ev(72, base + 1.0, 0.5))
        events.append(_ev(60, base + 1.5, 0.5, hand=Hand.LEFT))
        events.append(_ev(72, base + 1.5, 0.5))
        events.append(_ev(72, base + 2.0, 0.5))
        events.append(_ev(72, base + 2.5, 0.5))
    meter = MeterEstimator().select(events)
    assert meter.time_signature in ("6/8", "12/8", "3/4")


def test_sixteenths_quantize_to_quarter_grid():
    events = [_ev(72, i * 0.25, 0.25) for i in range(16)]
    meter = MeterEstimator().select(events)
    quantized, decisions = MeasureQuantizer().quantize(events, meter)
    assert len(quantized) == 16
    starts = [round(e.start_beat, 3) for e in quantized]
    assert starts[0] == 0.0
    assert all(abs(b - a - 0.25) < 0.02 or abs(b - a - 0.0) < 1e-6 for a, b in zip(starts, starts[1:]))


def test_triplets_grid_available():
    events = [
        _ev(72, 0.0, 1.0 / 3.0),
        _ev(74, 1.0 / 3.0, 1.0 / 3.0),
        _ev(76, 2.0 / 3.0, 1.0 / 3.0),
        _ev(77, 1.0, 1.0 / 3.0),
        _ev(79, 4.0 / 3.0, 1.0 / 3.0),
        _ev(81, 5.0 / 3.0, 1.0 / 3.0),
    ]
    meter = MeterEstimator().select(events)
    quantized, _ = MeasureQuantizer().quantize(events, meter)
    assert len(quantized) == 6


def test_dotted_rhythm():
    events = [
        _ev(72, 0.0, 0.75),
        _ev(74, 0.75, 0.25),
        _ev(76, 1.0, 0.75),
        _ev(77, 1.75, 0.25),
        _ev(79, 2.0, 1.0),
        _ev(81, 3.0, 1.0),
    ]
    meter = MeterEstimator().select(events)
    quantized, _ = MeasureQuantizer().quantize(events, meter)
    assert any(abs(e.duration_beats - 0.75) < 0.05 for e in quantized)


def test_syncopation_not_flattened():
    events = [
        _ev(72, 0.0, 0.5),
        _ev(74, 0.5, 1.0),  # across the beat
        _ev(76, 1.5, 0.5),
        _ev(77, 2.0, 1.0),
        _ev(79, 3.0, 1.0),
    ]
    meter = MeterEstimator().select(events)
    quantized, _ = MeasureQuantizer().quantize(events, meter)
    mids = [e for e in quantized if e.pitch == 74]
    assert mids
    assert mids[0].start_beat == 0.5 or abs(mids[0].start_beat - 0.5) < 0.13


def test_ties_across_measures():
    events = [
        MusicalEvent(
            pitch=72, start_beat=3.0, duration_beats=2.0, hand=Hand.RIGHT, voice=0
        )
    ]
    plan, _ = NotationPlanner().build(events, meta=ScoreMeta(display_tempo_bpm=120))
    notes = []
    for measure in plan.measures:
        for staff in measure.staves:
            for voice in staff.voices:
                notes.extend(
                    el for el in voice.elements if el.__class__.__name__ == "PlannedNote"
                )
    tied = [n for n in notes if n.tie]
    assert tied, "held note across a barline should be tied"


def test_quantization_off_keeps_raw_beats():
    events = [
        _ev(72, 0.11, 0.37),
        _ev(74, 0.51, 0.41),
    ]
    q, decisions = MeasureQuantizer(mode="off").quantize(
        events, MeterEstimator().select(events)
    )
    assert [round(e.start_beat, 4) for e in q] == [0.125, 0.5]
    assert [round(e.duration_beats, 4) for e in q] == [0.375, 0.375]
    assert all(d.get("reason") == "off_fine_grid" for d in decisions)
    adaptive, _ = MeasureQuantizer(mode="adaptive").quantize(
        events, MeterEstimator().select(events)
    )
    assert [e.start_beat for e in q] != [e.start_beat for e in adaptive] or [
        e.duration_beats for e in q
    ] != [e.duration_beats for e in adaptive]


def test_pipeline_config_defaults_to_quantization_off(monkeypatch):
    monkeypatch.delenv("TRANSCRIPTION_QUANTIZATION_MODE", raising=False)
    from mir.pipeline_config import QuantizationMode, load_pipeline_config, parse_quantization_mode

    assert load_pipeline_config().quantization_mode == QuantizationMode.OFF
    assert parse_quantization_mode("off") == QuantizationMode.OFF
    assert parse_quantization_mode("identity") == QuantizationMode.OFF
