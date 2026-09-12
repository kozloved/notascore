"""Live/shadow/legacy orchestrator: one MT3 request, one tracker, optional stems."""

from __future__ import annotations

import hashlib
import json

import numpy as np
import pretty_midi
import pytest
import soundfile as sf

from audio_engine.beat_tracker import constant_tempo_map
from engine.flags import pipeline_mode
from engine.job_runner import run_job
from engine.orchestrator import PipelineOrchestrator
from engine.stages import StageName
from mir.midi_ingest import ingest_midi
from mir.raw_midi import job_fused_midi_path, job_raw_midi_path, job_raw_stem_midi_path, job_score_midi_path, job_validated_midi_path
from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent
from separation.base import SeparationResult, StemAudio


def _wav(path, seconds=1.0):
    sr = 22050
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    sf.write(str(path), 0.2 * np.sin(2 * np.pi * 440 * t), sr)
    return path


def _midi_bytes(notes=None, program=0):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(program=program, name="Piano")
    inst.notes = [
        pretty_midi.Note(velocity=80, pitch=p, start=s, end=e)
        for p, s, e in (notes or [(60, 0.0, 0.5), (64, 0.5, 1.0)])
    ]
    midi.instruments.append(inst)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "n.mid"
        midi.write(str(path))
        return path.read_bytes()


def _live_env(monkeypatch, *, mode="live"):
    monkeypatch.setenv("NEXTGEN_PIPELINE_MODE", mode)
    monkeypatch.setenv("NEXTGEN_SEPARATION", "1")
    monkeypatch.setenv("NEXTGEN_SEPARATION_BACKEND", "http")
    monkeypatch.setenv("SEPARATION_ENDPOINT", "http://sep.test/separate")
    monkeypatch.setenv("NEXTGEN_STEM_TRANSCRIPTION_ENABLED", "1")
    monkeypatch.setenv("NEXTGEN_FUSION_ENABLED", "1")
    monkeypatch.setenv("NEXTGEN_ENSEMBLE_RENDER", "0")
    monkeypatch.setenv("MT3_ENDPOINT", "http://mt3.test/transcribe")
    monkeypatch.setenv("TRANSCRIPTION_USE_PIANO_ANALYZER", "0")
    monkeypatch.setenv("TRANSCRIPTION_USE_BEAT_TRACKER", "1")


class _Counters:
    def __init__(self):
        self.mt3 = 0
        self.warmup = 0
        self.track = 0
        self.sep = 0
        self.bp = 0
        self.midi_bytes = b""
        self.notes = []
        self.raw_sha = ""


def _install_mocks(monkeypatch, tmp_path, counters: _Counters, *, sep_error=None, mt3_error=None, stem_fail=None):
    midi_bytes = _midi_bytes()
    counters.midi_bytes = midi_bytes
    counters.raw_sha = hashlib.sha256(midi_bytes).hexdigest()
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        seed = Path(tmp) / "seed.mid"
        seed.write_bytes(midi_bytes)
        ingested = ingest_midi(seed)
    counters.notes = list(ingested.notes)

    def fake_mt3(self, path):
        counters.mt3 += 1
        if mt3_error:
            raise RuntimeError(mt3_error)
        self.last_midi_bytes = midi_bytes
        self.last_provider_raw_sha256 = counters.raw_sha
        self.last_performance = ingested.performance
        self.last_timing = {"wall_ms": 12.0, "queue_ms": 3.0, "execution_ms": 9.0}
        return list(ingested.notes)

    def fake_track(self, audio):
        counters.track += 1
        self.last_source = "madmom"
        self.last_time_signature = "4/4"
        self.last_beat_times = [0.0, 0.5, 1.0, 1.5]
        return constant_tempo_map(120.0)

    def fake_sep(self, audio_path, **kwargs):
        counters.sep += 1
        if sep_error:
            return SeparationResult(
                stems=[],
                model="http",
                error=sep_error,
                requested_backend="http",
                actual_backend="",
            )
        out = tmp_path / "stems"
        out.mkdir(exist_ok=True)
        stems = []
        for label, payload in (("piano", b"PIANO"), ("bass", b"BASS"), ("drums", b"DRUM")):
            path = out / f"{label}.wav"
            path.write_bytes(payload)
            stems.append(StemAudio(stem_id=label, instrument=label, path=str(path), model="mock-sep"))
        return SeparationResult(
            stems=stems,
            model="mock-sep",
            model_version="test",
            requested_backend="http",
            actual_backend="mock-sep",
        )

    def fake_bp(self, path):
        counters.bp += 1
        if stem_fail and stem_fail in str(path):
            raise RuntimeError("stem transcription exploded")
        pitch = 60 if "piano" in str(path) else 36
        return [
            NoteEvent(
                pitch=pitch,
                start_time=0.0,
                end_time=0.4,
                velocity=80,
                confidence=0.9,
                source_backend="basic_pitch",
            )
        ]

    monkeypatch.setattr("adapters.mt3_backend.MT3Backend.transcribe_notes", fake_mt3)
    monkeypatch.setattr("audio_engine.beat_tracker.BeatTracker.track", fake_track)
    monkeypatch.setattr("separation.http.HttpSeparator.separate", fake_sep)
    monkeypatch.setattr("adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes", fake_bp)
    monkeypatch.setattr(
        "audio_engine.instrument_classifier.InstrumentClassifier.classify",
        lambda self, audio: InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.9),
    )
    monkeypatch.setattr("mir.pipeline.AudioSegmenter.segment", lambda self, audio: [])

    def reject_provider_http(request, timeout=None):
        url = getattr(request, "full_url", None) or str(request)
        if "warmup" in str(url).lower():
            counters.warmup += 1
        raise AssertionError(f"unexpected provider HTTP {url}")

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", reject_provider_http)
    monkeypatch.setattr("separation.http.urllib.request.urlopen", reject_provider_http)
    return ingested


