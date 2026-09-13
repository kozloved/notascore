"""Detected audio downbeats must survive score-origin and tempo interpretation."""
from types import SimpleNamespace

import pytest

from mir.cmr_builder import notes_to_events
from mir.meter import meter_from_time_signature
from mir.pipeline import UnderstandingPipeline
from mir.score_interpretation import scaled_time_map
from mir.types import NoteEvent
from timing.service import resolve_from_beat_times
from timing.tempo_map import MusicalTimeMap


def test_half_time_fractional_downbeat_becomes_bar_start():
    original = MusicalTimeMap.from_beat_times([0.5 + i * 0.5 for i in range(20)])
    half = scaled_time_map(original, 0.5)
    mapped = half.for_score(0.75, downbeat_times=[2.0, 4.0, 6.0], beats_per_bar=2)
    for second in [2.0, 4.0, 6.0]:
        assert mapped.seconds_to_beats(second) % 2 == pytest.approx(0)
    assert mapped.seconds_to_beats(0.75) == pytest.approx(0.75)


def test_fractional_origin_preserves_rubato_at_every_knot():
    original = MusicalTimeMap.from_beat_times([0.1, 0.6, 1.2, 1.9, 2.4, 3.0, 3.7, 4.2])
    half = scaled_time_map(original, 0.5)
    mapped = half.for_score(0.2, downbeat_times=[0.6, 3.0], beats_per_bar=2)
    offset = mapped.seconds_to_beats(0.2) - original.seconds_to_beats(0.2) * 0.5
    for second in [0.0, 0.2, 0.6, 0.85, 1.2, 1.5, 2.4, 3.0, 3.7, 4.5]:
        expected = original.seconds_to_beats(second) * 0.5 + offset
        assert mapped.seconds_to_beats(second) == pytest.approx(expected)
        assert mapped.beats_to_seconds(expected) == pytest.approx(second)


def test_compound_grouping_downbeats_drive_selected_score_meter():
    timing = resolve_from_beat_times([0.25 + i * 0.5 for i in range(14)])
    notes = [NoteEvent(60 + i, t, t + 0.2, note_id=str(i))
             for i, t in enumerate([0.75, 1.25, 2.75, 4.25])]
    pipe = UnderstandingPipeline()
    pipe.beat_tracker.last_beat_result = SimpleNamespace(
        beats_per_bar=4, downbeat_times=[0.25, 2.25, 4.25],
        grouping_beats_per_bar=6,
        grouping_beat_times=[0.25 + i * 0.25 for i in range(25)],
        grouping_positions=[5, 6, 1, 2, 3, 4] * 4 + [5],
    )
    events = pipe._align_score_meter(notes_to_events(notes, timing.time_map), notes,
                                     timing, meter_from_time_signature('6/8'))
    for second in [0.75, 2.25, 3.75]:
        assert timing.time_map.seconds_to_beats(second) % 3 == pytest.approx(0)
    assert events[0].start_beat == pytest.approx(0)
    for event in events:
        assert event.start_beat == pytest.approx(timing.time_map.seconds_to_beats(event.start_time_sec))


def test_first_downbeat_after_silence_starts_first_measure():
    source = MusicalTimeMap.from_beat_times([0.25 + i * 0.5 for i in range(20)])
    mapped = source.for_score(2.25, downbeat_times=[2.25, 4.25, 6.25], beats_per_bar=4)
    assert mapped.seconds_to_beats(2.25) == pytest.approx(0)


def test_real_pickup_stays_before_first_full_bar():
    source = MusicalTimeMap.from_beat_times([0.25 + i * 0.5 for i in range(20)])
    mapped = source.for_score(1.75, downbeat_times=[2.25, 4.25, 6.25], beats_per_bar=4)
    assert mapped.seconds_to_beats(1.75) == pytest.approx(3)
    assert mapped.seconds_to_beats(2.25) == pytest.approx(4)


def test_inconsistent_downbeats_do_not_rotate_score():
    source = MusicalTimeMap.from_beat_times([0.25 + i * 0.5 for i in range(20)])
    assert source.for_score(0.75, downbeat_times=[1.25, 2.25, 4.25], beats_per_bar=3) is source


def test_early_opening_attack_does_not_add_a_bar():
    timing = resolve_from_beat_times([0.19 + i * 0.35 for i in range(18)])
    notes = [NoteEvent(60, 0.174, 0.5, note_id='early'),
             NoteEvent(64, 1.24, 1.6, note_id='bar2')]
    pipe = UnderstandingPipeline()
    pipe.beat_tracker.last_beat_result = SimpleNamespace(
        beats_per_bar=3, downbeat_times=[0.19, 1.24, 2.29, 3.34])
    events = pipe._align_score_meter(notes_to_events(notes, timing.time_map), notes,
                                     timing, meter_from_time_signature('3/4'))
    assert events[0].start_beat == pytest.approx(0)
    assert events[0].start_time_sec == 0.174
    assert events[1].start_beat == pytest.approx(3)
    assert timing.time_map.beats_to_seconds(0) == pytest.approx(0.19)


