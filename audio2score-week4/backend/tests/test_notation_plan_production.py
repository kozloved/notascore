"""Production NotationPlan path: voices, ties, rests, chords, meters, fallback."""

from __future__ import annotations

from music21 import chord as m21chord, stream

from mir.models import PlannedNote, PlannedRest
from mir.quantizer import VOICE_SUM_TOLERANCE
from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.plan import NotationPlanner
from notation_engine.writer import NotationWriter


def _ev(pitch, start, dur, hand=Hand.RIGHT, voice=0, **kwargs) -> MusicalEvent:
    return MusicalEvent(
        pitch=pitch,
        start_beat=start,
        duration_beats=dur,
        hand=hand,
        voice=voice,
        velocity=kwargs.get("velocity", 80),
        articulation=kwargs.get("articulation"),
        dynamic=kwargs.get("dynamic"),
        note_id=kwargs.get("note_id", ""),
    )


def _meta(ts="4/4", bpm=120, **kwargs) -> ScoreMeta:
    return ScoreMeta(display_tempo_bpm=bpm, time_sig_hint=ts, **kwargs)


def _build(events, ts="4/4"):
    return NotationPlanner().build(events, meta=_meta(ts))


def _notes(plan, staff_id=0, voice_id=None):
    out = []
    for measure in plan.measures:
        for staff in measure.staves:
            if staff.staff_id != staff_id:
                continue
            for voice in staff.voices:
                if voice_id is not None and voice.voice_id != voice_id:
                    continue
                for el in voice.elements:
                    if isinstance(el, PlannedNote):
                        out.append((measure.number, voice.voice_id, el))
    return out


def _assert_voice_sums(plan, tol=VOICE_SUM_TOLERANCE):
    for measure in plan.measures:
        for staff in measure.staves:
            for voice in staff.voices:
                total = sum(el.duration_q for el in voice.elements)
                assert abs(total - measure.duration_beats) <= tol, (
                    measure.number,
                    staff.staff_id,
                    voice.voice_id,
                    total,
                    measure.duration_beats,
                )


def test_two_independent_voices_on_one_staff():
    events = [
        _ev(76, 0.0, 1.0, voice=0),
        _ev(77, 1.0, 1.0, voice=0),
        _ev(79, 2.0, 1.0, voice=0),
        _ev(81, 3.0, 1.0, voice=0),
        _ev(60, 0.0, 4.0, voice=1),
    ]
    plan, _ = _build(events)
    _assert_voice_sums(plan)
    rh = plan.measures[0].staves[0]
    assert len(rh.voices) == 2
    melody = [el for _, _, el in _notes(plan, 0, 0)]
    held = [el for _, _, el in _notes(plan, 0, 1)]
    assert [el.pitches for el in melody] == [[76], [77], [79], [81]]
    assert held and held[0].pitches == [60]
    for el in melody + held:
        assert len(el.pitches) == 1

    score = NotationWriter().score_from_plan(plan)
    xml = score.write("musicxml")
    text = xml.read_text(encoding="utf-8") if hasattr(xml, "read_text") else open(xml).read()
    assert "<voice>1</voice>" in text
    assert "<voice>2</voice>" in text
    for v in score.parts[0].recurse().getElementsByClass(stream.Voice):
        for el in v.notes:
            if isinstance(el, m21chord.Chord):
                midis = {p.midi for p in el.pitches}
                assert not (60 in midis and 76 in midis)


def test_sustained_bass_with_moving_melody():
    events = [
        _ev(72, 0.0, 1.0, hand=Hand.RIGHT, voice=0),
        _ev(74, 1.0, 1.0, hand=Hand.RIGHT, voice=0),
        _ev(76, 2.0, 1.0, hand=Hand.RIGHT, voice=0),
        _ev(77, 3.0, 1.0, hand=Hand.RIGHT, voice=0),
        _ev(48, 0.0, 4.0, hand=Hand.LEFT, voice=0),
    ]
    plan, _ = _build(events)
    _assert_voice_sums(plan)
    rh_notes = _notes(plan, staff_id=0)
    lh_notes = _notes(plan, staff_id=1)
    assert [el.pitches[0] for _, _, el in rh_notes] == [72, 74, 76, 77]
    assert lh_notes and lh_notes[0][2].pitches == [48]
    assert abs(lh_notes[0][2].duration_q - 4.0) < 1e-6