def test_live_full_song_request_counts(tmp_path, monkeypatch):
    _live_env(monkeypatch)
    assert pipeline_mode() == "live"
    counters = _Counters()
    ingested = _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "song.wav")
    xml = run_job(audio, "live1", mode="polyphonic", filename="song.wav")
    assert "score-partwise" in xml.lower()
    assert counters.mt3 == 1
    assert counters.warmup == 0
    assert counters.track == 1
    assert counters.sep == 1
    assert counters.bp == 2  # piano + bass; drums skipped
    raw = job_raw_midi_path(audio, "live1")
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == counters.raw_sha
    assert raw.read_bytes() == counters.midi_bytes
    piano_raw = job_raw_stem_midi_path(audio, "live1", "piano")
    assert piano_raw.exists()
    assert piano_raw.read_bytes() != raw.read_bytes()
    fused = job_fused_midi_path(audio, "live1")
    assert fused.exists()
    score = job_score_midi_path(audio, "live1")
    validated = job_validated_midi_path(audio, "live1")
    assert fused.read_bytes() != raw.read_bytes()
    assert score.read_bytes() != raw.read_bytes()
    assert score.read_bytes() != fused.read_bytes()
    if validated.exists():
        assert validated.read_bytes() != fused.read_bytes()
    snap = json.loads((tmp_path / "bp_live1" / "live1.performance.json").read_text())
    assert snap["midi_sha256"] == counters.raw_sha
    by_id = {n.note_id: n for n in ingested.performance.notes}
    for note in snap["notes"]:
        original = by_id[note["note_id"]]
        assert note["pitch"] == original.pitch
        assert note["velocity"] == original.velocity
        assert abs(note["start_sec"] - original.start_sec) < 1e-9
        assert abs(note["end_sec"] - original.end_sec) < 1e-9
    provenance = json.loads((tmp_path / "bp_live1" / "live1.provenance.json").read_text())
    names = [s["name"] for s in provenance["stages"]]
    assert "SEPARATE" in names
    sep_stage = next(s for s in provenance["stages"] if s["name"] == "SEPARATE")
    assert sep_stage["status"] == "success"
    assert sep_stage["ok"] is True
    recon = next(s for s in provenance["stages"] if s["name"] == "RECONCILE")
    assert recon["skipped"] is False
    drums_midi = list((tmp_path / "bp_live1").glob("live1.raw.drums.mid"))
    assert drums_midi == []


def test_shadow_does_not_double_mt3(tmp_path, monkeypatch):
    _live_env(monkeypatch, mode="shadow")
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "song.wav")
    xml = run_job(audio, "sh1", mode="polyphonic", filename="song.wav")
    assert "score-partwise" in xml.lower()
    assert counters.mt3 == 1
    assert counters.sep == 0
    assert counters.bp == 0
    assert counters.track == 1
    raw = job_raw_midi_path(audio, "sh1")
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == counters.raw_sha
    prov = json.loads((tmp_path / "bp_sh1" / "sh1.provenance.json").read_text())
    sep = next(s for s in prov["stages"] if s["name"] == "SEPARATE")
    assert sep["skipped"] is True
    assert (tmp_path / "bp_sh1" / "sh1.manifest.json").exists()


def test_legacy_ignores_separator_even_when_flagged(tmp_path, monkeypatch):
    _live_env(monkeypatch, mode="legacy")
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "song.wav")
    run_job(audio, "leg1", mode="polyphonic", filename="song.wav")
    assert counters.mt3 == 1
    assert counters.sep == 0
    assert counters.track == 1


def test_solo_live_skips_separation(tmp_path, monkeypatch):
    _live_env(monkeypatch, mode="live")
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "solo.wav")
    # Solo uses Basic Pitch as the global backend, so MT3 must stay 0.
    run_job(audio, "solo1", mode="solo", filename="solo.wav")
    assert counters.mt3 == 0
    assert counters.sep == 0
    assert counters.track == 1


