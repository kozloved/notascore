"""MusicXML export must not crash with music21 Stream.insert(0, None)."""

from __future__ import annotations

import pytest
from music21 import note as m21note
from music21 import stream
from music21.exceptions21 import StreamException

from mir.models import (
    NotationPlan,
    PlannedMeasure,
    PlannedNote,
    PlannedRest,
    PlannedStaff,
    PlannedVoice,
)
from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.writer import NotationWriter


def _meta(ts="4/4", bpm=120) -> ScoreMeta:
    return ScoreMeta(display_tempo_bpm=bpm, time_sig_hint=ts)


def _ev(pitch, start, dur, hand=Hand.RIGHT, voice=0, **kwargs) -> MusicalEvent:
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        hand=hand,
        voice=voice,
        velocity=kwargs.get("velocity", 80),
        note_id=kwargs.get("note_id", ""),
    )


def _plan_with_elements(elements, key_signature="C", time_signature="4/4") -> NotationPlan:
    return NotationPlan(
        tempo_bpm=120,
        time_signature=time_signature,
        key_signature=key_signature,
        measures=[
            PlannedMeasure(
                number=1,
                start_beat=0.0,
                duration_beats=4.0,
                time_signature=time_signature,
                key_signature=key_signature,
                staves=[
                    PlannedStaff(
                        staff_id=0,
                        clef="treble",
                        voices=[PlannedVoice(voice_id=0, elements=list(elements))],
                    )
                ],
            )
        ],
    )


def _write(score, tmp_path, name="export"):
    path = tmp_path / f"{name}.musicxml"
    score.write("musicxml", fp=str(path))
    return path.read_text(encoding="utf-8")


def test_music21_insert_none_at_zero_is_item_zero_error():
    with pytest.raises(StreamException, match=r"Cannot insert item 0 to stream"):
        stream.Stream().insert(0, None)


def test_safe_insert_ignores_none_and_zero():
    container = stream.Stream()
    assert NotationWriter._safe_insert(container, 0, None) is False
    assert NotationWriter._safe_insert(container, 0, 0) is False
    assert len(container) == 0
    assert NotationWriter._safe_insert(container, 0, m21note.Note(midi=60)) is True
    assert len(container) == 1


def test_empty_pitch_planned_note_exports_as_rest(tmp_path):
    plan = _plan_with_elements(
        [
            PlannedNote(pitches=[], start_q=0.0, duration_q=1.0, voice=0),
            PlannedRest(start_q=1.0, duration_q=3.0, voice=0),
        ]
    )
    score = NotationWriter().score_from_plan(plan)
    xml = _write(score, tmp_path, "empty-pitch")
    assert "score-partwise" in xml.lower()
    assert "<rest" in xml.lower()
    assert "Cannot insert item 0" not in xml


def test_invalid_key_and_time_signature_still_export(tmp_path):
    plan = _plan_with_elements(
        [PlannedRest(start_q=0.0, duration_q=4.0, voice=0)],
        key_signature="",
        time_signature="",
    )
    score = NotationWriter().score_from_plan(plan, meta=_meta())
    xml = _write(score, tmp_path, "invalid-meta")
    assert "score-partwise" in xml.lower()


def test_voice_overflow_is_clamped_before_musicxml_write(tmp_path):
    writer = NotationWriter()
    voice = stream.Voice(id="1")
    for _ in range(4):
        voice.append(m21note.Note(midi=72, quarterLength=1.0))
    voice.append(m21note.Rest(quarterLength=0.05))
    assert float(voice.highestTime) > 4.0
    writer._fit_stream_to_quarter_length(voice, 4.0)
    assert float(voice.highestTime) <= 4.0 + 1e-6

    plan = _plan_with_elements(
        [
            PlannedNote(pitches=[72], start_q=0.0, duration_q=4.05, voice=0),
        ]
    )
    xml = _write(writer.score_from_plan(plan), tmp_path, "overflow")
    assert "score-partwise" in xml.lower()


def test_write_musicxml_survives_polyphonic_overlap_and_barline(tmp_path):
    events = [
        _ev(60, 0.0, 1.0, Hand.RIGHT, note_id="a"),
        _ev(64, 0.5, 1.0, Hand.RIGHT, note_id="b"),
        _ev(72, 3.0, 2.0, Hand.RIGHT, note_id="c"),
        _ev(48, 0.0, 4.0, Hand.LEFT, note_id="d"),
    ]
    xml = NotationWriter().write_musicxml(
        events, _meta(), job_id="overlap-barline", audio_path=tmp_path / "clip.wav"
    )
    assert "score-partwise" in xml.lower()
    assert "<staves>2</staves>" in xml.lower() or "part-group" in xml.lower()


def test_write_musicxml_survives_tiny_and_inexpressible_durations(tmp_path):
    events = [
        _ev(60 + i, i * 0.0625, 0.0625, Hand.RIGHT, note_id=f"t{i}")
        for i in range(64)
    ]
    xml = NotationWriter().write_musicxml(
        events, _meta(), job_id="tiny-grid", audio_path=tmp_path / "clip.wav"
    )
    assert "score-partwise" in xml.lower()


def test_export_retries_when_make_notation_inserts_none(tmp_path, monkeypatch):
    events = [
        _ev(72, 0.0, 1.0, Hand.RIGHT, note_id="a"),
        _ev(48, 0.0, 1.0, Hand.LEFT, note_id="b"),
    ]
    writer = NotationWriter()
    score = writer.write_from_events_direct(events, _meta())
    xml_path = tmp_path / "retry.musicxml"
    calls = {"n": 0}
    original = score.write

    def flaky(fmt=None, fp=None, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise StreamException(
                "Cannot insert item 0 to stream -- is it a music21 object?"
            )
        return original(fmt=fmt, fp=fp, **kwargs)

    monkeypatch.setattr(score, "write", flaky)
    writer._export_musicxml(score, xml_path)
    assert calls["n"] >= 2
    assert xml_path.exists()
    assert "score-partwise" in xml_path.read_text(encoding="utf-8").lower()
