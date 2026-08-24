"""Tests for MIDI-file ingest into CMR."""

from __future__ import annotations

import pretty_midi

from mir.midi_ingest import hand_from_track_name, ingest_midi, is_midi_path
from mir.pipeline import UnderstandingPipeline
from mir.types import Hand
from transcription import BasicPitchEngine, FallbackEngine, get_engine


def _piano_midi(path, tempo=96.0):
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    rh = pretty_midi.Instrument(program=0, name="RH")
    lh = pretty_midi.Instrument(program=0, name="LH")
    rh.notes.append(pretty_midi.Note(velocity=80, pitch=72, start=0.0, end=0.5))
    rh.notes.append(pretty_midi.Note(velocity=80, pitch=76, start=0.0, end=0.5))
    lh.notes.append(pretty_midi.Note(velocity=70, pitch=48, start=0.0, end=2.0))
    lh.control_changes.append(pretty_midi.ControlChange(number=64, value=127, time=0.1))
    lh.control_changes.append(pretty_midi.ControlChange(number=64, value=0, time=1.6))
    midi.instruments.extend([rh, lh])
    midi.time_signature_changes.append(
        pretty_midi.TimeSignature(numerator=3, denominator=4, time=0.0)
    )
    midi.write(str(path))
    return path


def test_is_midi_path():
    assert is_midi_path("clip.mid")
    assert is_midi_path("clip.MIDI")
    assert not is_midi_path("clip.wav")


def test_hand_from_track_name():
    assert hand_from_track_name("RH") == Hand.RIGHT
    assert hand_from_track_name("Piano LH") == Hand.LEFT
    assert hand_from_track_name("Right Hand") == Hand.RIGHT
    assert hand_from_track_name("Piano") == Hand.UNKNOWN


def test_ingest_midi_reads_notes_tempo_pedal_hands(tmp_path):
    path = _piano_midi(tmp_path / "piano.mid", tempo=96.0)
    ingested = ingest_midi(path)
    assert len(ingested.notes) == 3
    hands = {n.hand for n in ingested.notes}
    assert Hand.RIGHT in hands and Hand.LEFT in hands
    assert abs(ingested.tempo_map.bpm_at(0.0) - 96.0) < 1.0
    assert ingested.time_sig_hint == "3/4"
    assert any(value == 127 for _, value in ingested.pedal_events)


def test_ingest_skips_drum_tracks(tmp_path):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    drums = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
    drums.notes.append(pretty_midi.Note(velocity=100, pitch=36, start=0.0, end=0.2))
    piano = pretty_midi.Instrument(program=0, name="Piano")
    piano.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5))
    midi.instruments.extend([drums, piano])
    path = tmp_path / "mixed.mid"
    midi.write(str(path))
    ingested = ingest_midi(path)
    assert len(ingested.notes) == 1
    assert ingested.notes[0].pitch == 60


def test_understanding_pipeline_ingests_midi(tmp_path):
    path = _piano_midi(tmp_path / "job.mid")
    xml = UnderstandingPipeline().transcribe(path, "midi-ingest")
    lower = xml.lower()
    assert "score-partwise" in lower
    assert "<staves>2</staves>" in lower
    assert (tmp_path / "bp_midi-ingest" / "midi-ingest.raw.mid").exists()
    assert (tmp_path / "bp_midi-ingest" / "midi-ingest.score.mid").exists()
    raw = pretty_midi.PrettyMIDI(str(tmp_path / "bp_midi-ingest" / "midi-ingest.raw.mid"))
    pitches = sorted(n.pitch for inst in raw.instruments for n in inst.notes)
    assert pitches == [48, 72, 76]


def test_fallback_engine_does_not_use_legacy_for_midi(tmp_path, monkeypatch):
    path = _piano_midi(tmp_path / "no-legacy.mid")
    primary = UnderstandingPipeline()
    fallback = BasicPitchEngine()
    engine = FallbackEngine(primary, fallback)
    called = {"legacy": False}

    def boom(*_args, **_kwargs):
        called["legacy"] = True
        raise AssertionError("legacy should not run for MIDI")

    monkeypatch.setattr(fallback, "transcribe", boom)
    xml = engine.transcribe(path, "midi-fallback")
    assert "score-partwise" in xml.lower()
    assert called["legacy"] is False


def test_get_engine_legacy_still_ingests_midi(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PIPELINE", "legacy")
    path = _piano_midi(tmp_path / "legacy.mid")
    xml = get_engine().transcribe(path, "legacy-midi")
    assert "score-partwise" in xml.lower()
