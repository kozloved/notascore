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
