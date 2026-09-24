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


def test_off_mode_skips_source_identity_gate(tmp_path):
    writer = NotationWriter()
    writer.write_musicxml(
        [event("a")],
        ScoreMeta(time_sig_hint="4/4"),
        "legacy",
        tmp_path / "input.mid",
        quantization_mode="off",
    )
    assert writer.last_export_integrity["status"] == "skipped"
    assert writer.last_export_integrity["lossless"] is False
    debug = writer.notation_debug_payload()
    assert debug["score_is_hypothesis"] is True
    assert debug["source_identity_gate"] is False
    assert debug["readability_requires_human"] is True


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


def test_editor_keeps_tied_sustain_as_one_attack(tmp_path):
    from score_edits import extract_from_musicxml, build_musicxml_and_midi

    xml = write(NotationWriter(), [event("held", duration=6), event("repeat", start=6)], tmp_path)
    model = extract_from_musicxml(xml)
    assert [(n["start"], n["duration"]) for n in model["notes"]] == [(0, 6), (6, 1)]
    rebuilt, _ = build_musicxml_and_midi(model)
    assert len(extract_from_musicxml(rebuilt)["notes"]) == 2


def _musicxml_time_modifications(xml_text: str) -> list[tuple[int, int]]:
    rows = []
    root = ET.fromstring(xml_text)
    for note in root.iter():
        if note.tag.split("}")[-1] != "note":
            continue
        if note.find("{*}rest") is not None or note.find(".//{*}rest") is not None:
            continue
        actual = note.find(".//{*}actual-notes")
        normal = note.find(".//{*}normal-notes")
        if actual is None or normal is None:
            continue
        rows.append((int(actual.text or 0), int(normal.text or 0)))
    return rows


def _midi_quarter_lengths(midi_bytes: bytes, *, tempo_bpm: float = 120.0) -> list[float]:
    midi = mido.MidiFile(file=__import__("io").BytesIO(midi_bytes))
    tpb = midi.ticks_per_beat or 480
    pending: dict[tuple[int, int], int] = {}
    lengths: list[float] = []
    tick = 0
    for message in mido.merge_tracks(midi.tracks):
        tick += int(message.time)
        if message.type == "note_on" and message.velocity > 0:
            pending[(message.channel, message.note)] = tick
        elif message.type in ("note_off", "note_on"):
            start = pending.pop((message.channel, message.note), None)
            if start is None:
                continue
            lengths.append((tick - start) / tpb)
    return lengths


def _mixed_triplet_events():
    return [
        event("q0", 60, 0, 1),
        event("q1", 62, 1, 1),
        event("t0", 72, 2, 1 / 3),
        event("t1", 74, 2 + 1 / 3, 1 / 3),
        event("t2", 76, 2 + 2 / 3, 1 / 3),
        event("q2", 64, 3, 1),
    ]


def test_as_score_fraction_keeps_notated_triplets():
    from fractions import Fraction

    from mir.performance_score import as_score_fraction
    from mir.quantizer import snap_writable_length

    assert snap_writable_length(1 / 3) == 0.3125
    assert as_score_fraction(1 / 3, positive=True) == Fraction(1, 3)
    assert as_score_fraction(2 / 3) == Fraction(2, 3)
    assert as_score_fraction(1 / 3, locked=True, positive=True) == Fraction(1, 3)
    assert as_score_fraction(0.25, positive=True) == Fraction(1, 4)


def test_editor_keeps_untouched_triplets(tmp_path):
    from score_edits import extract_from_musicxml, build_musicxml_and_midi

    xml = write(NotationWriter(), [event(str(i), 60 + i, i / 3, 1 / 3) for i in range(6)], tmp_path)
    model = extract_from_musicxml(xml)
    assert [n["start"] for n in model["notes"]] == pytest.approx([i / 3 for i in range(6)])
    assert [n["duration"] for n in model["notes"]] == pytest.approx([1 / 3] * 6)
    rebuilt, _ = build_musicxml_and_midi(model)
    assert [n["duration"] for n in extract_from_musicxml(rebuilt)["notes"]] == pytest.approx([1 / 3] * 6)


