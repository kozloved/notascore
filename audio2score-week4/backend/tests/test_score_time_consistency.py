"""Score-time retune must update every derived timing field atomically."""

from types import SimpleNamespace

import pytest
from music21 import converter

from mir.cmr_builder import notes_to_events
from mir.models import MeterHypothesis
from mir.pipeline import UnderstandingPipeline
from mir.raw_midi import job_raw_midi_path
from mir.score_interpretation import scaled_time_map, source_identity
from mir.types import MusicalEvent, NoteEvent, ScoreMeta
from notation_engine.writer import NotationWriter
from timing.service import (
    align_score_origin,
    apply_score_time_map,
    maps_logically_equal,
    resolve_from_beat_times,
    score_time_consistency_issues,
    score_time_fingerprint,
)
from timing.tempo_map import MusicalTimeMap

METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)


def _grid(bpm=120.0, duration=8.0, origin=0.0):
    interval = 60.0 / bpm
    times = [origin + i * interval for i in range(int(duration / interval) + 3)]
    return resolve_from_beat_times(times, duration_sec=duration, model="fixture_120")


def _notes_quarters(count=8, bpm=120.0):
    spb = 60.0 / bpm
    return [
        NoteEvent(60 + (i % 4), i * spb, i * spb + 0.9 * spb, velocity=80, note_id=f"n{i}")
        for i in range(count)
    ]


def _retune(timing, scale: float):
    new_map = scaled_time_map(timing.time_map, scale)
    return apply_score_time_map(
        timing,
        new_map,
        reason=f"score time retuned: tempo_scale={scale}",
        tempo_scale=scale,
    )


def _opening_printed_bpm(timing) -> int | None:
    for mark in timing.printed:
        if mark.bpm is not None:
            return int(mark.bpm)
    return None


def test_identity_scale_is_a_noop_on_the_map():
    timing = _grid()
    before = score_time_fingerprint(timing)
    same = scaled_time_map(timing.time_map, 1.0)
    assert same is timing.time_map
    assert maps_logically_equal(same, timing.time_map)
    assert score_time_fingerprint(timing) == before
    assert not any("score time retuned" in w for w in timing.analysis.warnings)
    assert timing.tempo_scale == 1.0
    assert abs((timing.quality.median_bpm or 0) - 120.0) < 1e-6
    assert score_time_consistency_issues(timing) == []


def test_half_time_retune_updates_all_derived_state():
    timing = _grid()
    notes = _notes_quarters()
    identity = [source_identity(n) for n in notes]
    performance_beats = list(timing.time_map.beat_times)
    performance_bpm = timing.quality.median_bpm
    _retune(timing, 0.5)
    assert [source_identity(n) for n in notes] == identity
    assert abs((timing.quality.median_bpm or 0) - 60.0) < 1e-6
    assert abs((timing.performance_median_bpm or 0) - 120.0) < 1e-6
    assert list(timing.performance_beat_times) == performance_beats
    assert len(timing.time_map.beat_times) < len(performance_beats)
    assert list(timing.analysis.beat_times) == list(timing.time_map.beat_times)
    assert maps_logically_equal(timing.analysis.time_map, timing.time_map)
    assert _opening_printed_bpm(timing) == 60
    assert score_time_consistency_issues(timing) == []
    payload = timing.to_dict()
    assert payload["retuned"] is True
    assert payload["tempo_scale"] == 0.5
    assert payload["performance_median_bpm"] == pytest.approx(120.0)
    assert payload["score_median_bpm"] == pytest.approx(60.0)
    assert payload["performance"]["median_bpm"] == pytest.approx(120.0)
    assert payload["score"]["median_bpm"] == pytest.approx(60.0)
    assert payload["score"]["beat_times"] == list(timing.time_map.beat_times)
    assert payload["beat_times"] == list(timing.time_map.beat_times)
    assert "score time retuned: tempo_scale=0.5" in payload["warnings"]
    assert performance_bpm == pytest.approx(120.0)


