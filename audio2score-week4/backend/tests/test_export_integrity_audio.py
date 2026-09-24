"""Audio-stack export integrity. Separated from MIDI-only gates."""

import pytest


@pytest.mark.audio
def test_audio_score_is_not_shifted_twice(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    from audio_engine.madmom_beats import MadmomBeatResult
    from mir.models import MeterDecision, MeterHypothesis
    from mir.pipeline import UnderstandingPipeline
    from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent, TempoMap

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