def test_editor_keeps_mixed_triplets_musicxml_only(tmp_path):
    from score_edits import extract_from_musicxml, build_musicxml_and_midi

    xml = write(NotationWriter(), _mixed_triplet_events(), tmp_path)
    model = extract_from_musicxml(xml)
    starts = [n["start"] for n in model["notes"]]
    durs = [n["duration"] for n in model["notes"]]
    assert starts == pytest.approx([0, 1, 2, 2 + 1 / 3, 2 + 2 / 3, 3])
    assert durs == pytest.approx([1, 1, 1 / 3, 1 / 3, 1 / 3, 1])
    assert _musicxml_time_modifications(xml)
    target = next(n for n in model["notes"] if abs(n["start"] - 1) < 1e-6)
    target["pitch"] = 63
    target["velocity"] = 99
    target["articulation"] = "tenuto"
    rebuilt, midi_bytes = build_musicxml_and_midi(model)
    again = extract_from_musicxml(rebuilt)
    assert [n["start"] for n in again["notes"]] == pytest.approx(starts)
    assert [n["duration"] for n in again["notes"]] == pytest.approx(durs)
    mods = _musicxml_time_modifications(rebuilt)
    assert mods
    assert all(actual == 3 and normal == 2 for actual, normal in mods)
    lengths = _midi_quarter_lengths(midi_bytes)
    assert any(abs(length - 1 / 3) < 0.02 for length in lengths)
    assert any(abs(length - 1) < 0.02 for length in lengths)


def test_editor_keeps_mixed_triplets_performance_backed(tmp_path):
    from mir.midi_ingest import ingest_midi
    from mir.notation_regen import recompute_notation
    from mir.notation_settings import NotationSettings
    from score_edits import extract_from_musicxml, build_musicxml_and_midi
    from tests.test_shared_engraving import _context_for, _write_midi

    # 120 BPM: quarter = 0.5s, triplet eighth = 1/6s.
    notes = [
        (60, 0.0, 0.5, 80),
        (62, 0.5, 1.0, 80),
        (72, 1.0, 1.0 + 0.5 / 3, 84),
        (74, 1.0 + 0.5 / 3, 1.0 + 1.0 / 3, 84),
        (76, 1.0 + 1.0 / 3, 1.5, 84),
        (64, 1.5, 2.0, 80),
    ]
    midi_path = tmp_path / "mixed.mid"
    original = _write_midi(midi_path, notes)
    ingested = ingest_midi(midi_path)
    result = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    assert midi_path.read_bytes() == original
    model = result.editor_model
    trip = [n for n in model["notes"] if abs(n["duration"] - 1 / 3) < 0.05]
    assert len(trip) >= 3
    trip_starts = [n["start"] for n in trip]
    trip_durs = [n["duration"] for n in trip]
    louder = next(n for n in model["notes"] if abs(n["start"] - 0.0) < 1e-6)
    louder["velocity"] = 108
    louder["pitch"] = 61
    rebuilt, _ = build_musicxml_and_midi(model)
    again = extract_from_musicxml(rebuilt)
    restored = [n for n in again["notes"] if abs(n["duration"] - 1 / 3) < 0.05]
    assert [n["start"] for n in restored] == pytest.approx(trip_starts, abs=1e-3)
    assert [n["duration"] for n in restored] == pytest.approx(trip_durs, abs=1e-3)
    edited = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=_context_for(ingested),
        corrections=[{"source_note_id": trip[0].get("source_note_id") or trip[0]["id"], "articulation": "staccato"}],
    )
    assert midi_path.read_bytes() == original
    after = [n for n in edited.editor_model["notes"] if abs(n["duration"] - 1 / 3) < 0.05]
    assert [n["duration"] for n in after] == pytest.approx(trip_durs, abs=1e-3)
    assert _musicxml_time_modifications(edited.musicxml)


def test_explicit_timing_edit_may_leave_grid_and_keeps_neighbors(tmp_path):
    from score_edits import extract_from_musicxml, build_musicxml_and_midi

    xml = write(NotationWriter(), _mixed_triplet_events(), tmp_path)
    model = extract_from_musicxml(xml)
    moved = next(n for n in model["notes"] if abs(n["start"] - 1) < 1e-6)
    moved["start"] = 1.25
    moved["duration"] = 0.25
    rebuilt, _ = build_musicxml_and_midi(model)
    again = extract_from_musicxml(rebuilt)
    by_pitch = {n["pitch"]: n for n in again["notes"]}
    assert by_pitch[62]["start"] == pytest.approx(1.25)
    assert by_pitch[62]["duration"] == pytest.approx(0.25)
    assert by_pitch[72]["duration"] == pytest.approx(1 / 3)
    assert by_pitch[74]["duration"] == pytest.approx(1 / 3)
    assert by_pitch[76]["duration"] == pytest.approx(1 / 3)


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