def test_double_time_retune_updates_all_derived_state():
    timing = _grid()
    notes = _notes_quarters()
    identity = [source_identity(n) for n in notes]
    performance_beats = list(timing.time_map.beat_times)
    _retune(timing, 2.0)
    assert [source_identity(n) for n in notes] == identity
    assert abs((timing.quality.median_bpm or 0) - 240.0) < 1e-6
    assert abs((timing.performance_median_bpm or 0) - 120.0) < 1e-6
    assert list(timing.performance_beat_times) == performance_beats
    assert len(timing.time_map.beat_times) > len(performance_beats)
    assert list(timing.analysis.beat_times) == list(timing.time_map.beat_times)
    assert _opening_printed_bpm(timing) == 240
    assert score_time_consistency_issues(timing) == []
    payload = timing.to_dict()
    assert payload["retuned"] is True
    assert payload["tempo_scale"] == 2.0
    assert payload["score_median_bpm"] == pytest.approx(240.0)
    assert payload["performance_median_bpm"] == pytest.approx(120.0)


def test_origin_alignment_and_tempo_scale_compose():
    timing = resolve_from_beat_times([0.5 + i * 0.5 for i in range(16)])
    assert abs((timing.quality.median_bpm or 0) - 120.0) < 1e-6
    timing = align_score_origin(
        timing, 0.75, downbeat_times=[2.0, 4.0], beats_per_bar=4
    )
    assert timing.time_map.seconds_to_beats(0.75) == pytest.approx(1.5)
    assert abs((timing.quality.median_bpm or 0) - 120.0) < 1e-6
    assert abs((timing.performance_median_bpm or 0) - 120.0) < 1e-6
    assert timing.tempo_scale == 1.0
    origin_warnings = list(timing.analysis.warnings)
    _retune(timing, 0.5)
    assert abs((timing.quality.median_bpm or 0) - 60.0) < 1e-6
    assert abs((timing.performance_median_bpm or 0) - 120.0) < 1e-6
    assert timing.tempo_scale == 0.5
    assert _opening_printed_bpm(timing) == 60
    assert timing.time_map.seconds_to_beats(0.75) == pytest.approx(0.75)
    assert any("origin translated" in w for w in origin_warnings)
    assert any("tempo_scale=0.5" in w for w in timing.analysis.warnings)
    assert score_time_consistency_issues(timing) == []
    assert maps_logically_equal(timing.analysis.time_map, timing.time_map)


def test_tempo_scale_then_origin_alignment_keeps_score_bpm():
    timing = resolve_from_beat_times([0.5 + i * 0.5 for i in range(16)])
    _retune(timing, 0.5)
    timing = align_score_origin(
        timing, 0.75, downbeat_times=[2.0, 4.0], beats_per_bar=4
    )
    assert timing.tempo_scale == 0.5
    assert abs((timing.quality.median_bpm or 0) - 60.0) < 1e-6
    assert abs((timing.performance_median_bpm or 0) - 120.0) < 1e-6
    assert _opening_printed_bpm(timing) == 60
    assert score_time_consistency_issues(timing) == []
    assert maps_logically_equal(timing.analysis.time_map, timing.time_map)


def test_raw_note_identity_survives_retune_and_midi_sha(tmp_path):
    import hashlib
    import pretty_midi

    notes = _notes_quarters()
    snapshot = [source_identity(n) for n in notes]
    timing = _grid()
    _retune(timing, 0.5)
    assert [source_identity(n) for n in notes] == snapshot
    src = tmp_path / "raw-id.mid"
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(0, name="Piano")
    inst.notes = [
        pretty_midi.Note(80, 60 + i, i * 0.5, i * 0.5 + 0.4) for i in range(8)
    ]
    midi.instruments.append(inst)
    midi.write(str(src))
    original = src.read_bytes()
    pipe = UnderstandingPipeline()
    pipe.transcribe_midi(src, "rawid")
    saved = job_raw_midi_path(src, "rawid").read_bytes()
    assert hashlib.sha256(saved).hexdigest() == hashlib.sha256(original).hexdigest()
    if pipe.last_raw_identity:
        assert (
            pipe.last_raw_identity.get("provider_raw_sha256")
            == pipe.last_raw_identity.get("saved_raw_sha256")
            or pipe.last_raw_identity.get("provider_raw_sha256") is None
        )


