"""Voice continuity: chords share a voice; independent streams do not."""

from mir.types import Hand, MusicalEvent
from mir.voice_separator import VoiceSeparator


def _ev(pitch, start, dur, hand=Hand.RIGHT, role=None):
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        hand=hand,
        role=role,
        velocity=80,
    )


def test_melody_plus_accompaniment():
    events = [
        _ev(67, 0.0, 1.0, role="melody"),
        _ev(69, 1.0, 1.0, role="melody"),
        _ev(71, 2.0, 1.0, role="melody"),
        _ev(48, 0.0, 1.0, hand=Hand.LEFT, role="accompaniment"),
        _ev(52, 0.0, 1.0, hand=Hand.LEFT, role="accompaniment"),
        _ev(55, 0.0, 1.0, hand=Hand.LEFT, role="accompaniment"),
        _ev(48, 1.0, 1.0, hand=Hand.LEFT, role="accompaniment"),
        _ev(52, 1.0, 1.0, hand=Hand.LEFT, role="accompaniment"),
        _ev(55, 1.0, 1.0, hand=Hand.LEFT, role="accompaniment"),
    ]
    out = VoiceSeparator().separate(events)
    rh = [e for e in out if e.hand == Hand.RIGHT]
    lh = [e for e in out if e.hand == Hand.LEFT]
    assert len({e.voice for e in rh}) == 1
    assert len({e.voice for e in lh}) == 1


def test_sustained_bass_plus_melody():
    events = [
        _ev(36, 0.0, 4.0, hand=Hand.LEFT, role="bass"),
        _ev(64, 0.0, 1.0, role="melody"),
        _ev(65, 1.0, 1.0, role="melody"),
        _ev(67, 2.0, 1.0, role="melody"),
        _ev(69, 3.0, 1.0, role="melody"),
    ]
    out = VoiceSeparator().separate(events)
    assert len({(e.hand, e.voice) for e in out}) == 2


def test_polyphonic_right_hand():
    events = [
        _ev(60, 0.0, 4.0, role="accompaniment"),
        _ev(76, 0.0, 1.0, role="melody"),
        _ev(77, 1.0, 1.0, role="melody"),
        _ev(79, 2.0, 1.0, role="melody"),
        _ev(81, 3.0, 1.0, role="melody"),
    ]
    out = VoiceSeparator().separate(events)
    voices = {e.voice for e in out}
    assert len(voices) == 2
    held = next(e for e in out if e.pitch == 60)
    tops = [e for e in out if e.pitch >= 76]
    assert all(e.voice != held.voice for e in tops)


def test_voice_crossing_streams():
    events = [
        _ev(67, 0.0, 1.0),
        _ev(60, 0.0, 1.0),
        _ev(64, 1.0, 1.0),
        _ev(62, 1.0, 1.0),
        _ev(60, 2.0, 1.0),
        _ev(64, 2.0, 1.0),
    ]
    out = VoiceSeparator().separate(events)
    assert len({e.voice for e in out}) >= 2


def test_compact_chord_is_one_voice():
    events = [_ev(60, 0.0, 1.0), _ev(64, 0.0, 1.0), _ev(67, 0.0, 1.0)]
    out = VoiceSeparator().separate(events)
    assert len({e.voice for e in out}) == 1
