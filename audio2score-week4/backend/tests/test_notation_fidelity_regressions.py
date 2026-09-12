from fractions import Fraction

import pretty_midi
import pytest
from music21 import converter

from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.writer import NotationWriter


def event(pitch, start, duration, velocity=80):
    return MusicalEvent(pitch, start, duration, velocity=velocity,
                        note_id=f"{pitch}:{start}", hand=Hand.RIGHT,
                        source_backend="midi")


def exported_notes(tmp_path, events, meta, job):
    writer = NotationWriter()
    xml = writer.write_musicxml(events, meta, job, tmp_path / "source.mid")
    midi = pretty_midi.PrettyMIDI(str(tmp_path / f"bp_{job}" / f"{job}.score.mid"))
    notes = sorted((n for inst in midi.instruments for n in inst.notes),
                   key=lambda n: (n.start, n.pitch))
    return writer, xml, notes


def test_playback_uses_rubato_without_cluttering_printed_score(tmp_path):
    beats = [0, 0.5, 1.2, 2.1, 2.7]
    meta = ScoreMeta(time_sig_hint="4/4", display_tempo_bpm=120, extra={
        "printed_tempo": [{"beat": 0, "bpm": 120}],
        "playback_tempo": [{"beat": i, "bpm": 60 / (b - a)}
                           for i, (a, b) in enumerate(zip(beats, beats[1:]))],
    })
    _, xml, notes = exported_notes(
        tmp_path, [event(60 + i, i, 1) for i in range(4)], meta, "rubato")
    assert [n.start for n in notes] == pytest.approx(beats[:-1], abs=0.002)
    assert [n.end for n in notes] == pytest.approx(beats[1:], abs=0.002)
    assert xml.count("<metronome") == 1


def test_tied_chord_keeps_each_source_velocity(tmp_path):
    _, _, notes = exported_notes(tmp_path, [event(60, 3, 2, 35), event(67, 3, 2, 105)],
                                ScoreMeta(time_sig_hint="4/4"), "dynamics")
    assert [(n.pitch, n.velocity) for n in notes] == [(60, 35), (67, 105)]
    assert [n.end - n.start for n in notes] == pytest.approx([1, 1])


@pytest.mark.parametrize("denominator", [12, 24, 48])
def test_fast_triplets_preserve_attacks_and_duration(tmp_path, denominator):
    events = [event(60 + i, i / denominator, 1 / denominator) for i in range(6)]
    _, xml, notes = exported_notes(tmp_path, events, ScoreMeta(time_sig_hint="4/4"),
                                       f"triplets{denominator}")
    parsed = converter.parseData(xml)
    pitched = list(parsed.parts[0].flatten().notes)
    assert len(notes) == len(pitched) == len(events)
    assert [n.offset for n in pitched] == [Fraction(i, denominator) for i in range(6)]
    assert all(n.quarterLength == Fraction(1, denominator) for n in pitched)
