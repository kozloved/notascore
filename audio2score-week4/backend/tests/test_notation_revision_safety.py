"""Acceptance tests for notation revision safety, identity, and honest policies."""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from fractions import Fraction
from pathlib import Path

import pretty_midi
import pytest
from fastapi import HTTPException

from evaluation.notation_fixtures import FIXTURES
from mir.midi_ingest import ingest_midi
from mir.interpretation_context import (
    FALLBACK_MISSING,
    InterpretationContext,
    InterpretationContextError,
)
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings
from mir.performance import PerformanceSnapshot
from mir.performance_score import _duration, _onset_candidates, quantize_notation
from mir.quantizer import QuantizerConfig
from mir.types import Hand, MusicalEvent
from notation_engine.exact_plan import _pieces, build_exact_measures
from mir.models import MeterHypothesis, PlannedNote, PlannedRest
from timing.tempo_map import MusicalTimeMap


METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)


def _fail_if_transcribe(monkeypatch):
    def boom(*_args, **_kwargs):
        pytest.fail("transcription provider called during notation regeneration")

    monkeypatch.setattr(
        "adapters.mt3_backend.MT3Backend.transcribe_notes", boom, raising=False
    )
    monkeypatch.setattr(
        "adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes",
        boom,
        raising=False,
    )


def _midi_bytes(notes, *, tempo=120):
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    inst = pretty_midi.Instrument(program=0, name="Piano")
    for pitch, start, end in notes:
        inst.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=end))
    midi.instruments.append(inst)
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "n.mid"
        midi.write(str(path))
        return path.read_bytes()


def _job_row(job_id: str, **overrides):
    import database as db

    now = db.utcnow()
    row = {
        "id": job_id,
        "status": "completed",
        "filename": "clip.wav",
        "content_type": "audio/wav",
        "size_bytes": 8,
        "storage_key": None,
        "result_storage_key": None,
        "progress": 100,
        "error": None,
        "created_at": now,
        "updated_at": now,
        "mode": "solo",
        "user_id": None,
        "title": "Clip",
        "duration_seconds": 1,
        "claim_token_hash": None,
        "deleted_at": None,
        "edit_revision": 0,
    }
    row.update(overrides)
    return row


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    import database as db

    url = f"sqlite:///{tmp_path / 'notation-rev.db'}"
    previous_url = db.DATABASE_URL
    previous_engine = db.engine
    monkeypatch.setenv("DATABASE_URL", url)
    db.DATABASE_URL = url
    db.engine = db.create_engine(
        url, connect_args={"check_same_thread": False, "timeout": 30}
    )
    db.SessionLocal.configure(bind=db.engine)
    db.init_db()
    yield tmp_path
    db.engine.dispose()
    db.engine = previous_engine
    db.DATABASE_URL = previous_url
    db.SessionLocal.configure(bind=previous_engine)


def _prepare_job(tmp_path, job_id: str, *, name="humanized_quarters"):
    source = tmp_path / f"{job_id}.mid"
    digest = FIXTURES[name](source)
    original = source.read_bytes()
    xml_path = tmp_path / f"{job_id}.musicxml"
    from mir.performance_cli import convert

    convert(source, xml_path)
    (tmp_path / f"{job_id}.raw.mid").write_bytes(original)
    return xml_path, original, digest


def _musical_inventory(xml_text: str):
    from music21 import converter

    score = converter.parse(xml_text, format="musicxml")
    notes = []
    for element in score.flatten().notes:
        members = list(element.notes) if element.isChord else [element]
        onset = float(element.getOffsetInHierarchy(score))
        for member in members:
            notes.append(
                (
                    int(member.pitch.midi),
                    round(onset, 4),
                    round(float(member.quarterLength), 4),
                )
            )
    signatures = [ts.ratioString for ts in score.flatten().getTimeSignatures()]
    keys = [str(k) for k in score.flatten().getElementsByClass("KeySignature")]
    tempi = [
        float(m.number)
        for m in score.flatten().getElementsByClass("MetronomeMark")
        if m.number is not None
    ]
    return notes, signatures, keys, tempi


