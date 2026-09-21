"""Tests for MIDI-file ingest into CMR."""

from __future__ import annotations

import pretty_midi
import pytest

from mir.midi_ingest import NoPitchedNotesError, hand_from_track_name, ingest_midi, is_midi_path
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


def test_ingest_empty_midi_raises_typed_no_pitched_notes(tmp_path):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    midi.instruments.append(pretty_midi.Instrument(program=0, name="Empty"))
    path = tmp_path / "empty.mid"
    midi.write(str(path))
    data = path.read_bytes()
    with pytest.raises(NoPitchedNotesError) as exc:
        ingest_midi(path)
    assert exc.value.reason == "empty"
    assert exc.value.midi_bytes == data
    assert exc.value.performance is not None
    assert isinstance(exc.value, ValueError)


def test_ingest_drum_only_midi_raises_typed_no_pitched_notes(tmp_path):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    drums = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
    drums.notes.append(pretty_midi.Note(velocity=100, pitch=36, start=0.0, end=0.2))
    midi.instruments.append(drums)
    path = tmp_path / "drums.mid"
    midi.write(str(path))
    with pytest.raises(NoPitchedNotesError) as exc:
        ingest_midi(path)
    assert exc.value.reason == "drum_only"
    assert exc.value.performance is not None
    assert any(n.is_drum for n in exc.value.performance.notes)


def test_ingest_fifo_pairs_overlapping_unison_reattacks(tmp_path):
    """pretty_midi collapses overlapping G4s; FIFO pairing keeps ~0.58s each."""
    from evaluation.readable_v2_cases import case_c_repeated_attacks_under_pedal

    path = tmp_path / "overlap.mid"
    case_c_repeated_attacks_under_pedal(path)
    original = path.read_bytes()
    ingested = ingest_midi(path)
    assert path.read_bytes() == original
    notes = ingested.performance.notes
    assert len(notes) == 4
    starts = [round(n.start_sec, 3) for n in notes]
    durs = [n.end_sec - n.start_sec for n in notes]
    assert starts == [0.0, 0.5, 1.0, 1.5]
    assert all(0.55 <= d <= 0.61 for d in durs)
    pm = pretty_midi.PrettyMIDI(str(path))
    pretty_durs = [n.end - n.start for inst in pm.instruments for n in inst.notes]
    assert min(pretty_durs) < 0.12
    assert min(durs) > min(pretty_durs)


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


def _smf_bytes(*, tracks, tempo=120, ticks_per_beat=480):
    import io

    import mido

    mid = mido.MidiFile(ticks_per_beat=ticks_per_beat, type=1)
    meta = mido.MidiTrack()
    mid.tracks.append(meta)
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo)))
    for spec in tracks:
        tr = mido.MidiTrack()
        mid.tracks.append(tr)
        if spec.get("name"):
            tr.append(mido.MetaMessage("track_name", name=spec["name"]))
        for item in spec["events"]:
            tr.append(item)
    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


def _write_smf(path, **kwargs):
    data = _smf_bytes(**kwargs)
    path.write_bytes(data)
    return data


def test_pairing_same_pitch_onset_two_streams(tmp_path):
    import hashlib

    import mido

    from mir.midi_ingest import NOTE_PAIRING_FIFO, parse_smf_notes

    path = tmp_path / "two-streams.mid"
    data = _write_smf(
        path,
        tracks=[
            {
                "name": "Long",
                "events": [
                    mido.Message("program_change", program=0, channel=0, time=0),
                    mido.Message("note_on", note=67, velocity=80, channel=0, time=0),
                    mido.Message("note_off", note=67, velocity=0, channel=0, time=1920),
                ],
            },
            {
                "name": "Short",
                "events": [
                    mido.Message("program_change", program=0, channel=1, time=0),
                    mido.Message("note_on", note=67, velocity=90, channel=1, time=0),
                    mido.Message("note_off", note=67, velocity=0, channel=1, time=480),
                ],
            },
        ],
    )
    original = hashlib.sha256(data).hexdigest()
    ingested = ingest_midi(path)
    assert path.read_bytes() == data
    assert ingested.performance.midi_sha256 == original
    assert ingested.performance.note_pairing == NOTE_PAIRING_FIFO
    by_ch = {n.channel: n for n in ingested.performance.notes}
    assert round(by_ch[0].end_sec - by_ch[0].start_sec, 3) == 2.0
    assert round(by_ch[1].end_sec - by_ch[1].start_sec, 3) == 0.5
    parsed = parse_smf_notes(data, pretty_midi.PrettyMIDI(str(path)))
    assert {(r["channel"], round(r["end"] - r["start"], 3)) for r in parsed.notes} == {
        (0, 2.0),
        (1, 0.5),
    }