def test_meter_events_use_final_score_time_map():
    timing = _grid()
    notes = _notes_quarters()
    _retune(timing, 0.5)
    events = notes_to_events(notes, timing.time_map)
    for ev, note in zip(events, notes):
        assert ev.start_time_sec == note.start_time
        assert ev.end_time_sec == note.end_time
        assert ev.note_id == note.note_id
        assert ev.pitch == note.pitch
        assert ev.start_beat == pytest.approx(
            timing.time_map.seconds_to_beats(note.start_time)
        )
    pipe = UnderstandingPipeline()
    pipe.beat_tracker.last_beat_result = SimpleNamespace(
        beats_per_bar=4, downbeat_times=[2.0, 4.0]
    )
    aligned = pipe._align_score_meter(events, notes, timing, METER)
    assert pipe.last_musical_time_map is timing.time_map
    assert maps_logically_equal(pipe.last_musical_time_map, timing.analysis.time_map)
    for ev, note in zip(aligned, notes):
        assert ev.start_time_sec == note.start_time
        assert ev.start_beat == pytest.approx(
            timing.time_map.seconds_to_beats(note.start_time)
        )
    assert score_time_consistency_issues(timing) == []


def test_printed_score_tempo_follows_half_time_map(tmp_path):
    timing = _grid()
    _retune(timing, 0.5)
    events = [
        MusicalEvent(72, float(i), 1, note_id=str(i)) for i in range(8)
    ]
    printed = [
        {"beat": m.beat, "bpm": m.bpm, "mark": m.mark, "reason": m.reason}
        for m in timing.printed
    ]
    meta = ScoreMeta(
        display_tempo_bpm=int(round(timing.quality.median_bpm or 60)),
        time_sig_hint="4/4",
        extra={"printed_tempo": printed},
    )
    score = NotationWriter().write_from_events_direct(
        events, meta, quantization_mode="performance"
    )
    marks = [m.number for m in score.recurse().getElementsByClass("MetronomeMark")]
    assert marks
    assert marks[0] == 60
    path = tmp_path / "retune.musicxml"
    NotationWriter()._export_musicxml(score, path)
    reparsed = converter.parse(str(path))
    exported = [m.number for m in reparsed.recurse().getElementsByClass("MetronomeMark")]
    assert exported
    assert exported[0] == 60


def test_origin_uses_the_same_apply_helper():
    timing = _grid()
    before_perf = list(timing.performance_beat_times)
    mapped = timing.time_map.for_score(0.25)
    if mapped is timing.time_map:
        mapped = MusicalTimeMap(
            tuple(timing.time_map.beats_to_seconds(i) for i in range(-1, len(timing.time_map.beat_times))),
            source=timing.time_map.source,
        )
    apply_score_time_map(timing, mapped, reason="score origin translated by test")
    assert list(timing.performance_beat_times) == before_perf
    assert maps_logically_equal(timing.time_map, timing.analysis.time_map)
    assert list(timing.analysis.beat_times) == list(timing.time_map.beat_times)
    assert timing.printed
    assert score_time_consistency_issues(timing) == []


def test_tempo_json_keeps_legacy_keys(tmp_path):
    timing = _grid()
    _retune(timing, 0.5)
    path = tmp_path / "job.tempo.json"
    timing.write_json(path)
    import json

    payload = json.loads(path.read_text())
    for key in (
        "backend_used",
        "beat_times",
        "printed_tempo",
        "quality",
        "warnings",
        "performance",
        "score",
        "retuned",
        "tempo_scale",
        "score_median_bpm",
        "performance_median_bpm",
    ):
        assert key in payload
    assert payload["quality"]["median_bpm"] == pytest.approx(60.0)