def test_note_crossing_barline_is_tied():
    events = [_ev(72, 3.0, 2.0)]
    plan, _ = _build(events)
    _assert_voice_sums(plan)
    notes = _notes(plan, staff_id=0, voice_id=0)
    assert len(plan.measures) >= 2
    first = [el for meas, _, el in notes if meas == 1]
    second = [el for meas, _, el in notes if meas == 2]
    assert first and second
    assert first[0].tie == "start"
    assert second[0].tie == "stop"
    assert first[0].pitches == second[0].pitches == [72]

    score = NotationWriter().score_from_plan(plan)
    xml = score.write("musicxml")
    text = xml.read_text(encoding="utf-8") if hasattr(xml, "read_text") else open(xml).read()
    assert 'type="start"' in text
    assert 'type="stop"' in text


def test_empty_measure_filled_with_rests():
    events = [_ev(72, 0.0, 1.0), _ev(74, 8.0, 1.0)]
    plan, _ = _build(events)
    _assert_voice_sums(plan)
    assert len(plan.measures) >= 3
    empty = plan.measures[1]
    for staff in empty.staves:
        for voice in staff.voices:
            assert all(isinstance(el, PlannedRest) for el in voice.elements)
            assert abs(sum(el.duration_q for el in voice.elements) - empty.duration_beats) < 1e-6


def test_syncopated_rhythm():
    events = [
        _ev(72, 0.0, 0.5),
        _ev(74, 0.5, 1.0),
        _ev(76, 1.5, 0.5),
        _ev(77, 2.0, 1.0),
        _ev(79, 3.0, 1.0),
    ]
    plan, _ = _build(events)
    _assert_voice_sums(plan)
    notes = [el for _, _, el in _notes(plan, 0, 0)]
    starts = [round(el.start_q, 3) for el in notes]
    assert 0.5 in starts
    held = next(el for el in notes if el.pitches == [74])
    assert abs(held.duration_q - 1.0) < 0.13


def test_dotted_rhythm():
    events = [
        _ev(72, 0.0, 0.75),
        _ev(74, 0.75, 0.25),
        _ev(76, 1.0, 0.75),
        _ev(77, 1.75, 0.25),
        _ev(79, 2.0, 1.0),
        _ev(81, 3.0, 1.0),
    ]
    plan, _ = _build(events)
    _assert_voice_sums(plan)
    notes = [el for _, _, el in _notes(plan, 0, 0)]
    assert any(abs(el.duration_q - 0.75) < 0.05 for el in notes)
    assert any(abs(el.duration_q - 0.25) < 0.05 for el in notes)


def test_triplets():
    events = [
        _ev(72, 0.0, 1.0 / 3.0),
        _ev(74, 1.0 / 3.0, 1.0 / 3.0),
        _ev(76, 2.0 / 3.0, 1.0 / 3.0),
        _ev(77, 1.0, 1.0 / 3.0),
        _ev(79, 4.0 / 3.0, 1.0 / 3.0),
        _ev(81, 5.0 / 3.0, 1.0 / 3.0),
        _ev(83, 2.0, 1.0),
        _ev(84, 3.0, 1.0),
    ]
    plan, _ = _build(events)
    _assert_voice_sums(plan)
    notes = [el for _, _, el in _notes(plan, 0, 0)]
    tripletish = [el for el in notes if abs(el.duration_q - (1.0 / 3.0)) < 0.05]
    assert len(tripletish) >= 3
    starts = [round(el.start_q, 5) for el in notes[:3]]
    assert starts[0] == 0.0
    assert abs(starts[1] - 1.0 / 3.0) < 0.05
    assert abs(starts[2] - 2.0 / 3.0) < 0.05


