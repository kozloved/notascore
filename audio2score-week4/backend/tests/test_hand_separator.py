"""Hand separation: context-aware Viterbi, not a middle-C gate."""

from mir.cmr_builder import notes_to_events
from mir.hand_separator import HandSeparator, RegisterSplitHandSeparator
from mir.pipeline import UnderstandingPipeline
from mir.types import (
    Hand,
    InstrumentKind,
    MusicalEvent,
    MusicalRole,
    NoteEvent,
    TempoMap,
    TempoPoint,
)


def _ev(pitch, start, dur=0.5, role=None, velocity=80, hand=Hand.UNKNOWN, hand_locked=False):
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        velocity=velocity,
        role=role,
        hand=hand,
        hand_locked=hand_locked,
        hand_confidence=1.0 if hand != Hand.UNKNOWN else 0.0,
    )


def test_simple_two_hand_piano_texture():
    events = []
    for i in range(8):
        events.append(_ev(48 + i, float(i), role="bass"))
        events.append(_ev(72 + i, float(i), role="melody"))
    out = HandSeparator().separate(events)
    low = [e for e in out if e.pitch < 60]
    high = [e for e in out if e.pitch >= 72]
    assert all(e.hand == Hand.LEFT for e in low)
    assert all(e.hand == Hand.RIGHT for e in high)
    assert all(e.hand != Hand.UNKNOWN for e in out)


def test_melody_below_middle_c_is_right_hand():
    events = []
    melody = [64, 62, 60, 59, 57, 55]
    bass = [36, 38, 40, 41, 43, 45]
    for i, (m, b) in enumerate(zip(melody, bass)):
        events.append(_ev(b, float(i), role="bass"))
        events.append(_ev(m, float(i), role="melody"))
    out = HandSeparator().separate(events)
    for e in out:
        if e.role == "melody":
            assert e.hand == Hand.RIGHT, (e.pitch, e.hand)
        if e.role == "bass":
            assert e.hand == Hand.LEFT, (e.pitch, e.hand)
    below = [e for e in out if e.role == "melody" and e.pitch < 60]
    assert below
    assert all(e.hand == Hand.RIGHT for e in below)


def test_bass_above_middle_c_is_left_hand():
    events = []
    bass = [48, 52, 55, 60, 62, 64]
    melody = [72, 74, 76, 77, 79, 81]
    for i, (b, m) in enumerate(zip(bass, melody)):
        events.append(_ev(b, float(i), role="bass"))
        events.append(_ev(m, float(i), role="melody"))
    out = HandSeparator().separate(events)
    for e in out:
        if e.role == "bass":
            assert e.hand == Hand.LEFT, (e.pitch, e.hand)
        if e.role == "melody":
            assert e.hand == Hand.RIGHT, (e.pitch, e.hand)
    above = [e for e in out if e.role == "bass" and e.pitch >= 60]
    assert above
    assert all(e.hand == Hand.LEFT for e in above)


def test_chord_spanning_middle_c_stays_on_one_hand():
    events = [
        _ev(55, 0.0, dur=1.0),
        _ev(60, 0.0, dur=1.0),
        _ev(64, 0.0, dur=1.0),
        _ev(36, 0.0, dur=1.0, role="bass"),
        _ev(76, 0.0, dur=1.0, role="melody"),
    ]
    out = HandSeparator().separate(events)
    chord_hands = {e.hand for e in out if e.pitch in (55, 60, 64)}
    assert len(chord_hands) == 1
    assert Hand.UNKNOWN not in chord_hands
    assert next(e for e in out if e.pitch == 36).hand == Hand.LEFT
    assert next(e for e in out if e.pitch == 76).hand == Hand.RIGHT


def test_wide_left_hand_accompaniment():
    events = []
    lh = [36, 43, 48, 55, 60]
    for beat in range(4):
        for j, p in enumerate(lh):
            events.append(_ev(p, beat + j * 0.2, dur=0.2, role="accompaniment"))
        events.append(_ev(72 + (beat % 3), float(beat), dur=1.0, role="melody"))
    out = HandSeparator().separate(events)
    accomp = [e for e in out if e.role == "accompaniment"]
    melody = [e for e in out if e.role == "melody"]
    assert all(e.hand == Hand.RIGHT for e in melody)
    left = [e for e in accomp if e.hand == Hand.LEFT]
    assert len(left) >= int(0.8 * len(accomp))
    sixty = [e for e in accomp if e.pitch == 60]
    assert sixty
    assert sum(1 for e in sixty if e.hand == Hand.LEFT) >= len(sixty) - 1


def test_wide_right_hand_arpeggio():
    arp = [60, 64, 67, 72, 76, 79, 84]
    events = []
    for beat in range(2):
        events.append(_ev(36, float(beat), dur=1.0, role="bass"))
        for j, p in enumerate(arp):
            events.append(_ev(p, beat + j * 0.125, dur=0.12, role="melody"))
    out = HandSeparator().separate(events)
    assert all(e.hand == Hand.LEFT for e in out if e.pitch == 36)
    arp_notes = [e for e in out if e.pitch in arp]
    assert all(e.hand == Hand.RIGHT for e in arp_notes), [
        (e.pitch, e.hand) for e in arp_notes if e.hand != Hand.RIGHT
    ]


