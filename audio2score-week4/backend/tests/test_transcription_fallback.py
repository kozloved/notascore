"""Empty/drum-only MT3 MIDI must fall back to a coherent Basic Pitch result.

Mocks the provider transport (HTTP body), not the orchestrator state machine.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pretty_midi
import pytest

from adapters.mt3_backend import MT3Backend
from engine.orchestrator import PipelineOrchestrator
from engine.stages import StageName
from mir.midi_ingest import NoPitchedNotesError
from mir.raw_midi import job_raw_midi_path
from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent
from tests.test_live_orchestrator_job import _live_env, _wav
from transcription import TranscriptionError


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "audio/midi"):
        self.body = body
        self.headers = {"Content-Type": content_type}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _midi_bytes(*, notes=None, drums=None) -> bytes:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    if notes:
        inst = pretty_midi.Instrument(program=0, name="Piano")
        for pitch, start, end in notes:
            inst.notes.append(
                pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=end)
            )
        midi.instruments.append(inst)
    elif drums:
        inst = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
        for pitch, start, end in drums:
            inst.notes.append(
                pretty_midi.Note(velocity=100, pitch=pitch, start=start, end=end)
            )
        midi.instruments.append(inst)
    else:
        midi.instruments.append(pretty_midi.Instrument(program=0, name="Empty"))
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "n.mid"
        midi.write(str(path))
        return path.read_bytes()


def _bp_note(pitch=67):
    return NoteEvent(
        pitch=pitch,
        start_time=0.0,
        end_time=0.5,
        velocity=80,
        confidence=0.8,
        source_backend="basic_pitch",
        note_id="n0000",
        model_score=0.8,
        confidence_source="amplitude",
    )


def _support_mocks(monkeypatch, tmp_path, *, bp_notes=None, bp_calls=None):
    from audio_engine.beat_tracker import constant_tempo_map

    def fake_track(self, audio):
        self.last_source = "madmom"
        self.last_time_signature = "4/4"
        self.last_beat_times = [0.0, 0.5, 1.0, 1.5]
        return constant_tempo_map(120.0)

    def fake_bp(self, path):
        if bp_calls is not None:
            bp_calls.append(str(path))
        if bp_notes is not None:
            return list(bp_notes)
        return [_bp_note()]

    monkeypatch.setattr("audio_engine.beat_tracker.BeatTracker.track", fake_track)
    monkeypatch.setattr(
        "adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes", fake_bp
    )
    monkeypatch.setattr(
        "audio_engine.instrument_classifier.InstrumentClassifier.classify",
        lambda self, audio: InstrumentPrediction(
            instrument=InstrumentKind.PIANO, confidence=0.9
        ),
    )
    monkeypatch.setattr("mir.pipeline.AudioSegmenter.segment", lambda self, audio: [])
    monkeypatch.setenv("NEXTGEN_SEPARATION_ENABLED", "0")
    monkeypatch.setenv("NEXTGEN_STEM_TRANSCRIPTION_ENABLED", "0")
    monkeypatch.setenv("NEXTGEN_FUSION_ENABLED", "0")


def _install_empty_mt3_http(monkeypatch, midi_bytes: bytes, calls: list):
    def fake_urlopen(request, timeout=None):
        calls.append(getattr(request, "full_url", None) or str(request))
        return _FakeResponse(midi_bytes)

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)


@pytest.mark.parametrize(
    "midi_kind,payload",
    [
        ("empty", _midi_bytes()),
        ("drum_only", _midi_bytes(drums=[(36, 0.0, 0.2)])),
    ],
)
def test_decode_empty_or_drum_midi_raises_typed_error(midi_kind, payload):
    backend = MT3Backend()
    with pytest.raises(NoPitchedNotesError) as exc:
        backend._decode(payload)
    assert exc.value.reason in {"empty", "drum_only"}
    assert exc.value.midi_bytes == payload
    assert backend.last_midi_bytes == payload
    assert backend.last_provider_raw_sha256 == hashlib.sha256(payload).hexdigest()
    if midi_kind == "drum_only":
        assert exc.value.reason == "drum_only"


@pytest.mark.parametrize("kind", ["empty", "drum_only"])
def test_empty_or_drum_mt3_http_falls_back_to_basic_pitch(
    tmp_path, monkeypatch, kind
):
    _live_env(monkeypatch)
    payload = (
        _midi_bytes() if kind == "empty" else _midi_bytes(drums=[(36, 0.0, 0.2)])
    )
    http_calls: list[str] = []
    bp_calls: list[str] = []
    _install_empty_mt3_http(monkeypatch, payload, http_calls)
    _support_mocks(monkeypatch, tmp_path, bp_calls=bp_calls)
    audio = _wav(tmp_path / "song.wav")
    result = PipelineOrchestrator().run(audio, f"fb-{kind}", mode="polyphonic")
    assert "score-partwise" in result.musicxml.lower()
    assert http_calls, "provider transport was not used"
    transcribe = result.stage(StageName.TRANSCRIBE_GLOBAL)
    assert transcribe.actual_backend == "basic_pitch"
    assert transcribe.requested_backend == "mt3"
    assert transcribe.extra.get("fallback_from") == "mt3"
    raw = job_raw_midi_path(audio, f"fb-{kind}").read_bytes()
    assert raw != payload
    assert hashlib.sha256(raw).hexdigest() != hashlib.sha256(payload).hexdigest()
    diag = tmp_path / f"bp_fb-{kind}" / f"fb-{kind}.unsuccessful.mt3.mid"
    assert diag.exists()
    assert diag.read_bytes() == payload
    identity = json.loads(
        (tmp_path / f"bp_fb-{kind}" / f"fb-{kind}.transcription.json").read_text()
    )
    assert identity["actual_backend"] == "basic_pitch"
    assert identity["requested_backend"] == "mt3"
    assert identity["fallback_reason"]
    prov = json.loads(
        (tmp_path / f"bp_fb-{kind}" / f"fb-{kind}.provenance.json").read_text()
    )
    assert prov["transcription"]["actual_backend"] == "basic_pitch"
    assert prov["transcription"]["backend"] == "basic_pitch"
    mix_bp = [c for c in bp_calls if "stem" not in Path(c).name]
    assert len(mix_bp) == 1


def test_successful_mt3_raw_bytes_remain_identical(tmp_path, monkeypatch):
    _live_env(monkeypatch)
    payload = _midi_bytes(notes=[(60, 0.0, 0.5), (64, 0.5, 1.0)])
    http_calls: list[str] = []
    bp_calls: list[str] = []
    _install_empty_mt3_http(monkeypatch, payload, http_calls)
    _support_mocks(monkeypatch, tmp_path, bp_calls=bp_calls)
    audio = _wav(tmp_path / "ok.wav")
    result = PipelineOrchestrator().run(audio, "ok-mt3", mode="polyphonic")
    assert "score-partwise" in result.musicxml.lower()
    raw = job_raw_midi_path(audio, "ok-mt3").read_bytes()
    assert raw == payload
    transcribe = result.stage(StageName.TRANSCRIBE_GLOBAL)
    assert transcribe.actual_backend == "mt3"
    assert not transcribe.extra.get("fallback_from")
    assert bp_calls == []
    identity = json.loads(
        (tmp_path / "bp_ok-mt3" / "ok-mt3.transcription.json").read_text()
    )
    assert identity["actual_backend"] == "mt3"
    assert identity["provider_raw_sha256"] == hashlib.sha256(payload).hexdigest()


def test_auth_error_does_not_fall_back_to_basic_pitch(tmp_path, monkeypatch):
    _live_env(monkeypatch)
    bp_calls: list[str] = []
    _support_mocks(monkeypatch, tmp_path, bp_calls=bp_calls)

    def fake_urlopen(request, timeout=None):
        import io
        from urllib.error import HTTPError

        raise HTTPError(
            "http://mt3.test/transcribe",
            401,
            "unauthorized",
            hdrs={},
            fp=io.BytesIO(b"no"),
        )

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    audio = _wav(tmp_path / "auth.wav")
    with pytest.raises(TranscriptionError, match="HTTP 401"):
        PipelineOrchestrator().run(audio, "auth-mt3", mode="polyphonic")
    assert bp_calls == []
    assert not job_raw_midi_path(audio, "auth-mt3").exists()


def test_failed_fallback_does_not_publish_inconsistent_result(tmp_path, monkeypatch):
    _live_env(monkeypatch)
    payload = _midi_bytes()
    _install_empty_mt3_http(monkeypatch, payload, [])
    _support_mocks(monkeypatch, tmp_path, bp_notes=[])
    audio = _wav(tmp_path / "both-empty.wav")
    with pytest.raises(TranscriptionError, match="fallback produced no pitched notes"):
        PipelineOrchestrator().run(audio, "both-empty", mode="polyphonic")
    assert not job_raw_midi_path(audio, "both-empty").exists()
