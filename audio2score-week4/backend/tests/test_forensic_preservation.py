"""Forensic preservation metrics and STRICT_SAFE overlap / piano contracts."""

from __future__ import annotations

import numpy as np

from audio_engine.normalizer import NormalizedAudio
from audio_engine.piano_analyzer import PianoAudioAnalyzer
from evaluation.preservation import compare_to_raw, quantization_report, stage_preservation_bundle
from evaluation.stage_diff import format_stage_diff
from mir.midi_cleaner import MIDICleaner
from mir.pipeline_config import ValidationMode
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent, NoteEvent
from mir.meter import MeterEstimator


def _n(pitch, start, end, vel=80, conf=0.9, note_id=""):
    return NoteEvent(
        pitch=pitch,
        start_time=start,
        end_time=end,
        velocity=vel,
        confidence=conf,
        note_id=note_id,
    )


def test_preservation_strict_safe_keeps_octave_and_grace():
    raw = [
        _n(48, 0.0, 1.0, vel=80, note_id="a"),
        _n(60, 0.0, 1.0, vel=28, note_id="b"),
        _n(71, 1.0, 1.03, vel=88, note_id="c"),
        _n(72, 1.10, 1.50, vel=80, note_id="d"),
    ]
    cleaned = MIDICleaner(mode=ValidationMode.STRICT_SAFE).clean(raw)
    report = compare_to_raw(raw, cleaned)
    assert report.deleted_from_raw == 0
    assert report.added_vs_raw == 0
    assert report.pitch_changed_vs_raw == 0
    assert report.onset_changed_vs_raw == 0
    assert report.duration_changed_vs_raw == 0
    assert report.raw_event_preservation_rate == 1.0


def test_preservation_detects_overlap_trim_as_duration_change():
    raw = [
        _n(60, 0.0, 1.0, vel=80, note_id="a"),
        _n(60, 0.4, 1.2, vel=70, note_id="b"),
    ]
    legacy = MIDICleaner().clean(raw)
    report = compare_to_raw(raw, legacy)
    assert report.deleted_from_raw == 0
    assert report.duration_changed_vs_raw == 1


def test_stage_diff_text_mentions_zero_deletes():
    raw = [_n(60, 0.103, 0.410, note_id="a"), _n(64, 0.487, 0.801, note_id="b")]
    events = [
        MusicalEvent(
            pitch=n.pitch,
            start_beat=n.start_time * 2.0,
            duration_beats=(n.end_time - n.start_time) * 2.0,
            velocity=n.velocity,
            note_id=n.note_id,
            start_time_sec=n.start_time,
            end_time_sec=n.end_time,
            hand=Hand.RIGHT,
        )
        for n in raw
    ]
    bundle = stage_preservation_bundle(
        raw_notes=raw,
        validated_notes=raw,
        structured_events=events,
        quantized_events=events,
        fallback_bpm=120.0,
    )
    text = format_stage_diff(bundle)
    assert "deleted: 0" in text
    assert "raw_note_count: 2" in text
    assert "STRUCTURED → QUANTIZED" in text


def test_quantization_report_counts_moved_events():
    events = [
        MusicalEvent(
            pitch=72,
            start_beat=i * 0.25,
            duration_beats=0.22,
            note_id=f"n{i}",
            start_time_sec=i * 0.125,
            end_time_sec=i * 0.125 + 0.11,
        )
        for i in range(8)
    ]
    meter = MeterEstimator().select(events)
    quantized, _ = MeasureQuantizer().quantize(events, meter)
    report = quantization_report(events, quantized)
    assert report.notes_deleted == 0
    assert report.quantized_event_count == 8
    assert report.count_drop_warning is False


def test_piano_analyzer_metadata_does_not_mutate_notes():
    sr = 22050
    t = np.linspace(0, 1.0, sr, endpoint=False)
    audio = NormalizedAudio(samples=(0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sample_rate=sr)
    notes = [
        _n(60, 0.0, 0.4, vel=80, note_id="a"),
        _n(64, 0.4, 0.8, vel=40, note_id="b"),
    ]
    analysis = PianoAudioAnalyzer().analyze(audio, notes, mutate_velocity=False)
    assert [n.velocity for n in analysis.notes] == [80, 40]
    assert [n.pitch for n in analysis.notes] == [60, 64]
    assert [n.start_time for n in analysis.notes] == [0.0, 0.4]
    assert len(analysis.velocity_suggestions) == 2
    mutated = PianoAudioAnalyzer().analyze(audio, notes, mutate_velocity=True)
    assert [n.velocity for n in mutated.notes] != [80, 40]
