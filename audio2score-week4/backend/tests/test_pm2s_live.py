"""Live PM2S tests. Skip unless torch + cloned repo + Zenodo weights are present."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mir.meter import MeterEstimator
from mir.pm2s_hands import Pm2sHandSeparator, pm2s_ready, pm2s_status
from mir.quantizer import MeasureQuantizer
from mir.types import Hand, MusicalEvent


def _ensure_repo(monkeypatch):
    if os.getenv("PM2S_REPO"):
        return
    default = Path(__file__).resolve().parents[3] / "vendor" / "pm2s"
    if default.is_dir():
        monkeypatch.setenv("PM2S_REPO", str(default))


def _ev(pitch, start_beat, dur, *, start_sec, note_id):
    return MusicalEvent(
        pitch=pitch,
        start_beat=start_beat,
        duration_beats=dur,
        velocity=80,
        hand=Hand.UNKNOWN,
        note_id=note_id,
        start_time_sec=start_sec,
        end_time_sec=start_sec + dur * 0.5,
    )


@pytest.fixture
def pm2s_env(monkeypatch):
    _ensure_repo(monkeypatch)
    monkeypatch.setenv("TRANSCRIPTION_HAND_SEPARATOR", "pm2s")
    monkeypatch.setenv("TRANSCRIPTION_QUANTIZATION_MODE", "pm2s")
    monkeypatch.setenv("TRANSCRIPTION_PM2S_REQUIRED", "1")
    if not pm2s_ready():
        pytest.skip(f"PM2S not ready: {pm2s_status()}")


@pytest.mark.pm2s
def test_live_pm2s_hands_assign_without_changing_pitches(pm2s_env):
    events = [
        _ev(48, 0.0, 1.0, start_sec=0.0, note_id="l"),
        _ev(76, 0.0, 0.5, start_sec=0.0, note_id="r"),
        _ev(40, 1.0, 1.0, start_sec=0.5, note_id="l2"),
        _ev(79, 1.0, 0.5, start_sec=0.5, note_id="r2"),
    ]
    sep = Pm2sHandSeparator()
    out = sep.separate(events)
    assert sep.last_source == "pm2s"
    by_id = {e.note_id: e for e in out}
    assert by_id["l"].pitch == 48
    assert by_id["r"].pitch == 76
    assert by_id["l"].hand in (Hand.LEFT, Hand.RIGHT)
    assert by_id["r"].hand in (Hand.LEFT, Hand.RIGHT)
    # Typical piano texture: bass left, treble right.
    assert by_id["l"].hand == Hand.LEFT
    assert by_id["r"].hand == Hand.RIGHT


@pytest.mark.pm2s
def test_live_pm2s_quantizer_rewrites_beats(pm2s_env):
    events = [
        _ev(72, 0.11, 0.37, start_sec=0.05, note_id="r"),
        _ev(48, 0.51, 0.41, start_sec=0.25, note_id="l"),
    ]
    events[1].hand = Hand.LEFT
    q = MeasureQuantizer(mode="pm2s")
    out, decisions = q.quantize(events, MeterEstimator().select(events))
    assert q.last_summary.get("engine") == "pm2s"
    assert all(d.get("reason") == "pm2s_quant" for d in decisions)
    by_id = {e.note_id: e for e in out}
    assert by_id["r"].pitch == 72
    assert by_id["l"].pitch == 48
    assert by_id["r"].start_time_sec == 0.05
    assert len(out) == 2


@pytest.mark.pm2s
def test_health_reports_pm2s_ready(pm2s_env, monkeypatch):
    from main import health

    payload = health()
    assert payload["pm2s"]["importable"] is True
    assert payload["pm2s"]["ready"] is True
    assert payload["pm2s"]["weights"]["hand_part"] is True
    assert payload["pm2s"]["weights"]["quantisation"] is True
    assert payload["pm2s"]["weights"]["beat"] is True
