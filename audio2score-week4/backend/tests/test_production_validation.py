"""Live production validation: smoke routing, provider SHA identity, provenance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from evaluation.production_smoke.check import (
    SmokeFailure,
    assert_health_cutover,
    assert_job_mode,
    assert_live_provenance,
    assert_polyphonic_backend,
    resolve_mode,
    upload_form_fields,
)
from mir.raw_identity import RAW_IDENTITY_VIOLATION, sha256_hex
from transcription import TranscriptionError


def _midi_bytes(pitch: int = 60) -> bytes:
    import tempfile

    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=0)
    inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=0.0, end=0.5))
    midi.instruments.append(inst)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "n.mid"
        midi.write(str(path))
        return path.read_bytes()


def test_smoke_upload_fields_include_polyphonic_mode():
    fields = dict(upload_form_fields(mode="polyphonic", audio_path="./full-song.wav"))
    assert fields["mode"] == "polyphonic"
    assert fields["file"].startswith("@./full-song.wav")


def test_smoke_mode_aliases_and_unknown():
    assert resolve_mode("poly") == "polyphonic"
    assert resolve_mode("quality") == "polyphonic"
    assert resolve_mode("fast") == "solo"
    assert resolve_mode(None) == "solo"
    with pytest.raises(SmokeFailure, match="Unknown MODE"):
        resolve_mode("ultra")


def test_smoke_script_sends_mode_form_field():
    script = Path(__file__).resolve().parents[2] / "deploy" / "smoke-nextgen-live.sh"
    text = script.read_text(encoding="utf-8")
    assert '-F "mode=${MODE}"' in text
    assert "MODE:-solo" in text
    helper = (
        Path(__file__).resolve().parents[1]
        / "evaluation"
        / "production_smoke"
        / "check.py"
    ).read_text(encoding="utf-8")
    assert "Cannot run polyphonic smoke" in helper
    assert "MT3 backend is not configured/available" in helper


def test_polyphonic_smoke_requires_mt3_health():
    health = {
        "nextgen": {
            "pipeline_mode": "live",
            "orchestrator_active": True,
            "separation_enabled": False,
            "stem_transcription_enabled": False,
            "fusion_enabled": False,
            "ensemble_render_enabled": False,
        },
        "modes": {"solo": True, "polyphonic": False},
        "polyphonic": {"available": False},
    }
    assert_health_cutover(health)
    with pytest.raises(SmokeFailure, match="MT3 backend is not configured"):
        assert_polyphonic_backend(health)


def test_smoke_job_mode_must_match_request():
    with pytest.raises(SmokeFailure, match="job mode = solo"):
        assert_job_mode({"mode": "solo", "status": "completed"}, "polyphonic")
    assert_job_mode({"mode": "polyphonic"}, "polyphonic")


def test_mt3_hashes_provider_bytes_before_parse(tmp_path, monkeypatch):
    from adapters.mt3_backend import MT3Backend
    from mir.midi_ingest import ingest_midi

    raw_provider_bytes = _midi_bytes(64)
    backend = MT3Backend()
    order = []
    original = ingest_midi

    def wrapped(path, **kwargs):
        order.append("ingest")
        assert backend.last_midi_bytes == raw_provider_bytes
        assert backend.last_provider_raw_sha256 == sha256_hex(raw_provider_bytes)
        return original(path, **kwargs)

    monkeypatch.setattr("adapters.mt3_backend.ingest_midi", wrapped)
    notes = backend._decode(raw_provider_bytes)
    assert order == ["ingest"]
    assert [n.pitch for n in notes] == [64]
    assert backend.last_provider_raw_sha256 == hashlib.sha256(
        raw_provider_bytes
    ).hexdigest()


def test_provider_sha_matches_saved_raw_mid(tmp_path, monkeypatch):
    from engine.job_runner import run_job
    from mir.raw_midi import job_raw_midi_path
    from tests.test_live_cutover import _cutover_env
    from tests.test_live_orchestrator_job import _Counters, _install_mocks, _wav

    _cutover_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "song.wav")
    run_job(audio, "id1", mode="polyphonic", filename="song.wav")
    raw_provider_bytes = counters.midi_bytes
    saved = job_raw_midi_path(audio, "id1").read_bytes()
    assert saved == raw_provider_bytes
    assert sha256_hex(raw_provider_bytes) == hashlib.sha256(saved).hexdigest()
    prov = json.loads((tmp_path / "bp_id1" / "id1.provenance.json").read_text())
    tr = prov["transcription"]
    assert tr["backend"] == "mt3"
    assert tr["provider_raw_sha256"] == sha256_hex(raw_provider_bytes)
    assert tr["saved_raw_sha256"] == sha256_hex(saved)
    assert tr["raw_identity_match"] is True
    dumped = json.dumps(prov)
    assert "MT3_API_KEY" not in dumped
    assert "super-secret" not in dumped


def test_mutated_provider_byte_is_identity_violation(tmp_path, monkeypatch):
    from engine.job_runner import run_job
    from tests.test_live_cutover import _cutover_env
    from tests.test_live_orchestrator_job import _Counters, _install_mocks, _wav

    _cutover_env(monkeypatch)
    counters = _Counters()
    ingested = _install_mocks(monkeypatch, tmp_path, counters)
    original = counters.midi_bytes
    provider_sha = hashlib.sha256(original).hexdigest()
    mutated = bytearray(original)
    mutated[-1] ^= 0x01

    def fake_mt3(self, path):
        counters.mt3 += 1
        self.last_midi_bytes = bytes(mutated)
        self.last_provider_raw_sha256 = provider_sha
        self.last_performance = ingested.performance
        self.last_timing = {"wall_ms": 1.0}
        return list(ingested.notes)

    monkeypatch.setattr("adapters.mt3_backend.MT3Backend.transcribe_notes", fake_mt3)
    audio = _wav(tmp_path / "song.wav")
    with pytest.raises(TranscriptionError, match=RAW_IDENTITY_VIOLATION) as exc:
        run_job(audio, "bad-id", mode="polyphonic", filename="song.wav")
    assert exc.value.code == RAW_IDENTITY_VIOLATION
    assert exc.value.public_message == "Transcription failed"
    assert RAW_IDENTITY_VIOLATION not in exc.value.public_message


def test_solo_does_not_require_provider_raw_sha256(tmp_path, monkeypatch):
    from engine.job_runner import run_job
    from mir.raw_midi import job_raw_midi_path
    from tests.test_live_cutover import _cutover_env
    from tests.test_live_orchestrator_job import _Counters, _install_mocks, _wav

    _cutover_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "piano.wav")
    run_job(audio, "solo-id", mode="solo", filename="piano.wav")
    raw = job_raw_midi_path(audio, "solo-id")
    assert raw.exists()
    prov = json.loads((tmp_path / "bp_solo-id" / "solo-id.provenance.json").read_text())
    tr = prov["transcription"]
    assert tr["backend"] == "basic_pitch"
    assert tr["provider_raw_sha256"] is None
    assert tr["saved_raw_sha256"]
    assert tr["raw_identity_match"] is None
    assert_live_provenance(prov, mode="solo")


def test_raw_write_happens_before_cleaner(tmp_path, monkeypatch):
    from engine.job_runner import run_job
    from mir.midi_cleaner import MIDICleaner
    from mir.raw_midi import job_raw_midi_path
    from tests.test_live_cutover import _cutover_env
    from tests.test_live_orchestrator_job import _Counters, _install_mocks, _wav

    _cutover_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    order = []
    original = MIDICleaner.clean_with_report

    def wrapped(self, notes):
        order.append("clean")
        raw = job_raw_midi_path(tmp_path / "song.wav", "ord1")
        assert raw.exists()
        assert raw.read_bytes() == counters.midi_bytes
        return original(self, notes)

    monkeypatch.setattr(MIDICleaner, "clean_with_report", wrapped)
    audio = _wav(tmp_path / "song.wav")
    run_job(audio, "ord1", mode="polyphonic", filename="song.wav")
    assert order == ["clean"]


def test_live_polyphonic_request_counts_and_provenance(tmp_path, monkeypatch):
    from engine.job_runner import run_job
    from engine.stages import StageName
    from mir.raw_midi import job_raw_midi_path
    from tests.test_live_cutover import _cutover_env
    from tests.test_live_orchestrator_job import _Counters, _install_mocks, _wav

    monkeypatch.setenv("MT3_API_KEY", "super-secret-key")
    _cutover_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "song.wav")
    run_job(audio, "cnt1", mode="polyphonic", filename="song.wav")
    assert counters.mt3 == 1
    assert counters.warmup == 0
    assert counters.track == 1
    assert counters.sep == 0
    assert counters.bp == 0
    prov = json.loads((tmp_path / "bp_cnt1" / "cnt1.provenance.json").read_text())
    assert prov["pipeline_mode"] == "live"
    assert prov["orchestrator"] == "nextgen"
    tr = prov["transcription"]
    assert tr["backend"] == "mt3"
    assert tr["provider"] in {"http", "runpod", "command", "none"}
    assert "endpoint" not in tr
    assert tr["raw_identity_match"] is True
    assert tr["provider_raw_sha256"] == hashlib.sha256(
        job_raw_midi_path(audio, "cnt1").read_bytes()
    ).hexdigest()
    assert prov["total_pipeline_ms"] is not None
    timings = prov["timings"]
    assert "preprocess_ms" in timings
    assert "mt3_request_ms" in timings
    assert "beat_tracking_ms" in timings
    dumped = json.dumps(prov)
    assert "super-secret-key" not in dumped
    sep = next(s for s in prov["stages"] if s["name"] == StageName.SEPARATE)
    assert sep["skipped"] is True


def test_smoke_polyphonic_provenance_rejects_solo_backend():
    prov = {
        "pipeline_mode": "live",
        "orchestrator": "nextgen",
        "transcription": {
            "backend": "basic_pitch",
            "provider_raw_sha256": None,
            "saved_raw_sha256": "abc",
            "raw_identity_match": None,
        },
    }
    with pytest.raises(SmokeFailure, match="backend"):
        assert_live_provenance(prov, mode="polyphonic")