def test_separation_failure_continues_with_mt3(tmp_path, monkeypatch):
    _live_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters, sep_error="separator down")
    audio = _wav(tmp_path / "song.wav")
    xml = run_job(audio, "failsep", mode="polyphonic", filename="song.wav")
    assert "score-partwise" in xml.lower()
    assert counters.mt3 == 1
    raw = job_raw_midi_path(audio, "failsep")
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == counters.raw_sha
    prov = json.loads((tmp_path / "bp_failsep" / "failsep.provenance.json").read_text())
    sep = next(s for s in prov["stages"] if s["name"] == "SEPARATE")
    assert sep["status"] == "failed"
    assert sep["ok"] is False
    assert sep["error"]


def test_one_stem_failure_continues(tmp_path, monkeypatch):
    _live_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters, stem_fail="piano")
    audio = _wav(tmp_path / "song.wav")
    xml = run_job(audio, "failstem", mode="polyphonic", filename="song.wav")
    assert "score-partwise" in xml.lower()
    assert counters.mt3 == 1
    bass = job_raw_stem_midi_path(audio, "failstem", "bass")
    assert bass.exists()
    piano = job_raw_stem_midi_path(audio, "failstem", "piano")
    assert not piano.exists()


def test_mt3_failure_is_not_replaced_by_stem_basic_pitch(tmp_path, monkeypatch):
    _live_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters, mt3_error="mt3 exploded")
    audio = _wav(tmp_path / "song.wav")
    with pytest.raises(RuntimeError, match="mt3 exploded"):
        run_job(audio, "failmt3", mode="polyphonic", filename="song.wav")
    assert counters.mt3 == 1
    assert counters.bp == 0
    assert not job_raw_midi_path(audio, "failmt3").exists()


def test_live_does_not_flatten_fused_ensemble_into_score(tmp_path, monkeypatch):
    _live_env(monkeypatch)
    counters = _Counters()
    _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "song.wav")
    result = PipelineOrchestrator().run(audio, "ens1", mode="polyphonic")
    assert result.stage(StageName.RENDER).skipped
    fusion = json.loads((tmp_path / "bp_ens1" / "ens1.fusion.json").read_text())
    assert fusion["notes"]
    assert fusion["baseline"]["source"] == "full_mix"
    assert fusion["review"]
    assert {row["action"] for row in fusion["review"]} <= {"keep", "add", "suppress"}
    names = [s.name.value for s in result.stages]
    assert names.index("RECONCILE") < names.index("INTERPRET_SCORE")
    baseline = json.loads((tmp_path / "bp_ens1" / "ens1.baseline.json").read_text())
    assert baseline["source"] == "full_mix"
    xml = result.musicxml.lower()
    assert "score-partwise" in xml
    fused_midi = pretty_midi.PrettyMIDI(str(job_fused_midi_path(audio, "ens1")))
    programs = {inst.program for inst in fused_midi.instruments if inst.notes}
    assert programs
    assert 0 in programs  # mix piano program preserved, not flattened away
    assert counters.mt3 == 1


def test_raw_midi_survives_separator_fusion_and_upload_copy(tmp_path, monkeypatch):
    from engine.sidecars import extra_result_files, result_object_key

    _live_env(monkeypatch)
    counters = _Counters()
    ingested = _install_mocks(monkeypatch, tmp_path, counters)
    audio = _wav(tmp_path / "song.wav")
    run_job(audio, "up1", mode="polyphonic", filename="song.wav")
    raw_path = job_raw_midi_path(audio, "up1")
    before = raw_path.read_bytes()
    sha_before = hashlib.sha256(before).hexdigest()
    by_id = {n.note_id: n for n in ingested.performance.notes}
    snap = json.loads((tmp_path / "bp_up1" / "up1.performance.json").read_text())
    for note in snap["notes"]:
        original = by_id[note["note_id"]]
        assert note["pitch"] == original.pitch
        assert note["velocity"] == original.velocity
        assert abs(note["start_sec"] - original.start_sec) < 1e-9
        assert abs(note["end_sec"] - original.end_sec) < 1e-9
        assert note["note_id"] == original.note_id

    uploaded = {f"up1.raw.mid": before}
    for extra in extra_result_files(tmp_path / "bp_up1", "up1"):
        uploaded[result_object_key(extra)] = extra.read_bytes()
    assert hashlib.sha256(uploaded["up1.raw.mid"]).hexdigest() == sha_before
    assert uploaded["up1.raw.mid"] == before
    assert uploaded["up1.fused.mid"] != before
    assert job_score_midi_path(audio, "up1").read_bytes() != before
    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == sha_before
    assert counters.mt3 == 1
    assert counters.warmup == 0
    assert counters.track == 1
    assert counters.sep == 1

