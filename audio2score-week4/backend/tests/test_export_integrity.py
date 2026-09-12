from copy import deepcopy
from pathlib import Path
from random import Random
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import mido
import pytest

from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.pipeline_config import QuantizationMode
from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.integrity import NotationIntegrityError, validate_event_identity
from notation_engine.writer import NotationWriter
from transcription import FallbackEngine


def event(ident, pitch=60, start=0, duration=1, voice=0):
    return MusicalEvent(pitch, start, duration, note_id=ident, voice=voice,
                        hand=Hand.RIGHT, source_backend="midi")


def write(writer, notes, tmp_path):
    return writer.write_musicxml(notes, ScoreMeta(time_sig_hint="4/4"), "audit",
                                 tmp_path / "input.mid", quantization_mode="performance")


def test_identity_guard_rejects_same_count_replacement():
    source = [event("a"), event("b", 64)]
    with pytest.raises(NotationIntegrityError):
        validate_event_identity(source, [event("a"), event("fake", 64)])


@pytest.mark.parametrize("corruption", ["repeat", "break_tie", "drop"])
def test_corrupt_xml_is_not_published(tmp_path, monkeypatch, corruption):
    writer = NotationWriter()
    original = writer._export_musicxml

    def corrupt(score, path):
        original(score, path)
        tree = ET.parse(path)
        if corruption == "break_tie":
            for parent in tree.iter():
                for child in list(parent):
                    if child.tag in ("tie", "tied"):
                        parent.remove(child)
        else:
            measure = tree.find(".//measure")
            note = next(n for n in measure.findall("note") if n.find("pitch") is not None)
            if corruption == "repeat":
                measure.append(deepcopy(note))
            else:
                measure.remove(note)
        tree.write(path, encoding="utf-8", xml_declaration=True)

    monkeypatch.setattr(writer, "_export_musicxml", corrupt)
    with pytest.raises(NotationIntegrityError):
        write(writer, [event("held", duration=6)], tmp_path)
    assert not (tmp_path / "bp_audit" / "audit.musicxml").exists()
    assert not (tmp_path / "bp_audit" / "audit.score.mid").exists()
    assert writer.last_export_integrity["status"] == "failed"


def test_corrupt_midi_is_not_published(tmp_path, monkeypatch):
    from music21 import stream

    original = stream.Score.write

    def corrupt(score, fmt, **kwargs):
        result = original(score, fmt, **kwargs)
        if fmt == "midi":
            midi = mido.MidiFile(kwargs["fp"])
            midi.tracks[-1].insert(0, mido.Message("note_on", note=60, velocity=80))
            midi.save(kwargs["fp"])
        return result

    monkeypatch.setattr(stream.Score, "write", corrupt)
    with pytest.raises(NotationIntegrityError, match="MIDI"):
        write(NotationWriter(), [event("a")], tmp_path)
    assert not (tmp_path / "bp_audit" / "audit.score.mid").exists()


def test_integrity_failure_never_invokes_legacy_fallback():
    primary, legacy = Mock(), Mock()
    primary.config = SimpleNamespace(quantization_mode=QuantizationMode.OFF)
    primary.transcribe.side_effect = NotationIntegrityError("extra attack")
    with pytest.raises(NotationIntegrityError):
        FallbackEngine(primary, legacy).transcribe("audio.wav", "audit")
    legacy.transcribe.assert_not_called()


def test_absent_downbeat_evidence_stays_absent():
    from timing.existing_tracker import analysis_from_beat_times, analyze_from_tracker

    beats = [i * 0.5 for i in range(12)]
    assert analysis_from_beat_times(beats).downbeat_times == []
    tracker = SimpleNamespace(last_beat_result=None, last_beat_times=beats, last_source="librosa")
    assert analyze_from_tracker(tracker).downbeat_times == []


