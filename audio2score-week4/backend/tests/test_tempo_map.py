"""Tests for TempoMap and BeatTracker."""

from audio_engine.beat_tracker import (
    BeatTracker,
    align_tempo_map,
    fit_constant_beat_grid,
    stabilize_tempo_map,
)
from mir.cmr_builder import notes_to_events
from mir.types import InstrumentKind, MusicalEvent, NoteEvent, ScoreMeta, TempoMap, TempoPoint
from notation_engine.writer import NotationWriter


def test_tempo_map_origin_puts_first_note_on_beat_zero():
    tm = TempoMap(
        points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=40.0)],
        origin_sec=0.012,
    )
    assert abs(tm.seconds_to_beats(0.012)) < 1e-9
    assert abs(tm.seconds_to_beats(1.512) - 1.0) < 1e-6
    assert abs(tm.beats_to_seconds(0.0) - 0.012) < 1e-9
    assert abs(tm.beats_to_seconds(1.0) - 1.512) < 1e-6


def test_tempo_map_seconds_to_beats_constant():
    tm = TempoMap(points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0)])
    assert abs(tm.seconds_to_beats(1.0) - 2.0) < 0.01


def test_tempo_map_bpm_at():
    tm = TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=100.0),
            TempoPoint(time_sec=2.0, beat=2.0, bpm=140.0),
        ]
    )
    assert tm.bpm_at(0.0) == 100.0
    assert tm.bpm_at(2.5) == 140.0


def test_tempo_map_beats_to_seconds_roundtrip():
    tm = TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0),
            TempoPoint(time_sec=2.0, beat=4.0, bpm=60.0),
        ]
    )
    for t in (0.0, 0.5, 2.0, 3.5):
        beat = tm.seconds_to_beats(t)
        assert abs(tm.beats_to_seconds(beat) - t) < 1e-6


def test_notes_to_events_uses_local_tempo():
    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=80),
        NoteEvent(pitch=64, start_time=3.0, end_time=4.0, velocity=80),
    ]
    tm = TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0),
            TempoPoint(time_sec=2.0, beat=4.0, bpm=60.0),
        ]
    )
    events = notes_to_events(notes, tm, instrument=InstrumentKind.PIANO)
    assert abs(events[0].duration_beats - 1.0) < 0.01
    # 2s at 120bpm = 4 beats, then 1s at 60bpm = 1 beat → start 5
    assert abs(events[1].start_beat - 5.0) < 0.01
    assert abs(events[1].duration_beats - 1.0) < 0.01


def test_stabilize_tempo_map_merges_jitter():
    points = [TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0)]
    bpm = 120.0
    for i in range(1, 16):
        bpm = 120.0 + (3.0 if i % 2 else -2.0)
        points.append(TempoPoint(time_sec=i * 0.5, beat=float(i), bpm=bpm))
    stable = stabilize_tempo_map(TempoMap(points=points), min_hold_sec=2.0)
    assert len(stable.points) == 1
    assert abs(stable.points[0].bpm - 120.0) < 5


def test_stabilize_tempo_map_keeps_real_change():
    points = []
    for i in range(8):
        points.append(TempoPoint(time_sec=i * 0.5, beat=float(i), bpm=100.0))
    for i in range(8, 16):
        points.append(TempoPoint(time_sec=i * 0.5, beat=float(i), bpm=150.0))
    stable = stabilize_tempo_map(
        TempoMap(points=points), min_change_ratio=0.08, min_hold_sec=2.0
    )
    assert len(stable.points) >= 2
    assert stable.bpm_at(0.2) < 120
    assert stable.bpm_at(6.0) > 130


def test_align_tempo_map_scales_regions():
    tm = TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=100.0),
            TempoPoint(time_sec=2.0, beat=0.0, bpm=80.0),
        ]
    )
    aligned = align_tempo_map(tm, 120.0)
    assert abs(aligned.bpm_at(0.0) - 120.0) < 0.01
    assert abs(aligned.bpm_at(2.0) - 96.0) < 0.01


def test_notation_inserts_tempo_change_marks():
    events = [
        MusicalEvent(pitch=60, start_beat=0.0, duration_beats=1.0, velocity=80),
        MusicalEvent(pitch=64, start_beat=8.0, duration_beats=1.0, velocity=80),
    ]
    tm = TempoMap(
        points=[
            TempoPoint(time_sec=0.0, beat=0.0, bpm=80.0),
            TempoPoint(time_sec=4.0, beat=5.333, bpm=160.0),
        ]
    )
    meta = ScoreMeta(display_tempo_bpm=80, tempo_map=tm)
    score = NotationWriter().write_from_events_direct(events, meta)
    marks = list(score.recurse().getElementsByClass("MetronomeMark"))
    numbers = {int(m.number) for m in marks if m.number}
    assert 80 in numbers
    assert any(n >= 150 for n in numbers)
    xml = score.write("musicxml")
    text = open(str(xml), encoding="utf-8").read()
    assert "<per-minute>80</per-minute>" in text.replace(" ", "")
    assert "<metronome" in text.lower()


def test_beat_tracker_returns_map(sine_tone, normalized_audio_factory):
    _, y = sine_tone(freq_hz=440, duration_sec=2.0)
    audio = normalized_audio_factory(y)
    tm = BeatTracker().track(audio)
    assert len(tm.points) >= 1
    assert tm.points[0].bpm > 0


def test_fit_constant_beat_grid_demo_melody_is_quarters():
    """Case1 demo WAV onsets (~1.5s IOI) stay at 80 or 160, not 40."""
    onsets = [0.012, 1.544, 2.997, 4.507, 5.995]
    tm = fit_constant_beat_grid(onsets, seed_bpm=80.0)
    bpm = tm.bpm_at(0.0)
    assert 76.0 <= bpm <= 164.0
    assert abs(bpm - 40.0) > 10.0
    beats = [tm.seconds_to_beats(t) for t in onsets]
    assert abs(beats[0]) < 0.05
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    # Half notes at 80 (gap 2) or whole notes at 160 (gap 4).
    assert all(abs(g - gaps[0]) < 0.12 for g in gaps)
    assert min(abs(gaps[0] - 2.0), abs(gaps[0] - 4.0)) < 0.12


def test_fit_constant_beat_grid_ignores_spurious_half_pulses():
    """Extra off-grid attacks must not fold 80/160 down to 40 BPM."""
    onsets = [0.012, 1.544, 2.997, 4.507, 5.995, 9.003, 9.746, 11.489, 13.185]
    tm = fit_constant_beat_grid(onsets, seed_bpm=80.0)
    bpm = tm.bpm_at(0.0)
    assert 76.0 <= bpm <= 164.0
    beats = [tm.seconds_to_beats(t) for t in onsets[:5]]
    gaps = [b - a for a, b in zip(beats, beats[1:])]
    assert min(abs(gaps[0] - 2.0), abs(gaps[0] - 4.0)) < 0.15
