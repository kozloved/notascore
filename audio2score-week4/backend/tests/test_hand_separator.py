"""Hand separation: context-aware Viterbi, not a middle-C gate."""

from mir.hand_separator import HandSeparator, RegisterSplitHandSeparator
from mir.types import Hand, MusicalEvent


def _ev(pitch, start, dur=0.5, role=None, velocity=80):
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        velocity=velocity,
        role=role,
    )


def test_simple_two_hand_scales():
    events = []
    for i in range(8):
        events.append(_ev(48 + i, float(i), role="bass"))
        events.append(_ev(72 + i, float(i), role="melody"))
    out = HandSeparator().separate(events)
    low = [e for e in out if e.pitch < 60]
    high = [e for e in out if e.pitch >= 72]
    assert all(e.hand == Hand.LEFT for e in low)
    assert all(e.hand == Hand.RIGHT for e in high)


def test_middle_register_accompaniment():
    events = []
    for i in range(6):
        t = float(i)
        events.extend(
            [
                _ev(55, t, dur=1.0, role="accompaniment"),
                _ev(59, t, dur=1.0, role="accompaniment"),
                _ev(62, t, dur=1.0, role="accompaniment"),
                _ev(76 + (i % 3), t, dur=1.0, role="melody"),
            ]
        )
    out = HandSeparator().separate(events)
    accomp = [e for e in out if e.role == "accompaniment"]
    melody = [e for e in out if e.role == "melody"]
    assert sum(1 for e in accomp if e.hand == Hand.LEFT) >= len(accomp) - 2
    assert all(e.hand == Hand.RIGHT for e in melody)


def test_hand_crossing_contrary_motion():
    events = []
    rh = [72, 71, 69, 67, 65, 64, 62, 60, 59, 57]
    lh = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64]
    for i, (a, b) in enumerate(zip(lh, rh)):
        events.append(_ev(a, float(i), role="bass"))
        events.append(_ev(b, float(i), role="melody"))
    out = HandSeparator().separate(events)
    by_start = {}
    for e in out:
        by_start.setdefault(e.start_beat, []).append(e)
    last = by_start[9.0]
    hands = {e.pitch: e.hand for e in last}
    assert hands[64] == Hand.LEFT
    assert hands[57] == Hand.RIGHT


def test_octave_passages():
    events = []
    for i in range(4):
        t = float(i)
        events.extend(
            [
                _ev(36, t, role="bass"),
                _ev(48, t, role="bass"),
                _ev(60, t, role="melody"),
                _ev(72, t, role="melody"),
            ]
        )
    out = HandSeparator().separate(events)
    assert all(e.hand == Hand.LEFT for e in out if e.pitch <= 48)
    assert all(e.hand == Hand.RIGHT for e in out if e.pitch >= 60)


def test_wide_arpeggios():
    pitches = [36, 40, 43, 48, 52, 55, 60, 64, 67, 72]
    events = [_ev(p, i * 0.25) for i, p in enumerate(pitches)]
    out = HandSeparator().separate(events)
    assert any(e.hand == Hand.LEFT for e in out)
    assert any(e.hand == Hand.RIGHT for e in out)
    assert out[0].hand == Hand.LEFT
    assert out[-1].hand == Hand.RIGHT


def test_melody_below_middle_c():
    events = []
    melody = [64, 62, 60, 59, 57, 55]
    bass = [36, 38, 40, 41, 43, 45]
    for i, (m, b) in enumerate(zip(melody, bass)):
        events.append(_ev(b, float(i), role="bass"))
        events.append(_ev(m, float(i), role="melody"))
    out = HandSeparator().separate(events)
    for e in out:
        if e.role == "melody":
            assert e.hand == Hand.RIGHT
        if e.role == "bass":
            assert e.hand == Hand.LEFT


def test_bass_notes_above_middle_c():
    events = []
    bass = [48, 52, 55, 60, 62, 64]
    melody = [72, 74, 76, 77, 79, 81]
    for i, (b, m) in enumerate(zip(bass, melody)):
        events.append(_ev(b, float(i), role="bass"))
        events.append(_ev(m, float(i), role="melody"))
    out = HandSeparator().separate(events)
    for e in out:
        if e.role == "bass":
            assert e.hand == Hand.LEFT, e
        if e.role == "melody":
            assert e.hand == Hand.RIGHT, e


def test_chords_around_middle_c_stay_together():
    events = [
        _ev(60, 0.0, dur=1.0),
        _ev(64, 0.0, dur=1.0),
        _ev(67, 0.0, dur=1.0),
        _ev(48, 0.0, dur=1.0, role="bass"),
    ]
    out = HandSeparator().separate(events)
    chord_hands = {e.hand for e in out if e.pitch in (60, 64, 67)}
    assert len(chord_hands) == 1
    bass = next(e for e in out if e.pitch == 48)
    assert bass.hand == Hand.LEFT


def test_ambiguous_isolated_middle_c():
    out = HandSeparator().separate([_ev(60, 0.0)])
    assert out[0].hand in (Hand.AMBIGUOUS, Hand.RIGHT, Hand.LEFT)
    assert out[0].hand_confidence <= 0.85


def test_legacy_split_still_available():
    events = [_ev(59, 0.0), _ev(60, 0.0)]
    out = RegisterSplitHandSeparator().separate(events)
    assert next(e for e in out if e.pitch == 59).hand == Hand.LEFT
    assert next(e for e in out if e.pitch == 60).hand == Hand.RIGHT
