import mido
import pretty_midi
import pytest

from mir.models import MeterHypothesis
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent


def test_exact_short_offbeats_and_overlapping_sustains_survive():
    events = [
        MusicalEvent(60 + i, start, duration, note_id=str(i),
                     hand=Hand.RIGHT, source_backend="midi")
        for i, (start, duration) in enumerate([
            (0.0625, 0.9375), (0.5, 0.5), (1.0625, 0.0625),
        ])
    ]
    quantizer = MeasureQuantizer(mode="performance")
    output, _ = quantizer.quantize(events, MeterHypothesis("4/4", 4, 4, 4, 1, 1))
    assert {e.note_id: (e.start_beat, e.duration_beats) for e in output} == {
        e.note_id: (e.start_beat, e.duration_beats) for e in events
    }


def test_midi_subbeat_tempo_changes_survive_pipeline_and_export(tmp_path, monkeypatch):
    from mir.pipeline import UnderstandingPipeline
    from mir.raw_midi import job_score_midi_path

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")

    source = tmp_path / "rubato.mid"
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend([
        mido.MetaMessage("set_tempo", tempo=500000),
        mido.MetaMessage("time_signature", numerator=4, denominator=4),
        mido.Message("note_on", note=60, velocity=80, time=120),
        mido.MetaMessage("set_tempo", tempo=700000, time=120),
        mido.Message("note_off", note=60, time=240),
        mido.Message("note_on", note=64, velocity=80),
        mido.MetaMessage("set_tempo", tempo=720000, time=120),
        mido.Message("note_off", note=64, time=360),
    ])
    midi.save(source)
    pipe = UnderstandingPipeline()
    pipe.transcribe_midi(source, "fidelity")
    assert pipe.notation.last_quantization_mode.value == "performance"
    assert pipe.notation.last_export_integrity["status"] == "passed"
    events = sorted(pipe.last_quantized_events, key=lambda e: e.start_beat)
    assert [e.start_beat for e in events] == pytest.approx([0.25, 1.0])
    assert [e.duration_beats for e in events] == pytest.approx([0.75, 1.0])
    original = pretty_midi.PrettyMIDI(str(source))
    exported = pretty_midi.PrettyMIDI(str(job_score_midi_path(source, "fidelity")))
    before = sorted((n.pitch, n.start, n.end) for inst in original.instruments for n in inst.notes)
    after = sorted((n.pitch, n.start, n.end) for inst in exported.instruments for n in inst.notes)
    assert len(after) == len(before)
    for actual, expected in zip(after, before):
        assert actual == pytest.approx(expected, abs=0.002)
