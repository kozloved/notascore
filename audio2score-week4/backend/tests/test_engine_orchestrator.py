import hashlib

import pretty_midi

from engine.artifacts import ArtifactKind
from engine.orchestrator import PipelineOrchestrator
from engine.stages import StageName
from mir.raw_midi import job_raw_midi_path, job_score_midi_path
from timing.printed_tempo import printed_tempo_annotations


def _midi(path):
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(0, name="Piano")
    inst.notes = [pretty_midi.Note(80, 60 + i, i * 0.5, i * 0.5 + 0.4) for i in range(4)]
    midi.instruments.append(inst)
    midi.write(str(path))
    return path


def test_orchestrator_midi_preserves_raw_bytes(tmp_path):
    source = _midi(tmp_path / "in.mid")
    original = source.read_bytes()
    result = PipelineOrchestrator().run_midi(source, "orch", meter="4/4")
    assert "score-partwise" in result.musicxml
    raw = job_raw_midi_path(source, "orch")
    score = job_score_midi_path(source, "orch")
    assert raw.read_bytes() == original
    assert hashlib.sha256(raw.read_bytes()).hexdigest() != hashlib.sha256(score.read_bytes()).hexdigest()
    names = [s.name for s in result.stages]
    assert names[0] == StageName.INGEST
    assert StageName.SEPARATE in names
    assert result.stage(StageName.SEPARATE).skipped
    assert result.stage(StageName.TRANSCRIBE_STEMS).skipped
    assert result.stage(StageName.RECONCILE).ok
    assert result.manifest.find(ArtifactKind.RAW_MIDI)
    assert result.manifest.find(ArtifactKind.SCORE_MIDI)
    assert result.manifest.find(ArtifactKind.RAW_MIDI)[0].sha256 != result.manifest.find(ArtifactKind.SCORE_MIDI)[0].sha256
    assert (tmp_path / "bp_orch" / "orch.manifest.json").exists()
    assert result.interpreted is not None
    assert result.time_map is not None


def test_separation_does_not_invent_stems():
    from separation.service import get_separator

    result = get_separator().separate("unused.wav")
    assert result.skipped
    assert result.stems == []
    assert "NEXTGEN_SEPARATION" in result.skip_reason or "disabled" in result.skip_reason.lower()


def test_printed_tempo_ignores_rubato_jitter():
    series = [(float(i), 90 + (i % 3) - 1) for i in range(16)]
    marks = printed_tempo_annotations(series, min_change_ratio=0.12, min_hold_beats=8)
    assert len(marks) == 1
    assert marks[0].mark == "metronome"


def test_printed_tempo_emits_rit_for_persistent_slowing():
    series = [(float(i), 90.0) for i in range(12)]
    series += [(float(i), 70.0) for i in range(12, 24)]
    marks = printed_tempo_annotations(series, min_change_ratio=0.12, min_hold_beats=8)
    kinds = [m.mark for m in marks]
    assert kinds[0] == "metronome"
    assert "rit" in kinds
    assert marks[0].bpm == 90


def test_transkun_and_beat_this_stay_disabled(monkeypatch):
    from engine.flags import transkun_configured, transkun_operational
    from transcription_fed.router import select_transcriber
    from transcription_fed.transkun import TranskunTranscriber, TranskunUnavailable, transkun_available
    from timing.beat_this import BeatThisAnalyzer, BeatThisUnavailable
    import pytest

    monkeypatch.setenv("NEXTGEN_TRANSKUN", "1")
    monkeypatch.setenv("NEXTGEN_TRANSKUN_CHECKPOINT", "/tmp/missing-transkun.ckpt")
    monkeypatch.setenv("NEXTGEN_BEAT_THIS", "1")
    monkeypatch.setenv("NEXTGEN_BEAT_THIS_CHECKPOINT", "/tmp/missing-beat-this.ckpt")
    assert transkun_configured() is True
    assert transkun_operational() is False
    assert transkun_available() is False
    assert select_transcriber(mode="polyphonic", instrument_hint="piano").name != "transkun"
    with pytest.raises(TranskunUnavailable):
        TranskunTranscriber().transcribe("x.wav")
    with pytest.raises(BeatThisUnavailable):
        BeatThisAnalyzer().analyze("x.wav")
