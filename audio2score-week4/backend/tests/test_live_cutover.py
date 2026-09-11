"""First production cutover: live orchestrator with federation OFF."""

from __future__ import annotations

import hashlib
import json

import pretty_midi

from engine.flags import (
    PIPELINE_MODE_LEGACY,
    format_pipeline_banner,
    nextgen_status,
    pipeline_mode,
)
from engine.job_runner import run_job
from engine.stages import StageName
from mir.raw_midi import job_fused_midi_path, job_raw_midi_path, job_score_midi_path
from mir.types import InstrumentKind, InstrumentPrediction
from tests.test_live_orchestrator_job import (
    _Counters,
    _install_mocks,
    _wav,
)


def _cutover_env(monkeypatch, *, mode="live"):
    monkeypatch.setenv("NEXTGEN_PIPELINE_MODE", mode)
    monkeypatch.setenv("NEXTGEN_SEPARATION_ENABLED", "0")
    monkeypatch.delenv("NEXTGEN_SEPARATION", raising=False)
    monkeypatch.setenv("NEXTGEN_SEPARATION_BACKEND", "auto")
    monkeypatch.delenv("SEPARATION_ENDPOINT", raising=False)
    monkeypatch.setenv("SEPARATION_ENDPOINT", "")
    monkeypatch.setenv("NEXTGEN_STEM_TRANSCRIPTION_ENABLED", "0")
    monkeypatch.setenv("NEXTGEN_FUSION_ENABLED", "0")
    monkeypatch.setenv("NEXTGEN_ENSEMBLE_RENDER", "0")
    monkeypatch.setenv("NEXTGEN_TRANSKUN", "0")
    monkeypatch.setenv("NEXTGEN_BEAT_THIS", "0")
    monkeypatch.setenv("NEXTGEN_WRITE_MANIFEST", "1")
    monkeypatch.setenv("MT3_ENDPOINT", "http://mt3.test/transcribe")
    monkeypatch.setenv("TRANSCRIPTION_USE_PIANO_ANALYZER", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_BEAT_TRACKER", "1")


def test_code_fallback_stays_legacy(monkeypatch):
    monkeypatch.delenv("NEXTGEN_PIPELINE_MODE", raising=False)
    assert pipeline_mode() == PIPELINE_MODE_LEGACY
    assert nextgen_status()["orchestrator_active"] is False


def test_health_nextgen_live_cutover_flags(monkeypatch):
    from main import health

    _cutover_env(monkeypatch)
    monkeypatch.setenv("MT3_API_KEY", "super-secret-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    payload = health()
    ng = payload["nextgen"]
    assert ng == {
        "pipeline_mode": "live",
        "orchestrator_active": True,
        "separation_enabled": False,
        "separation_backend": "auto",
        "separation_configured": False,
        "stem_transcription_enabled": False,
        "fusion_enabled": False,
        "transkun_enabled": False,
        "beat_this_enabled": False,
        "ensemble_render_enabled": False,
        "write_manifest": True,
    }
    dumped = json.dumps(payload)
    assert "super-secret-key" not in dumped
    assert "service-role-secret" not in dumped
    assert "MT3_API_KEY" not in dumped
    assert payload["pipeline_config"]["valid"] is True
    assert payload["pipeline_config"]["effective_hand_separator"] == "viterbi"


def test_health_stays_ok_for_hand_separator_performance_alias(monkeypatch):
    from main import health

    _cutover_env(monkeypatch)
    monkeypatch.setenv("TRANSCRIPTION_HAND_SEPARATOR", "performance")
    payload = health()
    assert payload["status"] == "ok"
    assert payload["hand_separator"] == "viterbi"
    assert payload["pipeline_config"]["valid"] is True
    assert payload["pipeline_config"]["effective_hand_separator"] == "viterbi"
    assert payload["pipeline_config"]["warning"]


def test_health_stays_ok_for_unknown_hand_separator(monkeypatch):
    from main import health

    _cutover_env(monkeypatch)
    monkeypatch.setenv("TRANSCRIPTION_HAND_SEPARATOR", "foobar")
    payload = health()
    assert payload["status"] == "ok"
    assert payload["pipeline_config"]["valid"] is False
    assert "foobar" in (payload["pipeline_config"]["error"] or "")
    assert payload["pipeline_config"]["effective_hand_separator"] == "viterbi"


def test_worker_banner_reports_live_without_secrets(monkeypatch):
    _cutover_env(monkeypatch)
    text = format_pipeline_banner(mt3_configured=True)
    assert "NotaScore pipeline configuration:" in text
    assert "nextgen_mode=live" in text
    assert "separation=off" in text
    assert "stem_transcription=off" in text
    assert "fusion=off" in text
    assert "ensemble_render=off" in text
    assert "MT3 configured = true" in text
    assert "http://mt3.test" not in text
    assert "MT3_API_KEY" not in text


def test_live_federation_disabled_polyphonic_job(tmp_path, monkeypatch):
    _cutover_env(monkeypatch)
    assert pipeline_mode() == "live"
    counters = _Counters()
    ingested = _install_mocks(monkeypatch, tmp_path, counters)

    def boom_sep(*args, **kwargs):
        counters.sep += 1
        raise AssertionError("HTTP separator must not run when federation is off")

    monkeypatch.setattr("separation.http.HttpSeparator.separate", boom_sep)
    audio = _wav(tmp_path / "song.wav")
    xml = run_job(audio, "cut1", mode="polyphonic", filename="song.wav")
    assert "score-partwise" in xml.lower()
    assert counters.mt3 == 1
    assert counters.warmup == 0
    assert counters.track == 1
    assert counters.sep == 0
    assert counters.bp == 0
    raw = job_raw_midi_path(audio, "cut1")
    sha_before = counters.raw_sha
    sha_after = hashlib.sha256(raw.read_bytes()).hexdigest()
    assert sha_before == sha_after
    assert raw.read_bytes() == counters.midi_bytes
    score = job_score_midi_path(audio, "cut1")
    assert score.exists()
    assert score.read_bytes() != raw.read_bytes()
    assert not job_fused_midi_path(audio, "cut1").exists()
    stem_midi = list((tmp_path / "bp_cut1").glob("cut1.raw.*.mid"))
    stem_wav = list((tmp_path / "bp_cut1").glob("cut1.stem.*"))
    assert stem_midi == []
    assert stem_wav == []
    prov = json.loads((tmp_path / "bp_cut1" / "cut1.provenance.json").read_text())
    assert prov["pipeline_mode"] == "live"
    assert prov["orchestrator"] == "nextgen"
    assert prov["separation_enabled"] is False
    assert prov["fusion_enabled"] is False
    sep = next(s for s in prov["stages"] if s["name"] == StageName.SEPARATE)
    assert sep["skipped"] is True
    recon = next(s for s in prov["stages"] if s["name"] == StageName.RECONCILE)
    assert recon["skipped"] is True
    by_id = {n.note_id: n for n in ingested.performance.notes}
    snap = json.loads((tmp_path / "bp_cut1" / "cut1.performance.json").read_text())
    for note in snap["notes"]:
        original = by_id[note["note_id"]]
        assert note["pitch"] == original.pitch
        assert note["velocity"] == original.velocity
        assert abs(note["start_sec"] - original.start_sec) < 1e-9
        assert abs(note["end_sec"] - original.end_sec) < 1e-9
    assert (tmp_path / "bp_cut1" / "cut1.manifest.json").exists()
    assert (tmp_path / "bp_cut1" / "cut1.tempo.json").exists()
    debug = json.loads((tmp_path / "bp_cut1" / "cut1.debug.json").read_text())
    extra = debug.get("extra") or {}
    assert extra.get("pipeline_mode") == "live"
    assert extra.get("orchestrator") == "nextgen"


def test_legacy_and_live_core_share_raw_identity(tmp_path, monkeypatch):
    results = {}
    for mode, job_id in (("legacy", "par-leg"), ("live", "par-live")):
        _cutover_env(monkeypatch, mode=mode)
        counters = _Counters()
        ingested = _install_mocks(monkeypatch, tmp_path, counters)
        audio = _wav(tmp_path / f"{job_id}.wav")
        xml = run_job(audio, job_id, mode="polyphonic", filename=f"{job_id}.wav")
        raw = job_raw_midi_path(audio, job_id).read_bytes()
        snap = json.loads((tmp_path / f"bp_{job_id}" / f"{job_id}.performance.json").read_text())
        results[mode] = {
            "sha": hashlib.sha256(raw).hexdigest(),
            "raw": raw,
            "xml": xml,
            "mt3": counters.mt3,
            "warmup": counters.warmup,
            "track": counters.track,
            "sep": counters.sep,
            "bp": counters.bp,
            "notes": snap["notes"],
            "ingested": ingested,
        }
    assert results["legacy"]["sha"] == results["live"]["sha"]
    assert results["legacy"]["raw"] == results["live"]["raw"]
    assert results["legacy"]["mt3"] == 1
    assert results["live"]["mt3"] == 1
    assert results["live"]["warmup"] == 0
    assert results["live"]["track"] == 1
    assert results["live"]["sep"] == 0
    assert results["live"]["bp"] == 0
    by_id = {n.note_id: n for n in results["legacy"]["ingested"].performance.notes}
    live_by_id = {n.note_id: n for n in results["live"]["ingested"].performance.notes}
    assert by_id.keys() == live_by_id.keys()
    for ident, original in by_id.items():
        live = live_by_id[ident]
        assert live.pitch == original.pitch
        assert live.velocity == original.velocity
        assert abs(live.start_sec - original.start_sec) < 1e-9
        assert abs(live.end_sec - original.end_sec) < 1e-9
    for note in results["live"]["notes"]:
        original = by_id[note["note_id"]]
        assert note["pitch"] == original.pitch
        assert note["velocity"] == original.velocity
        assert abs(note["start_sec"] - original.start_sec) < 1e-9
        assert abs(note["end_sec"] - original.end_sec) < 1e-9


def test_live_cutover_solo_piano(tmp_path, monkeypatch):
    _cutover_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "piano.wav")
    xml = run_job(audio, "solo-p", mode="solo", filename="piano.wav")
    assert "score-partwise" in xml.lower()
    assert counters.mt3 == 0
    assert counters.sep == 0
    assert counters.track == 1
    raw = job_raw_midi_path(audio, "solo-p")
    assert raw.exists()
    prov = json.loads((tmp_path / "bp_solo-p" / "solo-p.provenance.json").read_text())
    assert prov["orchestrator"] == "nextgen"
    assert prov["pipeline_mode"] == "live"


def test_live_cutover_solo_non_piano_is_not_piano_grand_staff(tmp_path, monkeypatch):
    _cutover_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    monkeypatch.setattr(
        "audio_engine.instrument_classifier.InstrumentClassifier.classify",
        lambda self, audio: InstrumentPrediction(instrument=InstrumentKind.GUITAR, confidence=0.9),
    )
    audio = _wav(tmp_path / "guitar.wav")
    xml = run_job(audio, "solo-g", mode="solo", filename="guitar.wav")
    assert "score-partwise" in xml.lower()
    assert counters.mt3 == 0
    lowered = xml.lower()
    piano_parts = lowered.count("<part-name>piano")
    bass_clefs = lowered.count('sign="f"')
    treble_clefs = lowered.count('sign="g"')
    if "guitar" in lowered or "acoustic guitar" in lowered:
        assert piano_parts == 0 or "guitar" in lowered
    debug = json.loads((tmp_path / "bp_solo-g" / "solo-g.debug.json").read_text())
    extra = debug.get("extra") or {}
    profile = (extra.get("quantization_summary") or {}).get("score_profile") or {}
    if profile:
        assert profile.get("grand_staff") is False
    # Two staves with bass+treble is the piano layout; guitar should not need both.
    if bass_clefs and treble_clefs and not profile:
        raise AssertionError("solo guitar used piano grand-staff clefs without a guitar profile")
    prov = json.loads((tmp_path / "bp_solo-g" / "solo-g.provenance.json").read_text())
    assert prov["pipeline_mode"] == "live"
