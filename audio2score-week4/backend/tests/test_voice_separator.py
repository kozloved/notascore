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


def test_repeated_note_stays_one_voice():
    events = [_ev(72, float(i), 0.5) for i in range(8)]
    out = VoiceSeparator().separate(events)
    assert len({e.voice for e in out}) == 1


def test_two_independent_lines_are_two_voices():
    events = []
    for i in range(4):
        events.append(_ev(76, float(i), 1.0, role="melody"))
        events.append(_ev(60, float(i), 1.0, role="inner"))
    out = VoiceSeparator().separate(events)
    assert len({e.voice for e in out}) == 2


def test_tiny_release_overlap_does_not_create_a_voice():
    from mir.performance_score import _score_voices

    events = [
        _ev(72, 0.0, 1.05),
        _ev(74, 1.0, 1.0),
        _ev(76, 2.0, 1.0),
    ]
    out = _score_voices(events, VoiceSeparator())
    assert len({e.voice for e in out}) == 1


def test_mixed_release_chord_splits_the_held_note():
    events = [
        _ev(60, 0.0, 1.0, role="accompaniment"),
        _ev(64, 0.0, 1.0, role="accompaniment"),
        _ev(67, 0.0, 4.0, role="melody"),
    ]
    out = VoiceSeparator().separate(events)
    held = next(e for e in out if e.pitch == 67)
    body = [e for e in out if e.pitch != 67]
    assert held.voice != body[0].voice
    assert body[0].voice == body[1].voice


def test_broken_chord_under_melody_keeps_two_lines():
    events = [
        _ev(76, 0.0, 4.0, role="melody"),
        _ev(48, 0.0, 0.5, hand=Hand.RIGHT, role="accompaniment"),
        _ev(52, 0.5, 0.5, hand=Hand.RIGHT, role="accompaniment"),
        _ev(55, 1.0, 0.5, hand=Hand.RIGHT, role="accompaniment"),
        _ev(60, 1.5, 0.5, hand=Hand.RIGHT, role="accompaniment"),
        _ev(48, 2.0, 0.5, hand=Hand.RIGHT, role="accompaniment"),
        _ev(52, 2.5, 0.5, hand=Hand.RIGHT, role="accompaniment"),
        _ev(55, 3.0, 0.5, hand=Hand.RIGHT, role="accompaniment"),
        _ev(60, 3.5, 0.5, hand=Hand.RIGHT, role="accompaniment"),
    ]
    out = VoiceSeparator().separate(events)
    held = next(e for e in out if e.pitch == 76)
    broken = [e for e in out if e.pitch != 76]
    assert all(e.voice != held.voice for e in broken)
    assert len({e.voice for e in broken}) == 1


def test_crossing_lines_use_lookahead_continuity():
    from mir.voice_separator import extra_printed_lanes, fragmentation_count, permutation_invariant_accuracy

    events = []
    # Upper line: 79, 76, 72, 67 (descending)
    # Lower line: 60, 64, 67, 72 (ascending) — they cross.
    upper = [79, 76, 72, 67]
    lower = [60, 64, 67, 72]
    for i, (u, lo) in enumerate(zip(upper, lower)):
        events.append(
            MusicalEvent(
                u, float(i), 1.0, hand=Hand.RIGHT, role="melody",
                note_id=f"u{i}", velocity=80, musical_voice=0,
            )
        )
        events.append(
            MusicalEvent(
                lo, float(i), 1.0, hand=Hand.RIGHT, role="inner",
                note_id=f"l{i}", velocity=70, musical_voice=1,
            )
        )
    out = VoiceSeparator().separate(events)
    by_id = {e.note_id: e for e in out}
    pred = [by_id[e.note_id].voice for e in events]
    truth = [e.musical_voice for e in events]
    assert permutation_invariant_accuracy(pred, truth) >= 0.75
    assert fragmentation_count(out, truth_attr="musical_voice") <= 2
    assert extra_printed_lanes(pred, truth) <= 1


def test_user_voice_labels_are_respected():
    events = [
        MusicalEvent(
            76, 0.0, 1.0, hand=Hand.RIGHT, voice=3, voice_assigned=True,
            voice_provenance="user_edit", note_id="a", velocity=80,
        ),
        MusicalEvent(
            60, 0.0, 1.0, hand=Hand.RIGHT, voice=1, voice_assigned=True,
            voice_provenance="user_edit", note_id="b", velocity=80,
        ),
        MusicalEvent(64, 1.0, 1.0, hand=Hand.RIGHT, note_id="c", velocity=80),
    ]
    out = VoiceSeparator().separate(events)
    by_id = {e.note_id: e.voice for e in out}
    assert by_id["a"] == 3
    assert by_id["b"] == 1


def test_voice_limit_keeps_every_note_and_records_diagnostics():
    from mir.voice_separator import VoiceSeparatorConfig

    events = []
    for lane, pitch in enumerate((48, 55, 62, 69, 76)):
        events.append(
            MusicalEvent(
                pitch, 0.0, 4.0, hand=Hand.RIGHT, note_id=f"n{lane}", velocity=80,
            )
        )
    sep = VoiceSeparator(VoiceSeparatorConfig(max_voices_per_hand=2, max_chord_span=3, split_gap=4))
    out = sep.separate(events)
    assert len(out) == 5
    assert {e.note_id for e in out} == {e.note_id for e in events}
    assert all(e.duration_beats == 4.0 for e in out)
    assert len({e.voice for e in out}) >= 2
    if len({e.voice for e in out}) > 2:
        assert any(row["kind"] == "voice_limit_exceeded" for row in sep.last_diagnostics)