def test_notation_cost_cannot_override_consistent_audio_bars():
    from mir.score_interpretation import evaluate_candidates
    timing = resolve_from_beat_times([0.19 + i * 0.35 for i in range(24)])
    notes = [NoteEvent(60, 0.19 + i * 0.35, 0.4 + i * 0.35, note_id=str(i)) for i in range(20)]
    pipe = UnderstandingPipeline()
    pipe.beat_tracker.last_beat_result = SimpleNamespace(
        beats_per_bar=3, downbeat_times=[0.19, 1.24, 2.29, 3.34, 4.39],
        grouping_beat_times=[0.19 + i * 0.35 for i in range(24)],
        grouping_positions=[1, 2, 3, 4, 5, 6] * 4)
    candidates = evaluate_candidates(notes, timing.time_map)
    eligible = pipe._downbeat_candidates(candidates, timing)
    assert eligible is not candidates
    assert not any(c.meter == '4/4' for c in eligible)
    assert not any(c.meter == '12/8' for c in eligible)
    assert any(c.meter == '6/8' and c.tempo_scale == 0.5 for c in eligible)
    assert any(c.meter == '3/4' and c.tempo_scale == 1 for c in eligible)


def test_polyphonic_audio_to_musicxml_keeps_detected_bar_phase(tmp_path, monkeypatch):
    import hashlib
    import numpy as np
    import pretty_midi
    import soundfile as sf
    from music21 import converter
    from audio_engine.madmom_beats import result_from_beat_array
    from mir.midi_ingest import ingest_midi
    from mir.types import InstrumentKind, InstrumentPrediction
    from notation_engine.integrity import score_attacks

    raw = tmp_path / 'provider.mid'
    midi = pretty_midi.PrettyMIDI(resolution=960)
    instrument = pretty_midi.Instrument(0)
    instrument.notes = [pretty_midi.Note(80, 51, .04, .17)]
    instrument.notes += [pretty_midi.Note(90, 42 if i % 3 == 0 else 60, .2 + i * .35, .5 + i * .35)
                         for i in range(18)]
    midi.instruments.append(instrument)
    midi.write(str(raw))
    raw_bytes = raw.read_bytes()
    ingested = ingest_midi(raw, source_backend='mt3')

    def transcribe(backend, path):
        backend.last_midi_bytes = raw_bytes
        backend.last_performance = ingested.performance
        backend.last_provider_raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        return list(ingested.notes)

    def track(tracker, audio):
        times = [.19 + i * .35 for i in range(21)]
        result = result_from_beat_array(np.column_stack([times, [1, 2, 3] * 7]))
        tracker.last_beat_result = result
        tracker.last_beat_times = times
        tracker.last_source = 'madmom'
        tracker.last_time_signature = '3/4'
        return result.tempo_map

    monkeypatch.setattr('adapters.mt3_backend.MT3Backend.transcribe_notes', transcribe)
    monkeypatch.setattr('audio_engine.beat_tracker.BeatTracker.track', track)
    monkeypatch.setattr('audio_engine.instrument_classifier.InstrumentClassifier.classify',
                        lambda *_: InstrumentPrediction(InstrumentKind.PIANO, .9))
    monkeypatch.setattr('mir.pipeline.AudioSegmenter.segment', lambda *_: [])
    monkeypatch.setenv('TRANSCRIPTION_USE_PIANO_ANALYZER', '0')
    source = tmp_path / 'poly.wav'
    sf.write(source, np.zeros(22050 * 8), 22050)
    pipe = UnderstandingPipeline(backend_name='mt3', mode='polyphonic', validation_mode='strict_safe')
    xml = pipe.transcribe(source, 'bar-alignment')
    score = converter.parse(xml, format='musicxml')
    attacks = score_attacks(score)
    meter = pipe.job.structure.selected_meter
    assert meter.time_signature == '3/4'
    assert len(attacks) == len(ingested.notes)
    bass_attacks = sorted(a.start for a in attacks if a.pitch == 42)
    assert bass_attacks == pytest.approx([3 + i * 3 for i in range(6)])
    for t in pipe._score_downbeats(pipe.last_timing, meter):
        beat = pipe.last_musical_time_map.seconds_to_beats(t)
        assert beat / 3 == pytest.approx(round(beat / 3))
    assert (tmp_path / 'bp_bar-alignment' / 'bar-alignment.raw.mid').read_bytes() == raw_bytes
    import json
    timing = json.loads((tmp_path / 'bp_bar-alignment' / 'bar-alignment.tempo.json').read_text())
    assert timing['selected_meter'] == '3/4'
