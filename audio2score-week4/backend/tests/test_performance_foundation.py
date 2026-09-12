"""Reference-MIDI acceptance cases; expected rhythms are specified independently."""

from dataclasses import FrozenInstanceError
import json

import pretty_midi
import pytest
from music21 import converter

from evaluation.stage_gate import evaluate
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.performance_cli import convert
from mir.performance import PerformanceSnapshot
from mir.types import Hand


def midi_file(path, notes, program=0, meter=(4, 4), jitter=0.0):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120, resolution=960)
    inst = pretty_midi.Instrument(program, name="Source")
    inst.notes = [pretty_midi.Note(83, p, (s + jitter) / 2, (s + d + jitter) / 2)
                  for p, s, d in notes]
    midi.instruments.append(inst)
    midi.time_signature_changes.append(pretty_midi.TimeSignature(*meter, 0))
    midi.write(str(path))
    return path


CASES = [
    ("flute_short_rests", 73, (4, 4), [(72, 0, .25), (74, .5, .25), (76, 1, .5), (77, 2, 1)]),
    ("cello_barline", 42, (4, 4), [(48, 0, 1), (50, 3, 6)]),
    ("piano_polyphony", 0, (4, 4), [(48, 0, 4), (72, 0, 1), (74, 1, 1), (76, 2, 1), (77, 3, 1)]),
    ("piano_same_pitch_overlap", 0, (4, 4), [(72, 0, 3), (72, 1, 1), (74, 3, 1)]),
    ("flute_triplets", 73, (4, 4), [(72 + i % 3, i / 3, 1 / 3) for i in range(12)]),
    ("piano_compound", 0, (6, 8), [(60, 0, 1.5), (64, 1.5, 1.5)]),
    ("violin_chord", 40, (3, 4), [(60, 0, 1), (64, 0, 1), (67, 1, 1), (69, 2, 1)]),
]


@pytest.mark.parametrize("name,program,meter,notes", CASES, ids=[c[0] for c in CASES])
def test_solo_reference_gate(tmp_path, name, program, meter, notes):
    source = midi_file(tmp_path / "input.mid", notes, program, meter, jitter=.008)
    reference = midi_file(tmp_path / "reference.mid", notes, program, meter)
    result = evaluate(source, reference, tmp_path / "gate", onset_floor=1, offset_floor=1)
    assert result["passed"], result
    score = converter.parse(tmp_path / "gate" / "score.musicxml")
    assert len(score.parts) == (2 if program == 0 else 1)
    assert int(score.parts[0].getInstrument().midiProgram) == program


def test_snapshot_retains_short_notes_controllers_drums_and_identity(tmp_path):
    path = midi_file(tmp_path / "source.mid", [(72, 0, .002), (72, 0, 1)])
    midi = pretty_midi.PrettyMIDI(str(path))
    midi.instruments[0].control_changes.append(pretty_midi.ControlChange(11, 91, .2))
    midi.instruments[0].pitch_bends.append(pretty_midi.PitchBend(256, .3))
    drums = pretty_midi.Instrument(0, is_drum=True)
    drums.notes.append(pretty_midi.Note(99, 36, 0, .5))
    midi.instruments.append(drums)
    midi.write(str(path))
    raw = path.read_bytes()
    ingested = ingest_midi(path)
    snapshot = ingested.performance
    assert len(snapshot.notes) == 3 and len(ingested.notes) == 2
    assert min(n.duration for n in ingested.notes) < .01
    events = notes_to_events(ingested.notes, ingested.tempo_map)
    assert min(e.duration_beats for e in events) < .01
    assert len({e.note_id for e in events}) == 2
    assert snapshot.tracks[0].controls[0][1:] == (11, 91)
    assert snapshot.tracks[0].pitch_bends[0][1] == 256
    with pytest.raises(FrozenInstanceError):
        ingested.notes[0].pitch = 1
    with pytest.raises(FrozenInstanceError):
        snapshot.notes[0].pitch = 2
    snapshot.verify_midi(raw)
    snapshot.write_json(tmp_path / "snapshot.json")
    assert PerformanceSnapshot.read_json(tmp_path / "snapshot.json") == snapshot
    with pytest.raises(ValueError, match="checksum"):
        snapshot.verify_midi(raw + b"changed")
    assert path.read_bytes() == raw


