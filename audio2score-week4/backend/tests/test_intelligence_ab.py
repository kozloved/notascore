"""A/B harness: baseline vs Gemini-enhanced notes on synthetic piano cases."""

from __future__ import annotations

from dataclasses import dataclass

from benchmark.metrics import match_notes
from intelligence.cache import AnalysisCache
from intelligence.config import gemini_config
from intelligence.layer import maybe_enhance
from intelligence.schemas import Correction, GeminiAnalysis
from intelligence.service import GeminiMusicAnalysisService
from mir.cmr_builder import notes_to_events
from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent, ScoreMeta, TempoMap, TempoPoint


@dataclass
class Case:
    name: str
    reference: list[NoteEvent]
    predicted: list[NoteEvent]
    correction: Correction | None


def _n(pitch, start, end, vel=80, conf=0.9):
    return NoteEvent(pitch=pitch, start_time=start, end_time=end, velocity=vel, confidence=conf)


def _tempo():
    return TempoMap(points=[TempoPoint(0.0, 0.0, 100.0, 0.9)])


CASES = [
    Case(
        name="solo_piano",
        reference=[_n(60, 0.0, 0.5), _n(64, 0.5, 1.0), _n(67, 1.0, 1.5)],
        predicted=[_n(60, 0.0, 0.5), _n(64, 0.5, 1.0), _n(67, 1.0, 1.5)],
        correction=None,
    ),
    Case(
        name="piano_with_pedal_ghost_octave",
        reference=[_n(60, 0.0, 0.8), _n(64, 0.0, 0.8)],
        predicted=[
            _n(60, 0.0, 0.8),
            _n(64, 0.0, 0.8),
            _n(88, 0.0, 0.4, vel=18, conf=0.12),
        ],
        correction=Correction(
            type="pitch",
            time_start=0.0,
            time_end=0.4,
            existing_value={"pitch": 88},
            proposed_value={"drop": True},
            confidence=0.99,
            reason="quiet octave ghost",
        ),
    ),
    Case(
        name="simple_melody",
        reference=[_n(72, 0.0, 0.4), _n(74, 0.5, 0.9), _n(76, 1.0, 1.4)],
        predicted=[_n(72, 0.0, 0.4), _n(74, 0.5, 0.9), _n(76, 1.0, 1.4)],
        correction=None,
    ),
    Case(
        name="dense_classical_piano",
        reference=[_n(p, i * 0.25, i * 0.25 + 0.5) for i, p in enumerate((48, 52, 55, 60, 64, 67, 72))],
        predicted=[_n(p, i * 0.25, i * 0.25 + 0.5) for i, p in enumerate((48, 52, 55, 60, 64, 67, 72))],
        correction=None,
    ),
    Case(
        name="stable_tempo",
        reference=[_n(60, 0.0, 0.5), _n(60, 0.5, 1.0), _n(60, 1.0, 1.5)],
        predicted=[_n(60, 0.0, 0.5), _n(60, 0.5, 1.0), _n(60, 1.0, 1.5)],
        correction=None,
    ),
]


class _FakeProvider:
    name = "fake"

    def __init__(self, analysis: GeminiAnalysis):
        self.analysis = analysis

    def analyse(self, packet, **kwargs):
        return self.analysis, {"prompt_tokens": 80, "output_tokens": 40}


def test_ab_gemini_does_not_worsen_clean_cases_and_helps_ghost_octave(tmp_path, monkeypatch):
    monkeypatch.setenv("ENABLE_GEMINI_MUSIC_ANALYSIS", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("ENABLE_GEMINI_AUDIO_INPUT", "0")
    monkeypatch.setenv("TEMP_DIR", str(tmp_path))
    cfg = gemini_config()
    rows = []
    for case in CASES:
        analysis = GeminiAnalysis(
            overall_confidence=0.8,
            corrections=[case.correction] if case.correction else [],
            model="gemini-2.5-flash-lite",
        )
        service = GeminiMusicAnalysisService(
            cfg,
            provider=_FakeProvider(analysis),
            cache=AnalysisCache(cfg),
        )
        tempo = _tempo()
        events = notes_to_events(case.predicted, tempo, instrument=InstrumentKind.PIANO)
        enhanced = maybe_enhance(
            job_id=case.name,
            notes=list(case.predicted),
            events=events,
            meta=ScoreMeta(),
            tempo_map=tempo,
            prediction=InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.9),
            cfg=cfg,
            service=service,
        )
        baseline = match_notes(case.predicted, case.reference)
        gemini = match_notes(enhanced.notes, case.reference)
        rows.append((case.name, baseline.f1, gemini.f1))
        if case.correction is None:
            assert gemini.f1 >= baseline.f1 - 1e-9
        else:
            assert gemini.f1 >= baseline.f1

    ghost = next(r for r in rows if r[0] == "piano_with_pedal_ghost_octave")
    assert ghost[2] > ghost[1]
