import pretty_midi
import pytest
from music21 import note, stream, tie

from evaluation.score_ab import compare_case, discover, exported_notes
from mir.types import TempoMap


def test_comparison_evaluates_export_and_leaves_midi_unchanged(tmp_path):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    instrument = pretty_midi.Instrument(0)
    instrument.notes = [pretty_midi.Note(80, 72 + i, i * 0.5, (i + 1) * 0.5) for i in range(4)]
    midi.instruments.append(instrument)
    source, reference = tmp_path / "input.mid", tmp_path / "reference.mid"
    midi.write(str(source))
    midi.write(str(reference))
    before = source.read_bytes(), reference.read_bytes()
    assert list(discover(tmp_path)) == [(source, reference)]
    rows = compare_case(source, reference, tmp_path / "out")
    assert {r["mode"] for r in rows} == {"adaptive", "performance"}
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["reference_metrics"]["onset_pitch_offset_f1"] == 1 for r in rows)
    assert all(r["export_preservation"]["onset_pitch_offset_f1"] == 1 for r in rows)
    assert before == (source.read_bytes(), reference.read_bytes())


def test_exported_ties_are_joined_without_collapsing_repeated_attacks(tmp_path):
    score, part = stream.Score(), stream.Part()
    for index in range(2):
        measure = stream.Measure(number=index + 1)
        voice = stream.Voice(id="1")
        n = note.Note(72, quarterLength=4)
        n.tie = tie.Tie("start" if index == 0 else "stop")
        voice.append(n)
        measure.insert(0, voice)
        part.append(measure)
    measure = stream.Measure(number=3)
    measure.append(note.Note(72, quarterLength=1))
    part.append(measure)
    score.insert(0, part)
    path = tmp_path / "tied.musicxml"
    score.write("musicxml", fp=str(path))
    notes = exported_notes(path, TempoMap())
    assert len(notes) == 2
    assert notes[0].start_time == 0
    assert notes[0].end_time == 4
    assert notes[1].start_time == 4


def test_exported_orphan_tie_is_an_error(tmp_path):
    score = stream.Score()
    part = stream.Part()
    measure = stream.Measure(number=1)
    n = note.Note(72, quarterLength=1)
    n.tie = tie.Tie("stop")
    measure.append(n)
    part.append(measure)
    score.insert(0, part)
    path = tmp_path / "orphan.musicxml"
    score.write("musicxml", fp=str(path), makeNotation=False)
    with pytest.raises(ValueError, match="Orphan"):
        exported_notes(path, TempoMap())
