"""Meter-aware quantization and rhythm cases."""

from mir.meter import MeterEstimator, meter_from_time_signature
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


def test_downbeat_not_clamped_to_last_sixteenth():
    """A note just before the barline must snap to the next downbeat, not 3.75."""
    events = [_ev(72, 3.99, 1.0)]
    meter = meter_from_time_signature("4/4")
    quantized, _ = MeasureQuantizer().quantize(events, meter)
    assert quantized
    assert abs(quantized[0].start_beat - 4.0) < 1e-9


def test_isochronous_melody_prints_quarters():
    """Straight melody IOIs become even quarter notes, not a shrinking grid."""
    events = [
        _ev(65 + i, float(i) + 0.04 * ((i % 3) - 1), 0.92) for i in range(8)
    ]
    meter = meter_from_time_signature("4/4")
    quantized, _ = MeasureQuantizer().quantize(events, meter)
    starts = [round(e.start_beat, 6) for e in quantized]
    assert starts[0] == 0.0
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert gaps
    assert all(abs(g - 1.0) < 1e-6 for g in gaps)
    assert all(abs(e.duration_beats - 1.0) < 1e-6 for e in quantized)


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