def test_hand_crossing_contrary_motion():
    events = []
    rh = [72, 71, 69, 67, 65, 64, 62, 60, 59, 57]
    lh = [48, 50, 52, 53, 55, 57, 59, 60, 62, 64]
    for i, (a, b) in enumerate(zip(lh, rh)):
        events.append(_ev(a, float(i), role="bass"))
        events.append(_ev(b, float(i), role="melody"))
    out = HandSeparator().separate(events)
    last = [e for e in out if e.start_beat == 9.0]
    hands = {e.pitch: e.hand for e in last}
    assert hands[64] == Hand.LEFT
    assert hands[57] == Hand.RIGHT


def test_repeated_melodic_line_does_not_switch_hands():
    events = []
    figure = [60, 62, 64, 62]
    for i in range(8):
        events.append(_ev(36 + (i % 3), float(i), role="bass"))
        events.append(_ev(figure[i % 4], float(i), role="melody"))
    out = HandSeparator().separate(events)
    melody = [e for e in out if e.role == "melody"]
    hands = {e.hand for e in melody}
    assert hands == {Hand.RIGHT}
    assert all(e.hand == Hand.LEFT for e in out if e.role == "bass")


def test_octave_doubling_stays_with_each_hand():
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
    assert all(e.hand == Hand.LEFT for e in out if e.pitch in (36, 48))
    assert all(e.hand == Hand.RIGHT for e in out if e.pitch in (60, 72))


def test_ambiguous_isolated_middle_register():
    sep = HandSeparator()
    out = sep.separate([_ev(60, 0.0)])
    assert out[0].hand == Hand.AMBIGUOUS
    assert out[0].hand_confidence <= 0.45
    assert sep.last_decisions
    decision = sep.last_decisions[0]
    assert decision.selected == "ambiguous"
    assert "register" in decision.factors
    assert decision.competing_hand in ("left", "right")


def test_same_pitch_depends_on_surrounding_context():
    melody_ctx = []
    for i in range(4):
        melody_ctx.append(_ev(48, float(i), role="bass"))
        melody_ctx.append(_ev(60, float(i), role="melody"))
    as_melody = next(e for e in HandSeparator().separate(melody_ctx) if e.pitch == 60)

    chord_ctx = []
    for i in range(4):
        chord_ctx.extend(
            [
                _ev(36, float(i), role="bass"),
                _ev(48, float(i), role="accompaniment"),
                _ev(55, float(i), role="accompaniment"),
                _ev(60, float(i), role="accompaniment"),
                _ev(76, float(i), role="melody"),
            ]
        )
    as_inner = next(e for e in HandSeparator().separate(chord_ctx) if e.pitch == 60)
    assert as_melody.hand == Hand.RIGHT
    assert as_inner.hand == Hand.LEFT


def test_roles_are_hints_not_preassigned_hands():
    """CMR used to copy melody→RH / bass→LH before the separator, which then skipped."""
    events = []
    for i, pitch in enumerate([64, 62, 60, 59, 57, 55]):
        events.append(
            _ev(
                pitch,
                float(i),
                role="melody",
                hand=Hand.LEFT,
                hand_locked=False,
            )
        )
        events.append(_ev(36 + i, float(i), role="bass", hand=Hand.LEFT))
    out = HandSeparator().separate(events)
    melody = [e for e in out if e.role == "melody"]
    assert all(e.hand == Hand.RIGHT for e in melody), [(e.pitch, e.hand) for e in melody]


def test_hand_locked_is_the_only_skip():
    isolated = HandSeparator().separate([_ev(60, 0.0)])
    assert isolated[0].hand == Hand.AMBIGUOUS
    locked = _ev(60, 0.0, hand=Hand.LEFT, hand_locked=True)
    out = HandSeparator().separate([locked])
    assert out[0].hand == Hand.LEFT
    assert out[0].hand_confidence >= 0.95


def test_roles_do_not_pre_populate_hands_in_cmr():
    notes = [
        NoteEvent(pitch=55, start_time=0.0, end_time=0.5),
        NoteEvent(pitch=36, start_time=0.0, end_time=0.5),
    ]
    role = MusicalRole(
        melody_notes=[notes[0]],
        bass_notes=[notes[1]],
        confidence=0.9,
    )
    tm = TempoMap(points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0)])
    events = notes_to_events(notes, tm, role=role, instrument=InstrumentKind.PIANO)
    assert {e.role for e in events} == {"melody", "bass"}
    assert all(e.hand == Hand.UNKNOWN for e in events)
    assert all(e.hand_locked is False for e in events)


def test_pipeline_uses_context_aware_separator():
    pipeline = UnderstandingPipeline()
    assert type(pipeline.hand_separator) is HandSeparator
    assert not hasattr(pipeline.hand_separator, "SPLIT_PITCH")


def test_legacy_split_still_available():
    events = [_ev(59, 0.0), _ev(60, 0.0)]
    out = RegisterSplitHandSeparator().separate(events)
    assert next(e for e in out if e.pitch == 59).hand == Hand.LEFT
    assert next(e for e in out if e.pitch == 60).hand == Hand.RIGHT


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
