import json

import pretty_midi
from music21 import converter

from mir.performance_cli import convert


def test_midi_conversion_preserves_source_and_exports_score(tmp_path):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    piano = pretty_midi.Instrument(0)
    piano.notes = [pretty_midi.Note(80, 72 + i, i / 4, (i + 1) / 4)
                   for i in range(8)]
    midi.instruments.append(piano)
    source = tmp_path / "mt3.mid"
    midi.write(str(source))
    original = source.read_bytes()
    output = tmp_path / "score.musicxml"
    report = convert(source, output, "4/4")
    assert source.read_bytes() == original
    score = converter.parse(output)
    assert sum(len(part.flatten().notes) for part in score.parts) == 8
    decisions = json.loads(report.read_text())
    assert decisions["quantization_summary"]["engine"] == "performance"
    assert len(decisions["quantization_decisions"]) == 8



def test_cli_preserves_subbeat_playback_tempo_when_printing_is_off(tmp_path):
    import mido
    import pytest
    from mir.midi_ingest import ingest_midi

    source = tmp_path / "rubato.mid"
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend([
        mido.MetaMessage("set_tempo", tempo=500000),
        mido.Message("program_change", program=73),
        mido.Message("note_on", note=72, velocity=81),
        mido.MetaMessage("set_tempo", tempo=1000000, time=240),
        mido.Message("note_off", note=72, time=240),
        mido.Message("note_on", note=74, velocity=75),
        mido.Message("note_off", note=74, time=480),
    ])
    midi.save(source)
    original = source.read_bytes()
    convert(source, tmp_path / "rubato.musicxml", "4/4", settings={
        "printed_tempo_detail": "off", "interpretation": "literal",
    })
    notes = ingest_midi(tmp_path / "rubato.score.mid").notes
    assert source.read_bytes() == original
    assert len(notes) == 2
    assert [(n.pitch, n.velocity, n.source_program) for n in notes] == [
        (72, 81, 73), (74, 75, 73),
    ]
    for note, expected in zip(notes, [(0, .75), (.75, 1.75)]):
        assert (note.start_time, note.end_time) == pytest.approx(expected, abs=.002)
    context = json.loads((tmp_path / "rubato.interpretation_context.json").read_text())
    assert context["playback_tempo"] == [
        {"beat": 0.0, "bpm": 120.0}, {"beat": .5, "bpm": 60.0},
    ]


def test_cli_ties_do_not_create_attacks_and_repeats_still_do(tmp_path):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    piano = pretty_midi.Instrument(0)
    piano.notes = [pretty_midi.Note(80, 72, 0, 3),
                   pretty_midi.Note(75, 72, 3, 3.5)]
    midi.instruments.append(piano)
    source = tmp_path / "held.mid"
    midi.write(str(source))
    convert(source, tmp_path / "held.musicxml", "4/4", settings={"interpretation": "literal"})
    exported = pretty_midi.PrettyMIDI(str(tmp_path / "held.score.mid"))
    notes = [n for inst in exported.instruments for n in inst.notes]
    assert [(n.pitch, n.start, n.end) for n in notes] == [(72, 0, 3), (72, 3, 3.5)]