def test_cli_emits_distinct_score_midi_and_provenance(tmp_path):
    source = midi_file(tmp_path / "source.mid", [(72, 0, 1)], program=73)
    convert(source, tmp_path / "score.musicxml")
    snapshot = json.loads((tmp_path / "score.performance.json").read_text())
    assert snapshot["source_backend"] == "midi"
    assert snapshot["notes"][0]["program"] == 73
    midi = pretty_midi.PrettyMIDI(str(tmp_path / "score.score.mid"))
    assert midi.instruments[0].program == 73
    # Protect against a sidecar overwriting the source, too.
    with pytest.raises(ValueError, match="source MIDI"):
        convert(tmp_path / "score.score.mid", tmp_path / "score.musicxml")


def test_tempo_changes_survive_interpretation_and_score_midi(tmp_path):
    import mido
    source = tmp_path / "tempo.mid"
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend([
        mido.Message("program_change", program=73),
        mido.MetaMessage("set_tempo", tempo=500000),
        mido.MetaMessage("time_signature", numerator=4, denominator=4),
        mido.Message("note_on", note=72, velocity=83),
        mido.Message("note_off", note=72, time=480),
        mido.MetaMessage("set_tempo", tempo=1000000),
        mido.Message("note_on", note=74, velocity=83),
        mido.Message("note_off", note=74, time=480),
    ])
    midi.save(source)
    convert(source, tmp_path / "tempo.musicxml")
    snapshot = PerformanceSnapshot.read_json(tmp_path / "tempo.performance.json")
    assert snapshot.tempo_changes == ((0.0, 120.0), (0.5, 60.0))
    score_midi = ingest_midi(tmp_path / "tempo.score.mid")
    assert [(n.start_time, n.end_time) for n in score_midi.notes] == [(0.0, .5), (.5, 1.5)]


def test_derived_midi_keeps_programs_and_does_not_lengthen_short_notes(tmp_path):
    from mir.raw_midi import write_notes_to_midi
    source = midi_file(tmp_path / "source.mid", [(72, 0, .01)], program=73)
    notes = ingest_midi(source).notes
    output = tmp_path / "derived.mid"
    write_notes_to_midi(notes, output, split_hands=False)
    derived = ingest_midi(output)
    assert derived.notes[0].source_program == 73
    assert derived.notes[0].duration < .01


def test_solo_pipeline_never_assigns_piano_hands(tmp_path, monkeypatch):
    from mir.pipeline import UnderstandingPipeline
    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
    source = midi_file(tmp_path / "source.mid", [(48, 0, 1), (52, 1, 1)], program=42)
    pipeline = UnderstandingPipeline()
    xml = pipeline.transcribe_midi(source, "solo")
    assert "<staves>2</staves>" not in xml
    assert all(e.hand == Hand.UNKNOWN for e in pipeline.last_quantized_events)
    assert (tmp_path / "bp_solo" / "solo.raw.mid").read_bytes() == source.read_bytes()


def test_ensemble_is_explicitly_unvalidated_not_collapsed_to_piano(tmp_path):
    source = midi_file(tmp_path / "mixed.mid", [(60, 0, 1)])
    midi = pretty_midi.PrettyMIDI(str(source))
    flute = pretty_midi.Instrument(73)
    flute.notes.append(pretty_midi.Note(80, 72, 0, .5))
    midi.instruments.append(flute)
    midi.write(str(source))
    result = evaluate(source, source, tmp_path / "gate")
    assert not result["passed"]
    assert "Ensemble" in result["error"]
    assert result["checks"]["source_bytes_unchanged"]


def test_transcription_gate_catches_wrong_instrument_and_missing_notes(tmp_path):
    truth = midi_file(tmp_path / "truth.mid", [(72, 0, 1), (74, 1, 1)], program=73)
    wrong = midi_file(tmp_path / "wrong.mid", [(72, 0, 1), (74, 1, 1)], program=0)
    result = evaluate(wrong, truth, tmp_path / "wrong-out", stage="transcription")
    assert result["reference_metrics"]["onset_pitch_f1"] == 1
    assert not result["passed"] and not result["checks"]["instrument_onsets"]
    missing = midi_file(tmp_path / "missing.mid", [(72, 0, 1)], program=73)
    assert not evaluate(missing, truth, tmp_path / "missing-out", stage="transcription")["passed"]
    assert evaluate(truth, truth, tmp_path / "good-out", stage="transcription")["passed"]