def test_audio_score_is_not_shifted_twice(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    from mir.pipeline import UnderstandingPipeline
    from mir.models import MeterDecision, MeterHypothesis
    from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent, TempoMap
    from audio_engine.madmom_beats import MadmomBeatResult

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
    monkeypatch.setenv("TRANSCRIPTION_ENABLE_GEMINI", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_PIANO_ANALYZER", "0")
    notes = [NoteEvent(60 + i % 3, 0.5 + i * 0.5, 1 + i * 0.5,
                       note_id=str(i)) for i in range(8)]
    monkeypatch.setattr("adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes",
                        lambda *args: notes)
    monkeypatch.setattr("mir.score_interpretation.evaluate_candidates", lambda *args: [])
    source = tmp_path / "audio.wav"
    sf.write(source, np.zeros(22050 * 5), 22050)
    pipe = UnderstandingPipeline()
    beats = [0.25 + i * 0.5 for i in range(12)]
    result = MadmomBeatResult(TempoMap(), "4/4", beats, beats[::4])
    pipe.beat_tracker.last_beat_result = result
    pipe.beat_tracker.last_source = "madmom"
    monkeypatch.setattr(pipe, "_prefetch_cpu", lambda *args: (
        InstrumentPrediction(InstrumentKind.PIANO, 1), []))
    monkeypatch.setattr(pipe, "_build_tempo_map", lambda *args: (TempoMap(), "4/4"))
    meter = MeterHypothesis("4/4", 4, 4, 4, 1, 1)
    monkeypatch.setattr(pipe, "_arbitrate_meter", lambda *args, **kwargs:
                        MeterDecision("4/4", 1, hypothesis=meter))
    pipe.transcribe(source, "phase")
    assert [e.start_beat for e in pipe.last_quantized_events] == [0.5 + i for i in range(8)]
    assert pipe.notation.last_quantization_summary["score_beat_offset"] == 0
    assert pipe.notation.last_export_integrity["status"] == "passed"


def test_editor_keeps_tied_sustain_as_one_attack(tmp_path):
    from score_edits import extract_from_musicxml, build_musicxml_and_midi

    xml = write(NotationWriter(), [event("held", duration=6), event("repeat", start=6)], tmp_path)
    model = extract_from_musicxml(xml)
    assert [(n["start"], n["duration"]) for n in model["notes"]] == [(0, 6), (6, 1)]
    rebuilt, _ = build_musicxml_and_midi(model)
    assert len(extract_from_musicxml(rebuilt)["notes"]) == 2


def test_editor_keeps_untouched_triplets(tmp_path):
    from score_edits import extract_from_musicxml, build_musicxml_and_midi

    xml = write(NotationWriter(), [event(str(i), 60 + i, i / 3, 1 / 3) for i in range(6)], tmp_path)
    model = extract_from_musicxml(xml)
    assert [n["start"] for n in model["notes"]] == pytest.approx([i / 3 for i in range(6)])
    rebuilt, _ = build_musicxml_and_midi(model)
    assert [n["duration"] for n in extract_from_musicxml(rebuilt)["notes"]] == pytest.approx([1 / 3] * 6)


def test_old_job_download_keeps_ties_and_real_repeats(tmp_path):
    from io import BytesIO
    from main import _musicxml_to_midi_bytes

    xml = write(NotationWriter(), [event("held", duration=6), event("repeat", start=6)], tmp_path)
    midi = mido.MidiFile(file=BytesIO(_musicxml_to_midi_bytes(xml)))
    attacks = [message for track in midi.tracks for message in track
               if message.type == "note_on" and message.velocity > 0]
    assert len(attacks) == 2


@pytest.mark.parametrize("seed", range(8))
def test_generated_polyphony_preserves_all_attacks(tmp_path, seed):
    rng = Random(seed)
    notes = []
    for voice in range(3):
        cursor = 0
        for i in range(16):
            duration = rng.choice([0.25, 0.5, 1, 1.5, 3, 5])
            pitches = rng.sample(range(48 + voice * 8, 60 + voice * 8), rng.choice([1, 2, 3]))
            notes.extend(event(f"{voice}:{i}:{pitch}", pitch, cursor, duration, voice)
                         for pitch in pitches)
            cursor += duration + rng.choice([0, 0, 0.25])
    writer = NotationWriter()
    write(writer, notes, tmp_path)
    assert writer.last_export_integrity == {
        "status": "passed", "expected_attacks": len(notes),
        "musicxml_attacks": len(notes), "midi_attacks": len(notes),
    }


CORPUS = Path(__file__).resolve().parents[1] / "benchmark" / "corpus"


@pytest.mark.parametrize("source", sorted(CORPUS.rglob("input.mid")),
                         ids=lambda p: p.parent.name)
def test_corpus_has_no_invented_export_attacks(tmp_path, source):
    ingested = ingest_midi(source)
    writer = NotationWriter()
    writer.write_musicxml(
        notes_to_events(ingested.notes, ingested.tempo_map),
        ScoreMeta(time_sig_hint=ingested.time_sig_hint, tempo_map=ingested.tempo_map,
                  extra={"preserve_midi_tempo": True}),
        "corpus", tmp_path / "source.mid", quantization_mode="performance")
    assert writer.last_export_integrity["status"] == "passed"
    assert writer.last_export_integrity["expected_attacks"] == len(ingested.notes)
