"""HTTP separator contract: real worker I/O, never invented stems."""

from __future__ import annotations

import base64
import json

from separation.http import HttpSeparator
from separation.service import get_separator


class _FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_http_separator_writes_only_returned_stems(tmp_path, monkeypatch):
    monkeypatch.setenv("SEPARATION_ENDPOINT", "http://sep.test/separate")
    audio = tmp_path / "mix.wav"
    audio.write_bytes(b"RIFF-FAKE")
    piano = base64.b64encode(b"PIANO-WAV").decode()
    drums = base64.b64encode(b"DRUM-WAV").decode()
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request)
        assert request.full_url == "http://sep.test/separate"
        payload = json.loads(request.data.decode())
        assert payload["job_id"] == "job1"
        assert payload["requested_stems"] == ["piano", "drums", "guitar"]
        body = {
            "model": "mock-separator",
            "model_version": "test",
            "stems": {
                "piano": {"audio_base64": piano, "confidence": 0.8},
                "drums": {"audio_base64": drums},
            },
        }
        return _FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr("separation.http.urllib.request.urlopen", fake_urlopen)
    sep = HttpSeparator()
    result = sep.separate(
        str(audio),
        job_id="job1",
        output_dir=tmp_path,
        requested_stems=["piano", "drums", "guitar"],
    )
    assert len(calls) == 1
    assert not result.skipped
    assert result.error == ""
    assert {s.stem_id for s in result.stems} == {"piano", "drums"}
    assert "guitar" not in {s.stem_id for s in result.stems}
    assert not (tmp_path / "job1.stem.guitar.wav").exists()
    assert not (tmp_path / "job1.stem.vocals.wav").exists()
    assert (tmp_path / "job1.stem.piano.wav").read_bytes() == b"PIANO-WAV"
    assert (tmp_path / "job1.stem.drums.wav").read_bytes() == b"DRUM-WAV"
    piano_stem = next(s for s in result.stems if s.stem_id == "piano")
    assert piano_stem.confidence == 0.8
    assert piano_stem.model == "mock-separator"
    assert piano_stem.model_version == "test"
    assert result.model == "mock-separator"
    assert result.model_version == "test"
    assert sep.last_request_count == 1
    assert result.error == ""
    assert result.skipped is False


def test_http_separator_ignores_unknown_stem_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("SEPARATION_ENDPOINT", "http://sep.test/separate")
    audio = tmp_path / "mix.wav"
    audio.write_bytes(b"RIFF")

    def fake_urlopen(request, timeout=None):
        body = {
            "model": "mock-separator",
            "stems": {
                "harmonica": {"audio_base64": base64.b64encode(b"NO").decode()},
                "bass": {"audio_base64": base64.b64encode(b"BASS").decode()},
            },
        }
        return _FakeResponse(json.dumps(body).encode())

    monkeypatch.setattr("separation.http.urllib.request.urlopen", fake_urlopen)
    result = HttpSeparator().separate(str(audio), job_id="j", output_dir=tmp_path)
    assert [s.stem_id for s in result.stems] == ["bass"]
    assert any("harmonica" in w for w in result.warnings)


def test_http_failure_is_error_not_success(tmp_path, monkeypatch):
    monkeypatch.setenv("SEPARATION_ENDPOINT", "http://sep.test/separate")
    audio = tmp_path / "mix.wav"
    audio.write_bytes(b"RIFF")

    def fake_urlopen(request, timeout=None):
        raise TimeoutError("nope")

    monkeypatch.setattr("separation.http.urllib.request.urlopen", fake_urlopen)
    result = HttpSeparator().separate(str(audio), job_id="j", output_dir=tmp_path)
    assert result.error
    assert result.stems == []
    assert not result.skipped


def test_separator_disabled_does_not_invent_stems():
    result = get_separator().separate("unused.wav")
    assert result.skipped
    assert result.stems == []
