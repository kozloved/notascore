"""Musical analysis packet, router, validator, and optional Gemini layer."""

from __future__ import annotations

from dataclasses import dataclass

from intelligence.cache import AnalysisCache
from intelligence.config import gemini_config
from intelligence.costs import estimate_cost
from intelligence.layer import maybe_enhance
from intelligence.packet import build_analysis_packet
from intelligence.patches import apply_note_patches
from intelligence.router import MusicalAnalysisRouter
from intelligence.schemas import Correction, GeminiAnalysis
from intelligence.service import GeminiMusicAnalysisService
from intelligence.validator import MusicalCorrectionValidator
from mir.cmr_builder import notes_to_events
from mir.types import (
    Hand,
    InstrumentKind,
    InstrumentPrediction,
    NoteEvent,
    ScoreMeta,
    TempoMap,
    TempoPoint,
)


def _cfg(tmp_path, **overrides):
    monkey_env = {
        "ENABLE_GEMINI_MUSIC_ANALYSIS": "1",
        "GEMINI_API_KEY": "test-key",
        "ENABLE_GEMINI_AUDIO_INPUT": "0",
        "ENABLE_GEMINI_DEEP_ANALYSIS": "0",
        "TEMP_DIR": str(tmp_path),
    }
    monkey_env.update(overrides)
    return monkey_env


def _notes_simple():
    return [
        NoteEvent(pitch=60, start_time=0.0, end_time=0.5, velocity=90, confidence=0.95),
        NoteEvent(pitch=64, start_time=0.0, end_time=0.5, velocity=80, confidence=0.9),
        NoteEvent(pitch=67, start_time=0.0, end_time=0.5, velocity=80, confidence=0.9),
        NoteEvent(pitch=48, start_time=0.5, end_time=1.0, velocity=70, confidence=0.85),
    ]


def _tempo():
    return TempoMap(points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=120.0, confidence=0.9)])


def _packet(notes=None):
    notes = notes or _notes_simple()
    tempo = _tempo()
    events = notes_to_events(notes, tempo, instrument=InstrumentKind.PIANO)
    pred = InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.85)
    return build_analysis_packet(
        job_id="pkt",
        notes=notes,
        events=events,
        tempo_map=tempo,
        prediction=pred,
        duration_seconds=2.0,
        sample_rate=22050,
    )


def test_packet_summarises_notes_and_uncertainties():
    notes = _notes_simple() + [
        NoteEvent(pitch=72, start_time=0.0, end_time=0.4, velocity=20, confidence=0.2),
    ]
    packet = _packet(notes)
    body = packet.to_dict()
    assert body["transcription"]["note_count"] == 5
    assert body["tempo"]["global_bpm"] == 120.0
    assert body["uncertainties"]["pitch_conflicts"]
    assert body["uncertainties"]["low_confidence_regions"]


def test_router_simple_piano_stays_on_lite():
    from intelligence.config import GeminiConfig
    from pathlib import Path

    cfg = GeminiConfig(
        api_key="x",
        provider="gemini",
        enabled=True,
        audio_input=False,
        deep_analysis=False,
        midi_validation=True,
        structure_analysis=True,
        default_model="gemini-2.5-flash-lite",
        reasoning_model="gemini-2.5-flash",
        auto_apply_threshold=0.9,
        deep_analysis_threshold=0.6,
        manual_review_threshold=0.75,
        max_drop_fraction=0.15,
        cache_ttl_seconds=60,
        cache_dir=Path("/tmp/gemini-test-cache"),
        timeout_seconds=10,
        max_audio_seconds=30,
    )
    decision = MusicalAnalysisRouter(cfg).decide(_packet())
    assert decision.use_lite is True
    assert decision.use_deep is False
    assert decision.complexity < 0.7


