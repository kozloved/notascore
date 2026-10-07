import mido
import pretty_midi
import pytest

from mir.models import MeterHypothesis
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent


def _tick_tolerance_sec(ticks_per_beat: int, tempos_us: list[int], *, ticks: float = 1.5) -> float:
    """Tolerance derived from MIDI tick resolution at the slowest tempo."""
    slowest = max(int(t) for t in tempos_us)
    return max(0.001, (slowest / 1_000_000.0) / float(ticks_per_beat) * ticks)


def _write_tempo_midi(path, *, ticks_per_beat: int, messages) -> None:
    midi = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend(messages)
    midi.save(path)


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
    ticks_per_beat = 480
    tempos = [500000, 700000, 720000]
    _write_tempo_midi(
        source,
        ticks_per_beat=ticks_per_beat,
        messages=[
            mido.MetaMessage("set_tempo", tempo=tempos[0]),
            mido.MetaMessage("time_signature", numerator=4, denominator=4),
            mido.Message("note_on", note=60, velocity=80, time=120),
            mido.MetaMessage("set_tempo", tempo=tempos[1], time=120),
            mido.Message("note_off", note=60, time=240),
            mido.Message("note_on", note=64, velocity=80),
            mido.MetaMessage("set_tempo", tempo=tempos[2], time=120),
            mido.Message("note_off", note=64, time=360),
        ],
    )
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
    tol = _tick_tolerance_sec(ticks_per_beat, tempos)
    for actual, expected in zip(after, before):
        assert actual == pytest.approx(expected, abs=tol)


def test_multiple_tempo_changes_inside_one_beat_preserve_onsets(tmp_path, monkeypatch):
    """Two tempo changes inside beat 0 must not smear onset 0.375 to a coarse BPM."""
    from mir.pipeline import UnderstandingPipeline
    from mir.raw_midi import job_score_midi_path

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
    source = tmp_path / "intra_beat.mid"
    ticks_per_beat = 480
    tempos = [500000, 600000, 750000, 500000]
    # Tempo at ticks 0, 60 (1/8), 120 (1/4), 240 (1/2); note at tick 180 (3/8).
    _write_tempo_midi(
        source,
        ticks_per_beat=ticks_per_beat,
        messages=[
            mido.MetaMessage("set_tempo", tempo=tempos[0]),
            mido.MetaMessage("time_signature", numerator=4, denominator=4),
            mido.MetaMessage("set_tempo", tempo=tempos[1], time=60),
            mido.MetaMessage("set_tempo", tempo=tempos[2], time=60),
            mido.Message("note_on", note=62, velocity=90, time=60),
            mido.MetaMessage("set_tempo", tempo=tempos[3], time=60),
            mido.Message("note_off", note=62, time=180),
        ],
    )
    original = pretty_midi.PrettyMIDI(str(source))
    pipe = UnderstandingPipeline()
    pipe.transcribe_midi(source, "intra")
    # Playback curve must expose every encoded tempo knot, not only integer beats.
    playback = (pipe.last_score_meta.extra or {}).get("playback_tempo") or []
    assert len(playback) >= 4
    assert playback[0]["bpm"] == pytest.approx(120.0)
    assert pipe.last_timing.time_map.exact_points
    onset_beat = pipe.last_timing.time_map.seconds_to_beats(
        original.instruments[0].notes[0].start
    )
    assert onset_beat == pytest.approx(0.375, abs=1e-9)
    exported = pretty_midi.PrettyMIDI(str(job_score_midi_path(source, "intra")))
    before = sorted((n.pitch, n.start, n.end) for inst in original.instruments for n in inst.notes)
    after = sorted((n.pitch, n.start, n.end) for inst in exported.instruments for n in inst.notes)
    tol = _tick_tolerance_sec(ticks_per_beat, tempos)
    for actual, expected in zip(after, before):
        assert actual == pytest.approx(expected, abs=tol)