def test_chord_plus_independent_melodic_voice():
    events = [
        _ev(60, 0.0, 1.0, voice=0),
        _ev(64, 0.0, 1.0, voice=0),
        _ev(67, 0.0, 1.0, voice=0),
        _ev(72, 1.0, 1.0, voice=0),
        _ev(76, 0.0, 1.0, voice=1),
        _ev(77, 1.0, 1.0, voice=1),
        _ev(79, 2.0, 1.0, voice=1),
        _ev(81, 3.0, 1.0, voice=1),
    ]
    plan, _ = _build(events)
    _assert_voice_sums(plan)
    accompaniment = [el for _, _, el in _notes(plan, 0, 0)]
    melody = [el for _, _, el in _notes(plan, 0, 1)]
    chords = [el for el in accompaniment if len(el.pitches) >= 2]
    assert chords
    assert set(chords[0].pitches) == {60, 64, 67}
    assert all(76 not in el.pitches for el in accompaniment)
    assert [el.pitches[0] for el in melody] == [76, 77, 79, 81]

    score = NotationWriter().score_from_plan(plan)
    xml = score.write("musicxml")
    text = xml.read_text(encoding="utf-8") if hasattr(xml, "read_text") else open(xml).read()
    assert "<chord" in text.lower()
    assert "<voice>1</voice>" in text
    assert "<voice>2</voice>" in text


def test_rh_and_lh_simultaneously():
    events = [
        _ev(72, 0.0, 1.0, hand=Hand.RIGHT),
        _ev(76, 0.0, 1.0, hand=Hand.RIGHT),
        _ev(48, 0.0, 2.0, hand=Hand.LEFT),
        _ev(52, 0.0, 2.0, hand=Hand.LEFT),
    ]
    plan, _ = _build(events)
    _assert_voice_sums(plan)
    assert any(s.staff_id == 0 for s in plan.measures[0].staves)
    assert any(s.staff_id == 1 for s in plan.measures[0].staves)
    rh = [el for _, _, el in _notes(plan, 0)]
    lh = [el for _, _, el in _notes(plan, 1)]
    assert set(rh[0].pitches) == {72, 76}
    assert set(lh[0].pitches) == {48, 52}


def test_meter_3_4():
    events = [
        _ev(72, 0.0, 1.0),
        _ev(74, 1.0, 1.0),
        _ev(76, 2.0, 1.0),
        _ev(77, 3.0, 1.0),
        _ev(79, 4.0, 1.0),
        _ev(81, 5.0, 1.0),
    ]
    plan, _ = _build(events, ts="3/4")
    _assert_voice_sums(plan)
    assert plan.time_signature == "3/4"
    assert all(abs(m.duration_beats - 3.0) < 1e-6 for m in plan.measures)
    assert len(plan.measures) == 2


def test_meter_4_4():
    events = [_ev(60 + i, float(i), 1.0) for i in range(8)]
    plan, _ = _build(events, ts="4/4")
    _assert_voice_sums(plan)
    assert plan.time_signature == "4/4"
    assert all(abs(m.duration_beats - 4.0) < 1e-6 for m in plan.measures)
    assert len(plan.measures) == 2


def test_meter_6_8():
    events = []
    for bar in range(2):
        base = bar * 3.0
        events.extend(
            [
                _ev(72, base + 0.0, 0.5),
                _ev(74, base + 0.5, 0.5),
                _ev(76, base + 1.0, 0.5),
                _ev(77, base + 1.5, 0.5),
                _ev(79, base + 2.0, 0.5),
                _ev(81, base + 2.5, 0.5),
            ]
        )
    plan, _ = _build(events, ts="6/8")
    _assert_voice_sums(plan)
    assert plan.time_signature == "6/8"
    assert all(abs(m.duration_beats - 3.0) < 1e-6 for m in plan.measures)
    assert len(plan.measures) == 2