def test_validator_rejects_low_confidence_and_applies_octave_drop():
    from intelligence.config import GeminiConfig
    from pathlib import Path

    cfg = GeminiConfig(
        api_key="x",
        provider="gemini",
        enabled=True,
        audio_input=False,
        deep_analysis=False,
        midi_validation=True,
        structure_analysis=True,
        default_model="gemini-2.5-flash-lite",
        reasoning_model="gemini-2.5-flash",
        auto_apply_threshold=0.9,
        deep_analysis_threshold=0.6,
        manual_review_threshold=0.75,
        max_drop_fraction=0.15,
        cache_ttl_seconds=60,
        cache_dir=Path("/tmp/gemini-test-cache"),
        timeout_seconds=10,
        max_audio_seconds=30,
    )
    notes = _notes_simple() + [
        NoteEvent(pitch=72, start_time=0.0, end_time=0.4, velocity=15, confidence=0.15),
    ]
    weak = Correction(
        type="pitch",
        time_start=0.0,
        time_end=0.5,
        existing_value={"pitch": 60},
        proposed_value={"pitch": 61},
        confidence=0.4,
        reason="maybe",
    )
    drop = Correction(
        type="pitch",
        time_start=0.0,
        time_end=0.4,
        existing_value={"pitch": 72},
        proposed_value={"drop": True},
        confidence=0.99,
        reason="quiet octave ghost",
    )
    validator = MusicalCorrectionValidator(cfg)
    accepted, rejected = validator.validate(
        [weak, drop], notes, audio_feature_confidence=0.9
    )
    assert any(c is drop or c.proposed_value.get("drop") for c in accepted)
    assert any(c.confidence == 0.4 for c in rejected)
    patched = apply_note_patches(notes, accepted)
    assert all(n.pitch != 72 for n in patched)


def test_estimate_cost_flash_lite_audio_is_cheap():
    tokens, cost = estimate_cost(
        "gemini-2.5-flash-lite",
        text_chars=4000,
        audio_seconds=180,
        output_tokens=1500,
    )
    assert tokens > 5000
    assert cost < 0.02


def test_maybe_enhance_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_GEMINI_MUSIC_ANALYSIS", "0")
    monkeypatch.setenv("GEMINI_ENABLED", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    notes = _notes_simple()
    tempo = _tempo()
    events = notes_to_events(notes, tempo)
    meta = ScoreMeta()
    result = maybe_enhance(
        job_id="off",
        notes=notes,
        events=events,
        meta=meta,
        tempo_map=tempo,
        prediction=InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.8),
    )
    assert result.skipped is True
    assert result.notes == notes


@dataclass
class _FakeProvider:
    name: str = "fake"
    analysis: GeminiAnalysis | None = None

    def analyse(self, packet, *, model, audio_bytes, audio_mime, task):
        assert audio_bytes is None
        return self.analysis or GeminiAnalysis(), {"prompt_tokens": 100, "output_tokens": 50}


def test_layer_applies_validated_drop(tmp_path, monkeypatch):
    for key, value in _cfg(tmp_path).items():
        monkeypatch.setenv(key, value)
    notes = _notes_simple() + [
        NoteEvent(pitch=72, start_time=0.0, end_time=0.4, velocity=15, confidence=0.15),
    ]
    tempo = _tempo()
    events = notes_to_events(notes, tempo, instrument=InstrumentKind.PIANO)
    cfg = gemini_config()
    drop = Correction(
        type="pitch",
        time_start=0.0,
        time_end=0.4,
        existing_value={"pitch": 72},
        proposed_value={"drop": True},
        confidence=0.99,
        reason="quiet octave ghost",
    )
    fake = _FakeProvider(
        analysis=GeminiAnalysis(overall_confidence=0.8, corrections=[drop], model="gemini-2.5-flash-lite")
    )
    service = GeminiMusicAnalysisService(
        cfg,
        provider=fake,
        cache=AnalysisCache(cfg),
    )
    result = maybe_enhance(
        job_id="on",
        notes=notes,
        events=events,
        meta=ScoreMeta(),
        tempo_map=tempo,
        prediction=InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.9),
        cfg=cfg,
        service=service,
    )
    assert result.skipped is False
    assert result.applied >= 1
    assert all(n.pitch != 72 for n in result.notes)