def test_storage_failure_does_not_advance_revision(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    import database as db
    import main as app_main

    job_id = f"fail-{uuid.uuid4().hex[:12]}"
    xml_path, original, digest = _prepare_job(isolated_db, job_id)
    canonical = xml_path.read_text(encoding="utf-8")
    db.create_job(_job_row(job_id, result_storage_key=str(xml_path), edit_revision=0))

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(app_main, "_write_revision_bundle", boom)
    with pytest.raises(HTTPException) as exc:
        app_main.job_notation_settings_post(
            job_id,
            app_main.NotationSettingsIn(interpretation="literal", revision=0),
            authorization=None,
        )
    assert exc.value.status_code == 500
    job = db.get_job(job_id)
    assert job["edit_revision"] == 0
    assert job["edited_result_storage_key"] in (None, "")
    assert xml_path.read_text(encoding="utf-8") == canonical
    assert (isolated_db / f"{job_id}.raw.mid").read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == digest


def test_concurrent_notation_saves_one_winner(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    import database as db
    import main as app_main

    job_id = f"race-{uuid.uuid4().hex[:12]}"
    xml_path, original, _digest = _prepare_job(isolated_db, job_id)
    canonical = xml_path.read_text(encoding="utf-8")
    db.create_job(_job_row(job_id, result_storage_key=str(xml_path), edit_revision=0))
    barrier = threading.Barrier(2)
    original_write = app_main._write_revision_bundle

    def delayed(job, files, require_complete=True):
        barrier.wait(timeout=5)
        return original_write(job, files, require_complete=require_complete)

    monkeypatch.setattr(app_main, "_write_revision_bundle", delayed)
    results: list[tuple] = []

    def worker(interpretation: str) -> None:
        try:
            payload = app_main.job_notation_settings_post(
                job_id,
                app_main.NotationSettingsIn(
                    interpretation=interpretation, revision=0
                ),
                authorization=None,
            )
            results.append(("ok", interpretation, payload))
        except HTTPException as exc:
            results.append(("err", interpretation, exc.status_code))

    threads = [
        threading.Thread(target=worker, args=("literal",)),
        threading.Thread(target=worker, args=("readable",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    outcomes = [row[0] for row in results]
    assert outcomes.count("ok") == 1
    assert outcomes.count("err") == 1
    job = db.get_job(job_id)
    assert job["edit_revision"] == 1
    assert job["edited_result_storage_key"]
    winner_xml = Path(job["edited_result_storage_key"]).read_text(encoding="utf-8")
    assert winner_xml
    assert xml_path.read_text(encoding="utf-8") == canonical
    assert (isolated_db / f"{job_id}.raw.mid").read_bytes() == original
    bundles = list((isolated_db / f"{job_id}.edits").glob("*")) if (isolated_db / f"{job_id}.edits").exists() else []
    published = Path(job["edited_result_storage_key"]).parent
    for bundle in bundles:
        if bundle.resolve() != published.resolve():
            assert not bundle.exists() or not any(bundle.iterdir())


def test_noop_regen_uses_detected_audio_tempo_not_midi_tempo(tmp_path, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    midi_bytes = _midi_bytes(
        [(60, 0.0, 0.5), (62, 0.5, 1.0), (64, 1.0, 1.5), (65, 1.5, 2.0)],
        tempo=120,
    )
    source = tmp_path / "audio-tempo.mid"
    source.write_bytes(midi_bytes)
    ingested = ingest_midi(source)
    assert abs(ingested.tempo_map.bpm_at(0) - 120) < 1
    time_map = MusicalTimeMap.from_bpm(90.0, duration_sec=4.0)
    context = InterpretationContext(
        time_map=time_map,
        selected_meter="4/4",
        key_name="C",
        display_bpm=90.0,
        accepted_source_note_ids=tuple(n.note_id for n in ingested.notes),
        midi_sha256=ingested.performance.midi_sha256,
        source_backend="basic_pitch",
    )
    first = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    second = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    assert first.transcribed is False and second.transcribed is False
    assert first.fallback is None
    notes_a, meters_a, keys_a, _tempi_a = _musical_inventory(first.musicxml)
    notes_b, meters_b, keys_b, _tempi_b = _musical_inventory(second.musicxml)
    assert notes_a == notes_b
    assert meters_a[0] == meters_b[0] == "4/4"
    assert keys_a == keys_b
    starts = [row["quantized_start"] for row in first.decisions]
    # 90 BPM maps 0.5s attacks onto 0.75-beat spacing, not 120 BPM quarters.
    assert starts[1] == pytest.approx(0.75, abs=0.08)
    silent = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        tempo_map=ingested.tempo_map,
    )
    midi_starts = [row["quantized_start"] for row in silent.decisions]
    assert midi_starts[1] == pytest.approx(1.0, abs=0.08)
    assert starts != midi_starts


def test_missing_legacy_context_is_explicit(monkeypatch):
    _fail_if_transcribe(monkeypatch)
    midi_bytes = _midi_bytes([(60, 0.0, 0.5)])
    with pytest.raises(InterpretationContextError, match="refusing silent"):
        recompute_notation(
            midi_bytes=midi_bytes,
            settings=NotationSettings(),
            fallback=FALLBACK_MISSING,
        )


def test_basic_pitch_snapshot_identity(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf
    from mir.pipeline import UnderstandingPipeline
    from mir.types import InstrumentKind, InstrumentPrediction, NoteEvent

    monkeypatch.setenv("TRANSCRIPTION_USE_BEAT_TRACKER", "0")
    notes = [
        NoteEvent(
            pitch=60,
            start_time=0.0,
            end_time=0.5,
            velocity=80,
            confidence=0.9,
            source_backend="basic_pitch",
            note_id="bp-n0",
        ),
        NoteEvent(
            pitch=64,
            start_time=0.5,
            end_time=1.0,
            velocity=70,
            confidence=0.8,
            source_backend="basic_pitch",
            note_id="bp-n1",
        ),
    ]
    monkeypatch.setattr(
        "adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes",
        lambda self, path: list(notes),
    )
    monkeypatch.setattr(
        "audio_engine.instrument_classifier.InstrumentClassifier.classify",
        lambda self, audio: InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.9),
    )
    monkeypatch.setattr("mir.pipeline.AudioSegmenter.segment", lambda self, audio: [])
    audio = tmp_path / "bp.wav"
    sr = 22050
    t = np.linspace(0, 1, sr, endpoint=False)
    sf.write(str(audio), 0.2 * np.sin(2 * np.pi * 440 * t), sr)
    xml = UnderstandingPipeline(backend_name="basic_pitch").transcribe(audio, "bp-id")
    assert "score-partwise" in xml.lower()
    out = tmp_path / "bp_bp-id"
    raw = (out / "bp-id.raw.mid").read_bytes()
    snap = json.loads((out / "bp-id.performance.json").read_text())
    digest = hashlib.sha256(raw).hexdigest()
    assert snap["midi_sha256"] == digest
    assert snap["source_backend"] == "basic_pitch"
    ids = [n["note_id"] for n in snap["notes"]]
    assert ids == ["bp-n0", "bp-n1"]
    PerformanceSnapshot.read_json(out / "bp-id.performance.json").verify_midi(raw)


def test_mt3_snapshot_identity(tmp_path, monkeypatch):
    import base64
    import numpy as np
    import soundfile as sf
    from mir.pipeline import UnderstandingPipeline
    from mir.types import InstrumentKind, InstrumentPrediction

    midi_bytes = _midi_bytes([(67, 0.0, 0.5)])
    monkeypatch.setenv("MT3_ENDPOINT", "https://api.runpod.ai/v2/example/runsync")
    monkeypatch.setenv("MT3_API_KEY", "rp-secret")
    monkeypatch.delenv("MT3_TRANSCRIBE_COMMAND", raising=False)
    monkeypatch.setenv("TRANSCRIPTION_USE_BEAT_TRACKER", "0")
    monkeypatch.setattr(
        "audio_engine.instrument_classifier.InstrumentClassifier.classify",
        lambda self, audio: InstrumentPrediction(instrument=InstrumentKind.PIANO, confidence=0.9),
    )
    monkeypatch.setattr("mir.pipeline.AudioSegmenter.segment", lambda self, audio: [])

    class _FakeResponse:
        def __init__(self, body: bytes):
            self.body = body
            self.headers = {"Content-Type": "application/json"}

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        payload = {
            "status": "COMPLETED",
            "output": {"midi_base64": base64.b64encode(midi_bytes).decode()},
        }
        return _FakeResponse(json.dumps(payload).encode())

    monkeypatch.setattr("adapters.mt3_backend.urllib.request.urlopen", fake_urlopen)
    audio = tmp_path / "mt3.wav"
    sr = 22050
    t = np.linspace(0, 1, sr, endpoint=False)
    sf.write(str(audio), 0.2 * np.sin(2 * np.pi * 440 * t), sr)
    xml = UnderstandingPipeline(backend_name="mt3").transcribe(audio, "mt3-id")
    assert "score-partwise" in xml.lower()
    out = tmp_path / "bp_mt3-id"
    raw = (out / "mt3-id.raw.mid").read_bytes()
    assert raw == midi_bytes
    snap = json.loads((out / "mt3-id.performance.json").read_text())
    assert snap["midi_sha256"] == hashlib.sha256(midi_bytes).hexdigest()
    assert snap["source_backend"] == "mt3"
    PerformanceSnapshot.read_json(out / "mt3-id.performance.json").verify_midi(raw)


def test_basic_pitch_fallback_from_mt3_stamps_reconstructed_identity(
    tmp_path, monkeypatch
):
    from tests.test_live_orchestrator_job import _live_env, _wav
    from tests.test_transcription_fallback import (
        _install_empty_mt3_http,
        _midi_bytes as _fb_midi,
        _support_mocks,
    )
    from engine.orchestrator import PipelineOrchestrator
    from mir.raw_midi import job_raw_midi_path

    _live_env(monkeypatch)
    http_calls: list[str] = []
    bp_calls: list[str] = []
    _install_empty_mt3_http(monkeypatch, _fb_midi(), http_calls)
    _support_mocks(monkeypatch, tmp_path, bp_calls=bp_calls)
    audio = _wav(tmp_path / "fb.wav")
    result = PipelineOrchestrator().run(audio, "fb-id", mode="polyphonic")
    assert "score-partwise" in result.musicxml.lower()
    raw = job_raw_midi_path(audio, "fb-id").read_bytes()
    snap_path = Path(audio).parent / "bp_fb-id" / "fb-id.performance.json"
    snap = json.loads(snap_path.read_text())
    assert snap["midi_sha256"] == hashlib.sha256(raw).hexdigest()
    assert snap["source_backend"] == "basic_pitch"
    ids = [n["note_id"] for n in snap["notes"]]
    assert "n0000" in ids
    PerformanceSnapshot.read_json(snap_path).verify_midi(raw)


def test_pitch_edit_survives_notation_setting_change(isolated_db, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    import database as db
    import main as app_main
    from score_edits import extract_from_performance, loads_edits

    job_id = f"edit-{uuid.uuid4().hex[:12]}"
    xml_path, original, _digest = _prepare_job(isolated_db, job_id)
    db.create_job(_job_row(job_id, result_storage_key=str(xml_path), edit_revision=0))
    job = db.get_job(job_id)
    model = app_main._load_edit_model(job)
    notes = [dict(row) for row in model["notes"]]
    target = next(row for row in notes if row.get("source_note_id") or row.get("id"))
    original_pitch = int(target["pitch"])
    target["pitch"] = original_pitch + 2
    saved = app_main.score_edits_put(
        job_id,
        app_main.ScoreEditsIn(
            revision=0,
            notes=notes,
            tempo_bpm=model["tempo_bpm"],
            time_signature=model["time_signature"],
            tempo_curve=model.get("tempo_curve"),
        ),
        authorization=None,
    )
    assert saved["has_edits"] is True
    posted = app_main.job_notation_settings_post(
        job_id,
        app_main.NotationSettingsIn(interpretation="literal", revision=1),
        authorization=None,
    )
    assert posted["transcribed"] is False
    job = db.get_job(job_id)
    edited = loads_edits(
        Path(job["edited_result_storage_key"]).with_name(f"{job_id}.edits.json").read_text()
    )
    kept = next(
        row
        for row in edited["notes"]
        if row.get("source_note_id") == target.get("source_note_id")
        or row["id"] == target["id"]
    )
    assert int(kept["pitch"]) == original_pitch + 2
    assert (isolated_db / f"{job_id}.raw.mid").read_bytes() == original
    _ = extract_from_performance


def test_score_midi_matches_regenerated_musicxml(tmp_path, monkeypatch):
    _fail_if_transcribe(monkeypatch)
    source = tmp_path / "match.mid"
    FIXTURES["humanized_quarters"](source)
    from mir.midi_ingest import ingest_midi
    from mir.performance_cli import convert

    convert(source, tmp_path / "match.musicxml")
    context = InterpretationContext.read_json(tmp_path / "match.interpretation_context.json")
    ingested = ingest_midi(source)
    result = recompute_notation(
        midi_bytes=source.read_bytes(),
        settings=NotationSettings.literal(),
        performance=ingested.performance,
        context=context,
    )
    assert result.score_midi
    xml_notes, *_ = _musical_inventory(result.musicxml)
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mid") as handle:
        handle.write(result.score_midi)
        handle.flush()
        exported = pretty_midi.PrettyMIDI(handle.name)
    midi_pitches = sorted(int(n.pitch) for inst in exported.instruments for n in inst.notes)
    xml_pitches = sorted(pitch for pitch, _start, _dur in xml_notes)
    assert midi_pitches == xml_pitches
    assert len(midi_pitches) == len(xml_notes)


def test_triplet_policy_disabled_does_not_use_unrestricted_exact():
    settings = NotationSettings.from_dict({"triplet_policy": "disabled"})
    hits = _onset_candidates(1 / 3, 0.08, settings)
    families = {family for _onset, family, _cost in hits}
    assert "triplet" not in families
    exceptions = []
    _onset_candidates(1 / 3 + 0.04, 0.02, settings, exceptions=exceptions)
    # A representable triplet that is the only way to keep the attack is recorded.
    if exceptions:
        assert exceptions[0]["kind"] == "triplet_policy"
        assert exceptions[0]["policy"] == "disabled"


def test_preserve_overlap_beats_pedal_tail_cap():
    settings = NotationSettings.from_dict({"overlap_handling": "preserve"})
    written = _duration(
        1.6,
        Fraction(0),
        Fraction(1),
        True,
        "binary",
        release_reason="pedal_tail",
        release_at=Fraction(1),
        settings=settings,
    )
    assert float(written) > 1.25
    assert float(written) != pytest.approx(1.0, abs=0.05)
    shortened = _duration(
        1.6,
        Fraction(0),
        Fraction(1),
        True,
        "binary",
        release_reason="pedal_tail",
        release_at=Fraction(1),
        settings=NotationSettings(),
    )
    assert float(shortened) <= 1.0 + 1e-9


def test_show_meter_keeps_onbeat_whole_and_half_notes():
    settings = NotationSettings.from_dict({"syncopation": "show_meter"})
    whole = list(_pieces(Fraction(0), Fraction(4), Fraction(1), settings, Fraction(4)))
    assert whole == [(Fraction(0), Fraction(4))]
    half = list(_pieces(Fraction(0), Fraction(2), Fraction(1), settings, Fraction(4)))
    assert half == [(Fraction(0), Fraction(2))]
    sync = list(_pieces(Fraction(1, 4), Fraction(1), Fraction(1), settings, Fraction(4)))
    assert len(sync) >= 2


def test_regional_display_grid_changes_only_the_overridden_passage():
    events = [
        MusicalEvent(72, 0.0, 0.3, note_id="m1a", hand=Hand.RIGHT, velocity=80),
        MusicalEvent(72, 1 / 3, 0.3, note_id="m1b", hand=Hand.RIGHT, velocity=80),
        MusicalEvent(72, 4.0, 0.3, note_id="m2a", hand=Hand.RIGHT, velocity=80),
        MusicalEvent(72, 4 + 1 / 3, 0.3, note_id="m2b", hand=Hand.RIGHT, velocity=80),
    ]
    settings = NotationSettings.from_dict(
        {
            "triplet_policy": "enabled",
            "measure_overrides": [
                {"start_measure": 2, "end_measure": 2, "triplet_policy": "disabled"}
            ],
        }
    )
    _out, decisions, report = quantize_notation(
        events, METER, config=QuantizerConfig(), settings=settings
    )
    first = [row for row in decisions if float(row["quantized_start"]) < 4]
    second = [row for row in decisions if float(row["quantized_start"]) >= 4]
    assert first and second
    assert any(row["rhythm_family"] == "triplet" for row in first)
    m2b = next(row for row in second if row["note_id"] == "m2b")
    assert m2b["rhythm_family"] != "triplet"


def test_meaningful_rests_without_redundant_lane_filler():
    events = [
        MusicalEvent(72, 0.0, 1.0, note_id="rh", hand=Hand.RIGHT, voice=0, voice_assigned=True),
        MusicalEvent(74, 2.0, 1.0, note_id="rh2", hand=Hand.RIGHT, voice=0, voice_assigned=True),
        MusicalEvent(48, 0.0, 4.0, note_id="lh", hand=Hand.LEFT, voice=0, voice_assigned=True),
        MusicalEvent(50, 0.5, 0.25, note_id="inner", hand=Hand.LEFT, voice=1, voice_assigned=True),
    ]
    from mir.quantizer import MeasureQuantizer

    result = MeasureQuantizer().quantize_production(events, METER)
    measures = build_exact_measures(result.events, result.report, METER, "C")
    musical = [
        el
        for measure in measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedRest) and el.kind == "musical" and not el.hidden
    ]
    structural = [
        el
        for measure in measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedRest) and el.kind == "structural"
    ]
    assert any(float(r.duration_q) >= 0.5 - 1e-9 for r in musical)
    assert structural
    notes = [
        el
        for measure in measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedNote)
    ]
    assert notes