def test_note_spanning_tempo_change_keeps_attack_and_release(tmp_path, monkeypatch):
    from mir.pipeline import UnderstandingPipeline
    from mir.raw_midi import job_score_midi_path

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
    source = tmp_path / "span.mid"
    ticks_per_beat = 480
    tempos = [500000, 800000]
    # Attack before the change, release after it.
    _write_tempo_midi(
        source,
        ticks_per_beat=ticks_per_beat,
        messages=[
            mido.MetaMessage("set_tempo", tempo=tempos[0]),
            mido.MetaMessage("time_signature", numerator=4, denominator=4),
            mido.Message("note_on", note=60, velocity=80, time=0),
            mido.MetaMessage("set_tempo", tempo=tempos[1], time=240),
            mido.Message("note_off", note=60, time=240),
        ],
    )
    pipe = UnderstandingPipeline()
    pipe.transcribe_midi(source, "span")
    original = pretty_midi.PrettyMIDI(str(source))
    exported = pretty_midi.PrettyMIDI(str(job_score_midi_path(source, "span")))
    before = original.instruments[0].notes[0]
    after = exported.instruments[0].notes[0]
    tol = _tick_tolerance_sec(ticks_per_beat, tempos)
    assert after.start == pytest.approx(before.start, abs=tol)
    assert after.end == pytest.approx(before.end, abs=tol)
    assert before.start == pytest.approx(0.0, abs=1e-9)
    assert before.end == pytest.approx(0.25 + 0.5 * 0.8, abs=1e-9)


def test_pickup_onset_with_midbeat_tempo_change(tmp_path, monkeypatch):
    from mir.pipeline import UnderstandingPipeline
    from mir.raw_midi import job_score_midi_path

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
    source = tmp_path / "pickup.mid"
    ticks_per_beat = 480
    tempos = [500000, 666666]
    # Pickup eighth at tick 0, tempo change mid-pickup, downbeat attack at tick 240.
    _write_tempo_midi(
        source,
        ticks_per_beat=ticks_per_beat,
        messages=[
            mido.MetaMessage("set_tempo", tempo=tempos[0]),
            mido.MetaMessage("time_signature", numerator=4, denominator=4),
            mido.Message("note_on", note=67, velocity=70, time=0),
            mido.MetaMessage("set_tempo", tempo=tempos[1], time=120),
            mido.Message("note_off", note=67, time=120),
            mido.Message("note_on", note=60, velocity=90),
            mido.Message("note_off", note=60, time=480),
        ],
    )
    pipe = UnderstandingPipeline()
    pipe.transcribe_midi(source, "pickup")
    original = pretty_midi.PrettyMIDI(str(source))
    exported = pretty_midi.PrettyMIDI(str(job_score_midi_path(source, "pickup")))
    before = sorted((n.pitch, n.start, n.end) for inst in original.instruments for n in inst.notes)
    after = sorted((n.pitch, n.start, n.end) for inst in exported.instruments for n in inst.notes)
    tol = _tick_tolerance_sec(ticks_per_beat, tempos)
    assert len(after) == len(before)
    for actual, expected in zip(after, before):
        assert actual == pytest.approx(expected, abs=tol)