def test_layer_applies_ghost_drop_tempo_and_key(tmp_path, monkeypatch):
    for key, value in _cfg(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("GEMINI_AUTO_APPLY_THRESHOLD", "0.70")
    notes = _notes_simple() + [
        NoteEvent(pitch=72, start_time=0.0, end_time=0.4, velocity=18, confidence=0.2),
    ]
    tempo = _tempo()
    events = notes_to_events(notes, tempo, instrument=InstrumentKind.PIANO)
    cfg = gemini_config()
    analysis = GeminiAnalysis(
        overall_confidence=0.88,
        corrections=[
            Correction(
                type="pitch",
                time_start=0.0,
                time_end=0.4,
                existing_value={"pitch": 72},
                proposed_value={"drop": True},
                confidence=0.9,
                reason="octave ghost",
            ),
            Correction(
                type="tempo",
                time_start=0.0,
                time_end=0.0,
                existing_value={},
                proposed_value={"bpm": 96},
                confidence=0.9,
                reason="audio tempo",
            ),
            Correction(
                type="key",
                time_start=0.0,
                time_end=0.0,
                existing_value={},
                proposed_value={"key": "C major"},
                confidence=0.9,
                reason="audio key",
            ),
        ],
        model="gemini-2.5-flash",
    )
    result = maybe_enhance(
        job_id="meta",
        notes=notes,
        events=events,
        meta=ScoreMeta(),
        tempo_map=tempo,
        prediction=InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.9),
        cfg=cfg,
        service=GeminiMusicAnalysisService(cfg, provider=_FakeProvider(analysis=analysis), cache=AnalysisCache(cfg)),
    )
    assert result.applied >= 3
    assert all(n.pitch != 72 for n in result.notes)
    assert result.meta.key_hint == "C major"
    assert result.meta.display_tempo_bpm == 96
    assert abs(result.tempo_map.bpm_at(0.0) - 96) < 0.01


def test_cache_avoids_second_provider_call(tmp_path, monkeypatch):
    for key, value in _cfg(tmp_path).items():
        monkeypatch.setenv(key, value)
    cfg = gemini_config()
    calls = {"n": 0}

    class Counting(_FakeProvider):
        def analyse(self, packet, **kwargs):
            calls["n"] += 1
            return super().analyse(packet, **kwargs)

    analysis = GeminiAnalysis(overall_confidence=0.7, corrections=[], model="gemini-2.5-flash-lite")
    service = GeminiMusicAnalysisService(cfg, provider=Counting(analysis=analysis))
    packet = _packet()
    first = service.analyse_music(packet, job_id="cache-job")
    second = service.analyse_music(packet, job_id="cache-job")
    assert calls["n"] == 1
    assert second.cache_hit is True
    assert first.overall_confidence == 0.7


def test_provider_failure_does_not_break_pipeline(tmp_path, monkeypatch):
    for key, value in _cfg(tmp_path).items():
        monkeypatch.setenv(key, value)
    cfg = gemini_config()

    class Boom(_FakeProvider):
        def analyse(self, packet, **kwargs):
            raise RuntimeError("quota")

    notes = _notes_simple()
    tempo = _tempo()
    events = notes_to_events(notes, tempo)
    result = maybe_enhance(
        job_id="boom",
        notes=notes,
        events=events,
        meta=ScoreMeta(),
        tempo_map=tempo,
        prediction=InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.8),
        cfg=cfg,
        service=GeminiMusicAnalysisService(cfg, provider=Boom()),
    )
    assert result.notes == notes
    assert result.applied == 0
    assert result.skipped is True
    assert result.meta.extra.get("gemini", {}).get("skipped") is True


def test_audio_timeout_retries_json_only(tmp_path, monkeypatch):
    import numpy as np
    from audio_engine.normalizer import NormalizedAudio

    for key, value in _cfg(tmp_path, ENABLE_GEMINI_AUDIO_INPUT="1").items():
        monkeypatch.setenv(key, value)
    cfg = gemini_config()
    calls = {"audio": 0, "json": 0}

    class TimeoutThenOk(_FakeProvider):
        def analyse(self, packet, *, model, audio_bytes, audio_mime, task):
            if audio_bytes:
                calls["audio"] += 1
                raise TimeoutError("The read operation timed out")
            calls["json"] += 1
            return (
                GeminiAnalysis(overall_confidence=0.77, model=model),
                {"prompt_tokens": 10, "output_tokens": 5},
            )

    service = GeminiMusicAnalysisService(cfg, provider=TimeoutThenOk())
    audio = NormalizedAudio(
        samples=np.zeros(2205, dtype=np.float32),
        sample_rate=22050,
    )
    out = service.analyse_music(_packet(), job_id="timeout", normalized=audio)
    assert calls["audio"] == 1
    assert calls["json"] == 1
    assert out.overall_confidence == 0.77