def test_pairing_reversed_track_order(tmp_path):
    import mido

    path = tmp_path / "reversed.mid"
    data = _write_smf(
        path,
        tracks=[
            {
                "name": "ShortFirst",
                "events": [
                    mido.Message("program_change", program=0, channel=2, time=0),
                    mido.Message("note_on", note=60, velocity=70, channel=2, time=0),
                    mido.Message("note_off", note=60, velocity=0, channel=2, time=240),
                ],
            },
            {
                "name": "LongSecond",
                "events": [
                    mido.Message("program_change", program=0, channel=3, time=0),
                    mido.Message("note_on", note=60, velocity=80, channel=3, time=0),
                    mido.Message("note_off", note=60, velocity=0, channel=3, time=1920),
                ],
            },
        ],
    )
    ingested = ingest_midi(path)
    assert path.read_bytes() == data
    by_ch = {n.channel: n for n in ingested.performance.notes}
    assert round(by_ch[2].end_sec, 3) == 0.25
    assert round(by_ch[3].end_sec, 3) == 2.0
    assert ingested.performance.notes[0].note_id.startswith("track:0:")
    assert ingested.performance.notes[1].note_id.startswith("track:1:")


def test_pairing_same_program_different_channels(tmp_path):
    import mido

    path = tmp_path / "channels.mid"
    data = _write_smf(
        path,
        tracks=[
            {
                "name": "SplitCh",
                "events": [
                    mido.Message("program_change", program=40, channel=0, time=0),
                    mido.Message("program_change", program=40, channel=1, time=0),
                    mido.Message("note_on", note=64, velocity=80, channel=0, time=0),
                    mido.Message("note_on", note=64, velocity=90, channel=1, time=0),
                    mido.Message("note_off", note=64, velocity=0, channel=1, time=240),
                    mido.Message("note_off", note=64, velocity=0, channel=0, time=1680),
                ],
            }
        ],
    )
    ingested = ingest_midi(path)
    assert path.read_bytes() == data
    notes = ingested.performance.notes
    assert {n.program for n in notes} == {40}
    by_ch = {n.channel: n for n in notes}
    assert round(by_ch[1].end_sec, 3) == 0.25
    assert round(by_ch[0].end_sec, 3) == 2.0


def test_pairing_overlapping_repeats_one_stream(tmp_path):
    import mido

    from mir.midi_ingest import parse_smf_notes

    path = tmp_path / "retrig.mid"
    data = _write_smf(
        path,
        tracks=[
            {
                "name": "Retrig",
                "events": [
                    mido.Message("note_on", note=67, velocity=80, channel=0, time=0),
                    mido.Message("note_on", note=67, velocity=80, channel=0, time=240),
                    mido.Message("note_off", note=67, velocity=0, channel=0, time=40),
                    mido.Message("note_off", note=67, velocity=0, channel=0, time=240),
                ],
            }
        ],
    )
    ingested = ingest_midi(path)
    assert path.read_bytes() == data
    starts = [round(n.start_sec, 3) for n in ingested.performance.notes]
    ends = [round(n.end_sec, 3) for n in ingested.performance.notes]
    assert starts == [0.0, 0.25]
    assert ends == [0.292, 0.542]
    pm = pretty_midi.PrettyMIDI(str(path))
    pretty_ends = [round(n.end, 3) for inst in pm.instruments for n in inst.notes]
    assert pretty_ends == [0.292, 0.292]
    parsed = parse_smf_notes(data, pm)
    assert parsed.unmatched_note_offs == 0
    assert parsed.dangling_note_ons == 0


def test_pairing_program_change_and_unmatched_note_off(tmp_path):
    import mido

    from mir.midi_ingest import parse_smf_notes

    path = tmp_path / "pchg.mid"
    data = _write_smf(
        path,
        tracks=[
            {
                "name": "Pchg",
                "events": [
                    mido.Message("program_change", program=0, channel=0, time=0),
                    mido.Message("note_on", note=60, velocity=80, channel=0, time=0),
                    mido.Message("program_change", program=40, channel=0, time=240),
                    mido.Message("note_off", note=60, velocity=0, channel=0, time=240),
                    mido.Message("note_on", note=67, velocity=70, channel=0, time=0),
                    mido.Message("note_off", note=67, velocity=0, channel=0, time=480),
                    mido.Message("note_off", note=72, velocity=0, channel=0, time=0),
                ],
            }
        ],
    )
    parsed = parse_smf_notes(data, pretty_midi.PrettyMIDI(str(path)))
    assert parsed.unmatched_note_offs == 1
    assert parsed.dangling_note_ons == 0
    by_pitch = {r["pitch"]: r for r in parsed.notes}
    assert by_pitch[60]["program"] == 0
    assert by_pitch[60]["program_off"] == 40
    assert by_pitch[67]["program"] == 40
    ingested = ingest_midi(path)
    assert path.read_bytes() == data
    assert ingested.performance.note_pairing is not None
    # PrettyMIDI groups both notes onto the program-at-off instrument.
    assert all(n.program == 40 for n in ingested.performance.notes)
    assert [round(n.end_sec - n.start_sec, 3) for n in ingested.performance.notes] == [0.5, 0.5]


def test_legacy_snapshot_without_pairing_metadata_still_loads(tmp_path):
    from mir.performance import PerformanceSnapshot, SourceNote

    snap = PerformanceSnapshot(
        "midi",
        (SourceNote("track:0:note:0", 60, 0.0, 1.0, 80, 1.0, "track:0", 0),),
        midi_sha256="abc",
    )
    snap.write_json(tmp_path / "legacy.json")
    loaded = PerformanceSnapshot.read_json(tmp_path / "legacy.json")
    assert loaded.note_pairing is None
    assert loaded.notes[0].note_id == "track:0:note:0"
    assert loaded.schema_version == 1
