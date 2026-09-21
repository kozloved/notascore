"""Shared planner export for automatic and edited scores (milestone 1)."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pretty_midi
import pytest
from music21 import converter

from mir.interpretation_context import InterpretationContext
from mir.midi_ingest import ingest_midi
from mir.notation_regen import NotationEditConflict, recompute_notation
from mir.notation_settings import NotationSettings
from mir.performance_score import report_from_events
from mir.types import Hand, MusicalEvent
from timing.tempo_map import MusicalTimeMap


def _write_midi(path: Path, notes, *, tempo=120, program=0, name="Piano"):
    midi = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    inst = pretty_midi.Instrument(program=program, name=name)
    for pitch, start, end, velocity in notes:
        inst.notes.append(
            pretty_midi.Note(velocity=velocity, pitch=pitch, start=start, end=end)
        )
    midi.instruments.append(inst)
    midi.write(str(path))
    return path.read_bytes()


def _context_for(ingested, **overrides):
    notes = ingested.notes
    duration = max((n.end_time for n in notes), default=8.0)
    time_map = MusicalTimeMap.from_tempo_map(ingested.tempo_map, duration_sec=max(duration, 4.0))
    kind = notes[0].instrument
    instrument = kind.value if hasattr(kind, "value") else str(kind or "piano")
    payload = dict(
        time_map=time_map,
        selected_meter="4/4",
        key_name="C",
        display_bpm=120.0,
        accepted_source_note_ids=tuple(n.note_id for n in notes),
        has_recorded_selection=True,
        midi_sha256=ingested.performance.midi_sha256,
        source_backend="midi",
        instrument=instrument or "piano",
    )
    payload.update(overrides)
    return InterpretationContext(**payload)


def _xml_shape(xml_text: str):
    """Engraving structure used to compare automatic vs edited exports."""
    score = converter.parse(xml_text, format="musicxml")
    parts = []
    for part in score.parts:
        inst = part.getInstrument()
        part_row = {
            "name": str(part.partName or ""),
            "instrument": str(getattr(inst, "instrumentName", None) or ""),
            "measures": [],
        }
        for measure in part.getElementsByClass("Measure"):
            voices: dict[str, list] = {}
            for el in measure.recurse().notesAndRests:
                site = el.activeSite
                if site is not None and site.__class__.__name__ == "Voice":
                    vid = str(site.id)
                else:
                    vid = str(getattr(el, "voice", None) or "1")
                members = list(el.notes) if el.isChord else [el]
                pitches = [
                    int(m.pitch.midi)
                    for m in members
                    if getattr(m, "pitch", None) is not None
                ]
                voices.setdefault(vid, []).append(
                    {
                        "offset": round(float(el.offset), 4),
                        "ql": round(float(el.quarterLength), 4),
                        "pitches": pitches,
                        "is_rest": bool(el.isRest),
                        "tie": getattr(getattr(el, "tie", None), "type", None),
                        "beams": tuple(
                            sorted(
                                str(getattr(beam, "type", beam))
                                for beam in (getattr(el, "beams", None) or [])
                            )
                        ),
                        "stem": str(getattr(el, "stemDirection", None) or ""),
                        "tuplets": tuple(
                            (
                                int(getattr(tup, "numberNotesActual", 0) or 0),
                                int(getattr(tup, "numberNotesNormal", 0) or 0),
                            )
                            for tup in (getattr(getattr(el, "duration", None), "tuplets", None) or [])
                        ),
                        "articulations": tuple(
                            sorted(
                                type(art).__name__
                                for art in (getattr(el, "articulations", None) or [])
                            )
                        ),
                    }
                )
            clef = None
            if measure.clef is not None:
                clef = str(getattr(measure.clef, "sign", None) or measure.clef)
            key_name = None
            if measure.keySignature is not None:
                key_name = str(measure.keySignature)
            part_row["measures"].append(
                {
                    "number": int(measure.number),
                    "voices": [
                        {"id": vid, "elements": voices[vid]} for vid in sorted(voices)
                    ],
                    "ts": getattr(measure.timeSignature, "ratioString", None),
                    "clef": clef,
                    "key": key_name,
                }
            )
        parts.append(part_row)
    return {
        "part_count": len(parts),
        "parts": parts,
        "time_signatures": [ts.ratioString for ts in score.flatten().getTimeSignatures()],
    }


def _xml_velocities(xml_text: str) -> list[int]:
    score = converter.parse(xml_text, format="musicxml")
    values = []
    for el in score.flatten().notes:
        members = list(el.notes) if el.isChord else [el]
        for member in members:
            vel = member.volume.velocity
            if vel is None:
                vel = el.volume.velocity
            values.append(int(vel or 0))
    return values


def _sid(result, pitch, start=None):
    for row in result.editor_model["notes"]:
        if int(row["pitch"]) != pitch:
            continue
        if start is not None and abs(float(row["start"]) - start) > 0.2:
            continue
        return row.get("source_note_id") or row["id"]
    raise AssertionError(f"missing source note pitch={pitch} start={start}")


def test_velocity_only_edit_keeps_engraving_semantics(tmp_path):
    midi_bytes = _write_midi(
        tmp_path / "vel.mid",
        [
            (72, 0.0, 0.45, 80),
            (74, 0.5, 0.95, 80),
            (76, 1.0, 1.45, 80),
            (77, 1.5, 1.95, 80),
            (48, 0.0, 1.9, 70),
        ],
    )
    original = hashlib.sha256(midi_bytes).hexdigest()
    ingested = ingest_midi(tmp_path / "vel.mid")
    context = _context_for(ingested, instrument="piano")
    auto = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    sid = _sid(auto, 74, 1.0)
    edited = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=auto.context,
        corrections=[{"source_note_id": sid, "velocity": 110}],
    )
    assert hashlib.sha256(midi_bytes).hexdigest() == original
    assert ingested.performance.midi_sha256 == original
    assert _xml_shape(auto.musicxml) == _xml_shape(edited.musicxml)
    assert 110 in _xml_velocities(edited.musicxml)
    assert _xml_velocities(auto.musicxml) != _xml_velocities(edited.musicxml)


def test_two_voices_on_one_staff_survive_duration_edit(tmp_path):
    beat = 0.5
    midi_bytes = _write_midi(
        tmp_path / "voices.mid",
        [
            # C5 held plus a moving upper line stay in the right hand so
            # both independent voices land on the same staff.
            (72, 0.0, beat * 4.0, 70),
            (76, 0.0, beat * 0.9, 86),
            (77, beat, beat * 1.9, 86),
            (79, beat * 2, beat * 2.9, 86),
            (81, beat * 3, beat * 3.9, 86),
        ],
    )
    ingested = ingest_midi(tmp_path / "voices.mid")
    context = _context_for(ingested)
    auto = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    shape = _xml_shape(auto.musicxml)
    treble = shape["parts"][0]
    voice_ids = {voice["id"] for measure in treble["measures"] for voice in measure["voices"]}
    assert len(voice_ids) >= 2
    held = _sid(auto, 72, 0.0)
    moving = _sid(auto, 79)
    auto_moving = next(n for n in auto.editor_model["notes"] if n["source_note_id"] == moving)
    auto_duration = float(auto_moving["duration"])
    edited_duration = 0.25 if auto_duration > 0.4 else 1.0
    assert abs(auto_duration - edited_duration) > 1e-6
    edited = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=auto.context,
        corrections=[{"source_note_id": moving, "duration": edited_duration}],
    )
    edited_shape = _xml_shape(edited.musicxml)
    edited_voices = {
        voice["id"]
        for measure in edited_shape["parts"][0]["measures"]
        for voice in measure["voices"]
    }
    assert len(edited_voices) >= 2
    held_row = next(n for n in edited.editor_model["notes"] if n["source_note_id"] == held)
    moving_row = next(n for n in edited.editor_model["notes"] if n["source_note_id"] == moving)
    assert float(held_row["duration"]) == pytest.approx(float(
        next(n for n in auto.editor_model["notes"] if n["source_note_id"] == held)["duration"]
    ))
    assert float(moving_row["duration"]) == pytest.approx(edited_duration)


def test_barline_tie_and_unrelated_measure_stay_stable(tmp_path):
    beat = 0.5
    midi_bytes = _write_midi(
        tmp_path / "tie.mid",
        [
            (60, beat * 2, beat * 6, 80),
            (72, beat * 8, beat * 8.9, 82),
        ],
    )
    ingested = ingest_midi(tmp_path / "tie.mid")
    context = _context_for(ingested)
    auto = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    auto_shape = _xml_shape(auto.musicxml)
    ties = [
        el["tie"]
        for part in auto_shape["parts"]
        for measure in part["measures"]
        for voice in measure["voices"]
        for el in voice["elements"]
        if el["tie"]
    ]
    assert "start" in ties and "stop" in ties
    later = _sid(auto, 72)
    edited = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=auto.context,
        corrections=[{"source_note_id": later, "start": 8.0, "duration": 1.0}],
    )
    edited_shape = _xml_shape(edited.musicxml)
    assert auto_shape["parts"][0]["measures"][0] == edited_shape["parts"][0]["measures"][0]
    assert auto_shape["part_count"] == edited_shape["part_count"]
    later_row = next(n for n in edited.editor_model["notes"] if n["source_note_id"] == later)
    assert float(later_row["start"]) == pytest.approx(8.0)
    assert float(later_row["duration"]) == pytest.approx(1.0)


def test_non_piano_single_staff_survives_velocity_edit(tmp_path):
    midi_bytes = _write_midi(
        tmp_path / "violin.mid",
        [(67, 0.0, 0.45, 80), (69, 0.5, 0.95, 80), (71, 1.0, 1.45, 80), (72, 1.5, 1.95, 80)],
        program=40,
        name="Violin",
    )
    ingested = ingest_midi(tmp_path / "violin.mid")
    context = _context_for(ingested, instrument="strings")
    auto = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    auto_shape = _xml_shape(auto.musicxml)
    assert auto_shape["part_count"] == 1
    names = " ".join(
        f"{part['name']} {part['instrument']}" for part in auto_shape["parts"]
    ).lower()
    assert "piano" not in names
    sid = _sid(auto, 69)
    edited = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=auto.context,
        corrections=[{"source_note_id": sid, "velocity": 100}],
    )
    edited_shape = _xml_shape(edited.musicxml)
    assert edited_shape["part_count"] == 1
    assert auto_shape == edited_shape
    assert 100 in _xml_velocities(edited.musicxml)


def test_unspellable_edited_duration_is_rejected(tmp_path):
    midi_bytes = _write_midi(tmp_path / "odd.mid", [(60, 0.0, 0.5, 80)])
    ingested = ingest_midi(tmp_path / "odd.mid")
    context = _context_for(ingested)
    auto = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    sid = _sid(auto, 60, 0.0)
    with pytest.raises(NotationEditConflict, match="cannot be engraved"):
        recompute_notation(
            midi_bytes=midi_bytes,
            settings=NotationSettings(),
            performance=ingested.performance,
            context=auto.context,
            corrections=[{"source_note_id": sid, "duration": 0.1}],
        )


def test_locked_timing_is_not_overwritten_by_quantizer():
    from mir.models import MeterHypothesis
    from mir.performance_score import quantize_notation
    from mir.quantizer import QuantizerConfig

    events = [
        MusicalEvent(
            72,
            0.51,
            0.97,
            velocity=80,
            note_id="locked",
            hand=Hand.RIGHT,
            voice=0,
            source_backend="midi",
            score_timing_locked=True,
        ),
        MusicalEvent(
            60,
            0.0,
            1.0,
            velocity=70,
            note_id="free",
            hand=Hand.LEFT,
            voice=0,
            source_backend="midi",
        ),
    ]
    meter = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
    out, _decisions, _report = quantize_notation(events, meter, config=QuantizerConfig())
    by_id = {ev.note_id: ev for ev in out}
    assert by_id["locked"].start_beat == pytest.approx(0.51, abs=1e-6)
    assert by_id["locked"].duration_beats == pytest.approx(0.97, abs=1e-6)
    assert by_id["free"].start_beat == pytest.approx(0.0, abs=0.05)


def test_report_from_events_reuses_previous_lanes_for_velocity():
    events = [
        MusicalEvent(60, 0.0, 1.0, velocity=80, note_id="n1", hand=Hand.RIGHT, voice=0),
        MusicalEvent(64, 1.0, 1.0, velocity=80, note_id="n2", hand=Hand.RIGHT, voice=0),
    ]
    first = report_from_events(events)
    louder = [
        MusicalEvent(60, 0.0, 1.0, velocity=110, note_id="n1", hand=Hand.RIGHT, voice=0),
        MusicalEvent(64, 1.0, 1.0, velocity=80, note_id="n2", hand=Hand.RIGHT, voice=0),
    ]
    second = report_from_events(louder, previous=first)
    assert [n.onset for n in first.notes] == [n.onset for n in second.notes]
    assert [n.duration for n in first.notes] == [n.duration for n in second.notes]
    assert [n.voice for n in first.notes] == [n.voice for n in second.notes]
    assert [n.group_id for n in first.notes] == [n.group_id for n in second.notes]


def test_supplied_articulation_survives_velocity_edit_and_rest_is_not_staccato(tmp_path):
    midi_bytes = _write_midi(
        tmp_path / "marks.mid",
        [
            (76, 0.0, 0.10, 88),
            (77, 0.5, 0.60, 88),
            (79, 1.0, 1.45, 80),
        ],
    )
    ingested = ingest_midi(tmp_path / "marks.mid")
    context = _context_for(ingested)
    auto = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    short = _sid(auto, 76, 0.0)
    later = _sid(auto, 79)
    assert all(not n.get("articulation") for n in auto.editor_model["notes"])
    marked = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=auto.context,
        corrections=[{"source_note_id": later, "articulation": "staccato"}],
    )
    marked_row = next(n for n in marked.editor_model["notes"] if n["source_note_id"] == later)
    assert marked_row["articulation"] == "staccato"
    short_row = next(n for n in marked.editor_model["notes"] if n["source_note_id"] == short)
    assert not short_row.get("articulation")
    louder = recompute_notation(
        midi_bytes=midi_bytes,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=marked.context,
        corrections=[{"source_note_id": later, "articulation": "staccato", "velocity": 110}],
    )
    assert _xml_shape(marked.musicxml) == _xml_shape(louder.musicxml)
    louder_row = next(n for n in louder.editor_model["notes"] if n["source_note_id"] == later)
    assert louder_row["articulation"] == "staccato"
    assert int(louder_row["velocity"]) == 110
    arts = [
        el["articulations"]
        for part in _xml_shape(louder.musicxml)["parts"]
        for measure in part["measures"]
        for voice in measure["voices"]
        for el in voice["elements"]
        if el["articulations"]
    ]
    assert any("Staccato" in names for names in arts)
