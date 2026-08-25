"""madmom downbeat parsing, BPM family refine, optional AudioSet taggers."""

from __future__ import annotations

import numpy as np
import pytest

from audio_engine.madmom_beats import madmom_available, result_from_beat_array
from audio_engine.audioset_tagger import audioset_enabled, audioset_status, _family_scores
from mir.types import InstrumentKind
from transcription import refine_tempo


def test_madmom_parses_four_four_click_array():
    times = np.arange(0.0, 4.0, 0.5)
    pos = np.array([1, 2, 3, 4, 1, 2, 3, 4], dtype=float)
    tracked = np.column_stack([times, pos])
    result = result_from_beat_array(tracked)
    assert result is not None
    assert result.time_signature == "4/4"
    assert abs(result.bpm - 120.0) < 1.0
    assert result.downbeat_times[0] == pytest.approx(0.0)
    assert result.tempo_map.bpm_at(0.0) == pytest.approx(120.0, abs=1.0)


def test_madmom_parses_six_beat_array_as_compound_grouping():
    """A 6-state DBN output is grouping evidence for compound meter, not a final meter."""
    times = np.arange(0.0, 3.0, 0.25)
    pos = np.array([1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6], dtype=float)
    result = result_from_beat_array(np.column_stack([times, pos]))
    assert result is not None
    assert result.beats_per_bar == 6
    assert result.grouping_beats_per_bar == 6
    assert result.time_signature == "6/8"
    assert result.grouping_meter == "6/8"
    assert result.downbeat_times[0] == pytest.approx(0.0)
    from audio_engine.madmom_beats import GROUP_BEATS_PER_BAR

    assert GROUP_BEATS_PER_BAR == [3, 4, 6]


def test_madmom_parses_three_four_array():
    times = np.arange(0.0, 3.0, 0.5)
    pos = np.array([1, 2, 3, 1, 2, 3], dtype=float)
    result = result_from_beat_array(np.column_stack([times, pos]))
    assert result is not None
    assert result.time_signature == "3/4"
    assert abs(result.bpm - 120.0) < 1.0


def test_refine_tempo_recovers_120_from_76_seed():
    onsets = [i * 0.5 for i in range(8)]
    bpm = refine_tempo(onsets, 76.0)
    assert abs(bpm - 120.0) < 3.0


def test_refine_tempo_recovers_120_from_150_seed():
    onsets = [i * 0.5 for i in range(8)]
    bpm = refine_tempo(onsets, 150.0)
    assert abs(bpm - 120.0) < 3.0


def test_audioset_disabled_by_default():
    assert audioset_enabled() is False
    status = audioset_status()
    assert status["enabled"] is False


def test_audioset_family_mapping():
    scores = _family_scores(
        {
            "Piano": 0.8,
            "Speech": 0.1,
            "Acoustic guitar": 0.05,
            "Drum kit": 0.02,
        }
    )
    assert scores[InstrumentKind.PIANO] == pytest.approx(0.8)
    assert scores[InstrumentKind.VOICE] == pytest.approx(0.1)


def test_build_tempo_map_keeps_madmom_without_midi_refine():
    from mir.pipeline import UnderstandingPipeline
    from mir.types import TempoMap, TempoPoint

    pipeline = UnderstandingPipeline()
    pipeline.beat_tracker.track_stable = lambda audio: TempoMap(
        points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=150.0, confidence=0.9)]
    )
    pipeline.beat_tracker.last_source = "madmom"
    pipeline.beat_tracker.last_time_signature = "4/4"
    tempo_map, meter = pipeline._build_tempo_map(
        None, None, [i * 0.5 for i in range(8)]
    )
    assert meter == "4/4"
    assert abs(tempo_map.bpm_at(0.0) - 150.0) < 0.5


def test_build_tempo_map_refines_librosa_octave_seed():
    from mir.pipeline import UnderstandingPipeline
    from mir.types import TempoMap, TempoPoint

    pipeline = UnderstandingPipeline()
    pipeline.beat_tracker.track_stable = lambda audio: TempoMap(
        points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=76.0, confidence=0.7)]
    )
    pipeline.beat_tracker.last_source = "librosa"
    pipeline.beat_tracker.last_time_signature = None
    tempo_map, meter = pipeline._build_tempo_map(
        None, None, [i * 0.5 for i in range(8)]
    )
    assert meter is None
    assert abs(tempo_map.bpm_at(0.0) - 120.0) < 3.0


def test_packet_uses_madmom_time_sig_hint():
    from intelligence.packet import build_analysis_packet
    from mir.cmr_builder import notes_to_events
    from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent, TempoMap, TempoPoint

    notes = [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=80, confidence=1.0),
        NoteEvent(pitch=64, start_time=0.5, end_time=1.0, velocity=80, confidence=1.0),
    ]
    tempo = TempoMap(points=[TempoPoint(0.0, 0.0, 120.0, 0.9)])
    events = notes_to_events(notes, tempo, instrument=InstrumentKind.PIANO)
    packet = build_analysis_packet(
        job_id="meter-hint",
        notes=notes,
        events=events,
        tempo_map=tempo,
        prediction=InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.9),
        time_sig_hint="3/4",
    )
    assert packet.meter["time_signature_candidates"][0]["name"] == "3/4"
    assert packet.meter["time_signature_candidates"][0]["confidence"] == pytest.approx(0.9)


def test_beat_status_includes_audioset_and_backend():
    from audio_engine.beat_tracker import beat_status

    status = beat_status()
    assert status["backend"] == "madmom"
    assert "madmom_available" in status
    assert status["audioset"]["enabled"] is False


@pytest.mark.skipif(not madmom_available(), reason="madmom not installed")
def test_madmom_live_click_track_120_four_four(normalized_audio_factory, sample_rate):
    from audio_engine.beat_tracker import BeatTracker

    dur = 6.0
    t = np.arange(int(sample_rate * dur)) / sample_rate
    y = np.zeros_like(t, dtype=np.float32)
    beat = 0.5
    for i, bt in enumerate(np.arange(0, dur - 0.05, beat)):
        n0 = int(bt * sample_rate)
        n1 = min(len(y), n0 + int(0.012 * sample_rate))
        y[n0:n1] = 0.95 if i % 4 == 0 else 0.4
    audio = normalized_audio_factory(y)
    tracker = BeatTracker()
    tempo_map = tracker.track(audio)
    assert tracker.last_source == "madmom"
    assert tracker.last_time_signature == "4/4"
    assert abs(tempo_map.bpm_at(0.0) - 120.0) < 8.0