def test_write_musicxml_uses_notation_plan(tmp_path):
    events = [
        _ev(72, 0.0, 1.0, hand=Hand.RIGHT, articulation="staccato", dynamic="mf"),
        _ev(76, 0.0, 1.0, hand=Hand.RIGHT),
        _ev(48, 0.0, 4.0, hand=Hand.LEFT),
        _ev(67, 2.0, 1.0, hand=Hand.RIGHT),
    ]
    writer = NotationWriter()
    called = {"legacy": False}
    original = writer.build_score

    def wrapped(*args, **kwargs):
        called["legacy"] = True
        return original(*args, **kwargs)

    writer.build_score = wrapped
    xml = writer.write_musicxml(
        events, _meta("4/4"), job_id="prod-plan", audio_path=tmp_path / "clip.wav"
    )
    assert called["legacy"] is False
    assert writer.last_fallback_used is False
    assert writer.last_plan is not None
    assert writer.last_fallback_error is None
    lower = xml.lower()
    assert "score-partwise" in lower
    assert "<rest" in lower
    assert "<staves>2</staves>" in lower or "part-group" in lower
    assert "<metronome" in lower
    assert "<per-minute>120</per-minute>" in xml.replace(" ", "")
    assert (tmp_path / "bp_prod-plan" / "prod-plan.score.mid").exists()
    payload = writer.notation_debug_payload()
    assert payload["notation_path"] == "notation_plan"
    assert payload["fallback_used"] is False


def test_write_musicxml_falls_back_to_legacy_build_score(tmp_path):
    events = [
        _ev(72, 0.0, 1.0, hand=Hand.RIGHT),
        _ev(48, 0.0, 1.0, hand=Hand.LEFT),
    ]
    writer = NotationWriter()

    def boom(*_args, **_kwargs):
        raise RuntimeError("planner exploded")

    writer.planner.build = boom
    xml = writer.write_musicxml(
        events, _meta("4/4"), job_id="legacy-fallback", audio_path=tmp_path / "clip.wav"
    )
    assert writer.last_fallback_used is True
    assert writer.last_fallback_error is not None
    assert "planner exploded" in writer.last_fallback_error
    assert writer.notation_debug_payload()["notation_path"] == "legacy_build_score"
    assert "score-partwise" in xml.lower()
    assert "<metronome" in xml.lower()


def test_pipeline_debug_records_notation_path(tmp_path, monkeypatch):
    from unittest.mock import patch

    import numpy as np
    import soundfile as sf

    from mir.pipeline import UnderstandingPipeline
    from mir.types import NoteEvent

    monkeypatch.setenv("TRANSCRIPTION_USE_MIR_LAYERS", "1")
    notes = [
        NoteEvent(pitch=72, start_time=0.0, end_time=0.5, velocity=80, confidence=1.0),
        NoteEvent(pitch=48, start_time=0.0, end_time=1.0, velocity=70, confidence=1.0),
    ]
    audio = tmp_path / "debug.wav"
    sr = 22050
    t = np.linspace(0, 2, sr * 2)
    sf.write(str(audio), 0.2 * np.sin(2 * np.pi * 440 * t), sr)

    with patch(
        "adapters.basic_pitch_backend.BasicPitchBackend.transcribe_notes",
        return_value=notes,
    ):
        pipeline = UnderstandingPipeline()
        pipeline.transcribe(audio, "debug-plan")

    assert pipeline.last_debug is not None
    assert pipeline.last_debug.extra.get("notation_path") == "notation_plan"
    assert pipeline.last_debug.fallback_used is False
    debug_path = tmp_path / "bp_debug-plan" / "debug-plan.debug.json"
    assert debug_path.exists()
    text = debug_path.read_text(encoding="utf-8")
    assert "notation_plan" in text