def test_pickup_keeps_sparse_printed_tempo_and_full_playback_curve(tmp_path, monkeypatch):
    """A rebased pickup must not truncate the absolute playback tempo curve.

    Short local fluctuations stay off the printed page under the sparse tempo
    policy introduced in PR #98, but survive decoded MIDI playback.
    """
    from music21 import converter, tempo as m21tempo

    from mir.midi_ingest import ingest_midi
    from mir.notation_regen import recompute_notation
    from mir.notation_settings import NotationSettings
    from mir.pipeline import UnderstandingPipeline
    from mir.raw_midi import job_score_midi_path
    from tests.test_shared_engraving import _context_for

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
    source = tmp_path / "pickup_tempo_rebase.mid"
    ticks_per_beat = 480
    tempos = [500000, 666667, 600000]
    _write_tempo_midi(
        source,
        ticks_per_beat=ticks_per_beat,
        messages=[
            mido.MetaMessage("set_tempo", tempo=tempos[0]),
            mido.MetaMessage("time_signature", numerator=4, denominator=4),
            # Silence until beat 3, then pickup eighth.
            mido.Message("note_on", note=67, velocity=80, time=1440),
            mido.MetaMessage("set_tempo", tempo=tempos[1], time=240),  # beat 3.5
            mido.Message("note_off", note=67, time=0),
            mido.MetaMessage("set_tempo", tempo=tempos[2], time=240),  # beat 4
            mido.Message("note_on", note=60, velocity=90, time=0),
            mido.Message("note_off", note=60, time=480),
            mido.Message("note_on", note=62, velocity=85, time=0),
            mido.Message("note_off", note=62, time=480),
        ],
    )
    original = source.read_bytes()
    settings = NotationSettings.from_dict(
        {"meter": "4/4", "pickup_beats": 1.0, "first_downbeat_beat": 4.0}
    )
    pipe = UnderstandingPipeline()
    pipe.notation_settings = settings
    xml = pipe.transcribe_midi(source, "pickup_tempo_rebase")
    assert source.read_bytes() == original
    assert (pipe.notation.last_plan.extra or {}).get("pickup_origin_shift") == pytest.approx(3.0)
    measures = pipe.notation.last_plan.measures
    assert measures[0].duration_beats == pytest.approx(1.0)
    assert measures[1].start_beat == pytest.approx(1.0)
    # Performance coordinates stay absolute.
    by_pitch = {e.pitch: e.start_beat for e in pipe.notation.last_quantized_events}
    assert by_pitch[67] == pytest.approx(3.0)
    assert by_pitch[60] == pytest.approx(4.0)

    score = converter.parse(xml, format="musicxml")
    marks = {
        int(round(float(m.number))): float(m.getOffsetInHierarchy(score))
        for m in score.recurse().getElementsByClass(m21tempo.MetronomeMark)
    }
    assert marks == {round(pipe.last_score_meta.display_tempo_bpm): 0.0}

    exported = pretty_midi.PrettyMIDI(str(job_score_midi_path(source, "pickup_tempo_rebase")))
    before = sorted((n.pitch, n.start, n.end) for inst in pretty_midi.PrettyMIDI(str(source)).instruments for n in inst.notes)
    after = sorted((n.pitch, n.start, n.end) for inst in exported.instruments for n in inst.notes)
    tol = _tick_tolerance_sec(ticks_per_beat, tempos)
    assert len(after) == len(before)
    for actual, expected in zip(after, before):
        assert actual == pytest.approx(expected, abs=tol)

    ingested = ingest_midi(source)
    ctx = _context_for(ingested)
    auto = recompute_notation(
        midi_bytes=original, settings=settings, performance=ingested.performance, context=ctx
    )
    sid = auto.editor_model["notes"][0].get("source_note_id") or auto.editor_model["notes"][0]["id"]
    edited = recompute_notation(
        midi_bytes=original,
        settings=settings,
        performance=ingested.performance,
        context=ctx,
        corrections=[{"source_note_id": sid, "velocity": 101}],
    )
    assert source.read_bytes() == original

    def _mark_map(xml_text: str) -> dict[int, float]:
        parsed = converter.parse(xml_text, format="musicxml")
        return {
            int(round(float(m.number))): float(m.getOffsetInHierarchy(parsed))
            for m in parsed.recurse().getElementsByClass(m21tempo.MetronomeMark)
        }

    auto_marks = _mark_map(auto.musicxml)
    edit_marks = _mark_map(edited.musicxml)
    assert auto_marks == edit_marks
    assert len(auto_marks) == 1 and list(auto_marks.values()) == [0.0]


def test_repeated_pitch_across_tempo_changes_keeps_reattacks(tmp_path, monkeypatch):
    from mir.pipeline import UnderstandingPipeline
    from mir.raw_midi import job_score_midi_path

    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "performance")
    source = tmp_path / "repeats.mid"
    ticks_per_beat = 480
    tempos = [500000, 700000, 500000]
    _write_tempo_midi(
        source,
        ticks_per_beat=ticks_per_beat,
        messages=[
            mido.MetaMessage("set_tempo", tempo=tempos[0]),
            mido.MetaMessage("time_signature", numerator=4, denominator=4),
            mido.Message("note_on", note=60, velocity=80, time=0),
            mido.Message("note_off", note=60, time=120),
            mido.MetaMessage("set_tempo", tempo=tempos[1], time=0),
            mido.Message("note_on", note=60, velocity=82, time=0),
            mido.Message("note_off", note=60, time=120),
            mido.MetaMessage("set_tempo", tempo=tempos[2], time=0),
            mido.Message("note_on", note=60, velocity=84, time=0),
            mido.Message("note_off", note=60, time=240),
        ],
    )
    pipe = UnderstandingPipeline()
    pipe.transcribe_midi(source, "repeats")
    original = pretty_midi.PrettyMIDI(str(source))
    exported = pretty_midi.PrettyMIDI(str(job_score_midi_path(source, "repeats")))
    before = sorted((n.pitch, n.start, n.end) for inst in original.instruments for n in inst.notes)
    after = sorted((n.pitch, n.start, n.end) for inst in exported.instruments for n in inst.notes)
    assert len(before) == 3
    assert len(after) == 3
    tol = _tick_tolerance_sec(ticks_per_beat, tempos)
    for actual, expected in zip(after, before):
        assert actual == pytest.approx(expected, abs=tol)
