"""Strongly detached playing becomes written pulse notes, not tiny notes plus rests.

Readable convention, not recovered certainty. Pulse is inferred inside coherent
streams: offbeat accompaniment must not truncate a melody. Short regular on-beat
phrases fill when metrical position, a repeated pulse, and release consistency
agree. Locked / Literal notes stay short. Score playback of inferred staccato
must not sound the full written duration, and clearing that mark survives regen.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pretty_midi
from music21 import converter

from evaluation.notation_correctness_evidence import inspect_xml, musicxml_note_marks
from evaluation.readable_v2_cases import READABLE_V2_CASES
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.models import MeterHypothesis
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings
from mir.performance_score import quantize_notation
from mir.quantizer import QuantizerConfig
from mir.types import Hand, MusicalEvent
from notation_engine.playback import STACCATO_PLAYBACK_FRACTION, playback_duration_beats
from tests.test_shared_engraving import _context_for

METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
READABLE = NotationSettings()
LITERAL = NotationSettings.literal()
V2 = NotationSettings.readable_v2()
LEGACY = NotationSettings.legacy_readable()
CONFIG = QuantizerConfig()
CASE3 = (
    Path(__file__).resolve().parents[1]
    / "evaluation"
    / "development"
    / "NotaTestSamples"
    / "Case3"
    / "88_D_waltz_th_piano_raw.mid"
)


def _ev(pitch, start, dur, ident, hand=Hand.RIGHT, **kwargs):
    payload = dict(
        velocity=80,
        source_backend="midi",
        note_id=ident,
        hand=hand,
        hand_locked=True,
    )
    payload.update(kwargs)
    return MusicalEvent(pitch, start, dur, **payload)


def _quantize(events, settings, meter=METER):
    return quantize_notation(events, meter, config=CONFIG, settings=settings)


def _from_midi(path: Path, settings):
    ingested = ingest_midi(path)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    out, dec, _ = _quantize(events, settings)
    return out, dec, ingested


def _melody_quarters(count=8):
    return [_ev(72 + i, float(i), 0.20, f"rh{i}") for i in range(count)]


def _offbeat_left(count=8):
    return [
        _ev(48, float(i) + 0.5, 0.20, f"lh{i}", hand=Hand.LEFT) for i in range(count)
    ]


def _xml_note_durations(xml_text: str) -> list[float]:
    score = converter.parse(xml_text, format="musicxml")
    durs = []
    for part in score.parts:
        for el in part.recurse().notes:
            if el.isChord:
                continue
            durs.append(float(el.quarterLength))
    return durs


def test_strongly_detached_quarters_become_written_quarters():
    events = _melody_quarters()
    readable, dec, _ = _quantize(events, READABLE)
    literal, _, _ = _quantize(events, LITERAL)
    v2, _, _ = _quantize(events, V2)
    legacy, _, _ = _quantize(events, LEGACY)
    assert [round(e.duration_beats, 4) for e in readable] == [1.0] * 8
    assert [round(e.start_beat, 4) for e in readable] == [float(i) for i in range(8)]
    assert {e.note_id for e in readable} == {f"rh{i}" for i in range(8)}
    assert all(e.articulation == "staccato" for e in readable)
    assert all(e.articulation_source == "inferred" for e in readable)
    assert {row.get("articulation_source") for row in dec} == {"inferred"}
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in literal)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in v2)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in legacy)
    assert all(not e.articulation for e in literal)


def test_offbeat_accompaniment_does_not_truncate_the_melody():
    alone, _, _ = _quantize(_melody_quarters(), READABLE)
    paired, _, _ = _quantize(_melody_quarters() + _offbeat_left(), READABLE)
    melody = [e for e in paired if e.note_id.startswith("rh")]
    bass = [e for e in paired if e.note_id.startswith("lh")]
    assert [round(e.duration_beats, 4) for e in alone] == [1.0] * 8
    assert [round(e.duration_beats, 4) for e in melody] == [1.0] * 8
    assert [round(e.start_beat, 4) for e in melody] == [float(i) for i in range(8)]
    assert all(e.articulation == "staccato" for e in melody)
    assert [round(e.start_beat, 4) for e in bass] == [float(i) + 0.5 for i in range(8)]
    by_start = {round(e.start_beat, 4): round(e.duration_beats, 4) for e in bass}
    for beat in (0.5, 1.5, 2.5, 4.5, 5.5, 6.5):
        assert by_start[beat] == 1.0
    assert by_start[3.5] == 0.5
    assert by_start[7.5] == 0.5


def test_same_staff_independent_voice_does_not_truncate_the_melody():
    melody = [
        _ev(76 + i, float(i), 0.20, f"rh{i}", musical_voice=0, voice=0, voice_assigned=True)
        for i in range(8)
    ]
    inner = [
        _ev(
            60,
            float(i) + 0.5,
            0.20,
            f"in{i}",
            musical_voice=1,
            voice=1,
            voice_assigned=True,
        )
        for i in range(8)
    ]
    out, _, _ = _quantize(melody + inner, READABLE)
    upper = [e for e in out if e.note_id.startswith("rh")]
    lower = [e for e in out if e.note_id.startswith("in")]
    assert [round(e.duration_beats, 4) for e in upper] == [1.0] * 8
    assert [round(e.start_beat, 4) for e in upper] == [float(i) for i in range(8)]
    assert all(e.musical_voice != lower[0].musical_voice for e in upper)
    by_start = {round(e.start_beat, 4): round(e.duration_beats, 4) for e in lower}
    for beat in (0.5, 1.5, 2.5, 4.5, 5.5, 6.5):
        assert by_start[beat] == 1.0
    assert by_start[3.5] == 0.5
    assert by_start[7.5] == 0.5


def test_regular_short_phrases_fill_from_metrical_evidence():
    four = [_ev(76, float(i), 0.20, f"s{i}") for i in range(4)]
    five = [_ev(76, float(i), 0.20, f"s{i}") for i in range(5)]
    chords = []
    for i in range(4):
        for pitch in (60, 64, 67):
            chords.append(_ev(pitch, float(i), 0.20, f"{pitch}-{i}"))
    for events in (four, five, chords):
        readable, _, _ = _quantize(events, READABLE)
        literal, _, _ = _quantize(events, LITERAL)
        assert all(round(e.duration_beats, 4) == 1.0 for e in readable)
        assert all(e.articulation == "staccato" for e in readable)
        assert all(e.articulation_source == "inferred" for e in readable)
        assert all(e.duration_beats <= 0.25 + 1e-9 for e in literal)


def test_strongly_detached_chords_become_quarter_chords():
    events = []
    for i in range(8):
        for pitch in (60, 64, 67):
            events.append(_ev(pitch, float(i), 0.20, f"{pitch}-{i}"))
    readable, _, _ = _quantize(events, READABLE)
    by_onset = {}
    for ev in readable:
        by_onset.setdefault(round(ev.start_beat, 4), set()).add(round(ev.duration_beats, 4))
    assert sorted(by_onset) == [float(i) for i in range(8)]
    assert all(durs == {1.0} for durs in by_onset.values())
    assert len(readable) == 24
    assert all(e.articulation == "staccato" for e in readable)


def test_bass_chord_accompaniment_fills_to_the_pulse_not_the_next_bass():
    events = []
    for i in range(8):
        if i % 3 == 0:
            events.append(_ev(38, float(i), 0.22, f"bass-{i}", hand=Hand.LEFT))
            events.append(_ev(50, float(i), 0.22, f"bass8-{i}", hand=Hand.LEFT))
        else:
            events.append(_ev(54, float(i), 0.18, f"d-{i}"))
            events.append(_ev(57, float(i), 0.20, f"f-{i}"))
    readable, _, _ = _quantize(events, READABLE)
    assert all(round(e.duration_beats, 4) == 1.0 for e in readable)
    bass = [e for e in readable if e.note_id.startswith("bass-")]
    assert bass and all(round(e.duration_beats, 4) == 1.0 for e in bass)


def test_meaningful_pause_inside_detached_phrase_stays_a_rest():
    beats = [0, 1, 2, 3, 5, 6, 7, 8]
    events = [_ev(72 + i, float(beat), 0.20, f"n{i}") for i, beat in enumerate(beats)]
    readable, _, _ = _quantize(events, READABLE)
    by_id = {e.note_id: e for e in readable}
    assert [round(by_id[f"n{i}"].start_beat, 4) for i in range(8)] == [float(b) for b in beats]
    assert all(round(e.duration_beats, 4) == 1.0 for e in readable)
    assert by_id["n3"].start_beat + by_id["n3"].duration_beats <= 4.0 + 1e-9
    assert by_id["n4"].start_beat == 5.0


def test_phrase_ending_fills_to_the_pulse_not_the_bar():
    beats = [0, 1, 2, 3, 4, 5, 6, 8]
    events = [_ev(72 + i, float(beat), 0.20, f"n{i}") for i, beat in enumerate(beats)]
    readable, _, _ = _quantize(events, READABLE)
    by_id = {e.note_id: e for e in readable}
    assert round(by_id["n7"].duration_beats, 4) == 1.0
    assert by_id["n7"].start_beat == 8.0


def test_hold_under_strongly_detached_accompaniment_stays_independent():
    moving = [_ev(72, float(i), 0.20, f"c-{i}") for i in range(8)]
    moving += [_ev(76, float(i), 0.20, f"e-{i}") for i in range(8)]
    events = [_ev(67, 0.0, 8.0, "inner"), *moving]
    out, _, _ = _quantize(events, READABLE)
    held = next(e for e in out if e.note_id == "inner")
    chords = [e for e in out if e.note_id != "inner"]
    assert round(held.duration_beats, 4) >= 7.9
    assert all(round(e.duration_beats, 4) == 1.0 for e in chords)
    assert all(e.voice != held.voice for e in chords)
    assert not held.articulation


def test_locked_timing_and_literal_measure_are_not_filled():
    events = [_ev(72 + i, float(i), 0.20, f"n{i}") for i in range(8)]
    events[2] = _ev(74, 2.0, 0.20, "n2", score_timing_locked=True)
    mixed, _, _ = _quantize(
        events,
        NotationSettings.from_dict(
            {
                "interpretation": "readable",
                "measure_overrides": [
                    {"start_measure": 1, "end_measure": 1, "interpretation": "literal"}
                ],
            }
        ),
    )
    by_id = {e.note_id: e for e in mixed}
    for ident in ("n0", "n1", "n2", "n3"):
        assert by_id[ident].duration_beats <= 0.25 + 1e-9
    for ident in ("n4", "n5", "n6", "n7"):
        assert round(by_id[ident].duration_beats, 4) == 1.0
    locked, _, _ = _quantize(events, READABLE)
    locked_by = {e.note_id: e for e in locked}
    assert abs(locked_by["n2"].duration_beats - 0.20) < 1e-9
    assert locked_by["n2"].start_beat == 2.0
    assert round(locked_by["n0"].duration_beats, 4) == 1.0
    assert locked_by["n0"].start_beat + locked_by["n0"].duration_beats <= 2.0 + 1e-9


def test_isolated_short_in_mixed_phrase_stays_a_rest():
    events = [
        _ev(72, 0.0, 0.82, "a"),
        _ev(74, 1.0, 0.82, "b"),
        _ev(76, 2.0, 0.18, "c"),
        _ev(77, 3.0, 0.82, "d"),
    ]
    readable, _, _ = _quantize(events, READABLE)
    by_id = {e.note_id: e for e in readable}
    assert round(by_id["a"].duration_beats, 4) == 1.0
    assert round(by_id["b"].duration_beats, 4) == 1.0
    assert by_id["c"].duration_beats <= 0.25 + 1e-9
    assert not by_id["c"].articulation
    assert round(by_id["d"].duration_beats, 4) == 1.0


def test_supplied_articulation_is_not_overwritten():
    events = [
        _ev(72 + i, float(i), 0.20, f"n{i}", articulation="tenuto") for i in range(8)
    ]
    readable, dec, _ = _quantize(events, READABLE)
    assert all(round(e.duration_beats, 4) == 1.0 for e in readable)
    assert all(e.articulation == "tenuto" for e in readable)
    assert all(e.articulation_source == "supplied" for e in readable)
    assert {row.get("articulation") for row in dec} == {"tenuto"}


def test_midi_fixtures_match_the_readable_convention(tmp_path):
    source = tmp_path / "det.mid"
    READABLE_V2_CASES["strongly_detached_quarters"](source)
    original = source.read_bytes()
    readable, _, _ = _from_midi(source, READABLE)
    literal, _, _ = _from_midi(source, LITERAL)
    assert source.read_bytes() == original
    assert [round(e.duration_beats, 4) for e in readable] == [1.0] * 8
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in literal)

    chords = tmp_path / "chords.mid"
    READABLE_V2_CASES["strongly_detached_chords"](chords)
    original = chords.read_bytes()
    out, _, _ = _from_midi(chords, READABLE)
    assert chords.read_bytes() == original
    assert all(round(e.duration_beats, 4) == 1.0 for e in out)

    shorts = tmp_path / "B.mid"
    READABLE_V2_CASES["B_short_notes_with_rests"](shorts)
    out, _, _ = _from_midi(shorts, READABLE)
    assert all(round(e.duration_beats, 4) == 1.0 for e in out)
    assert all(e.articulation == "staccato" for e in out)

    offbeat = tmp_path / "offbeat.mid"
    READABLE_V2_CASES["detached_melody_with_offbeat_accompaniment"](offbeat)
    original = offbeat.read_bytes()
    out, _, ingested = _from_midi(offbeat, READABLE)
    assert offbeat.read_bytes() == original
    melody = [e for e in out if e.pitch >= 72]
    assert [round(e.duration_beats, 4) for e in melody] == [1.0] * 8

    same_staff = tmp_path / "same_staff.mid"
    READABLE_V2_CASES["detached_same_staff_independent_voices"](same_staff)
    original = same_staff.read_bytes()
    out, _, _ = _from_midi(same_staff, READABLE)
    assert same_staff.read_bytes() == original
    melody = [e for e in out if e.pitch >= 76]
    assert [round(e.duration_beats, 4) for e in melody] == [1.0] * 8


def test_staccato_score_playback_stays_detached_not_legato(tmp_path):
    events = _melody_quarters()
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(0, name="Piano")
    for ev in events:
        inst.notes.append(
            pretty_midi.Note(
                velocity=80,
                pitch=ev.pitch,
                start=ev.start_beat * 0.5,
                end=(ev.start_beat + ev.duration_beats) * 0.5,
            )
        )
    midi.instruments.append(inst)
    path = tmp_path / "det.mid"
    midi.write(str(path))
    original = path.read_bytes()
    ingested = ingest_midi(path)
    result = recompute_notation(
        midi_bytes=original,
        settings=READABLE,
        performance=ingested.performance,
        context=_context_for(ingested),
    )
    assert path.read_bytes() == original
    written = [round(float(n["duration"]), 4) for n in result.editor_model["notes"]]
    assert written == [1.0] * 8
    assert all(n.get("articulation") == "staccato" for n in result.editor_model["notes"])
    assert all(n.get("articulation_source") == "inferred" for n in result.editor_model["notes"])
    score = pretty_midi.PrettyMIDI(BytesIO(result.score_midi))
    played = sorted(n.end - n.start for inst in score.instruments for n in inst.notes)
    assert played
    assert all(dur <= 0.30 + 1e-3 for dur in played)
    assert all(dur >= 0.10 for dur in played)
    xml_durs = _xml_note_durations(result.musicxml)
    assert xml_durs
    assert all(abs(dur - 1.0) < 1e-6 for dur in xml_durs)
    marks = musicxml_note_marks(result.musicxml)
    assert all("staccato" in row["articulations"] for row in marks)
    shape = inspect_xml(result.musicxml)
    assert shape["marked_notes"] == 8


def test_clearing_inferred_staccato_survives_regeneration(tmp_path):
    events = _melody_quarters()
    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    inst = pretty_midi.Instrument(0, name="Piano")
    for ev in events:
        inst.notes.append(
            pretty_midi.Note(
                velocity=80,
                pitch=ev.pitch,
                start=ev.start_beat * 0.5,
                end=(ev.start_beat + ev.duration_beats) * 0.5,
            )
        )
    midi.instruments.append(inst)
    path = tmp_path / "det.mid"
    midi.write(str(path))
    original = path.read_bytes()
    ingested = ingest_midi(path)
    context = _context_for(ingested)
    first = recompute_notation(
        midi_bytes=original,
        settings=READABLE,
        performance=ingested.performance,
        context=context,
    )
    sid = first.editor_model["notes"][0]["source_note_id"]
    assert first.editor_model["notes"][0]["articulation"] == "staccato"
    cleared = recompute_notation(
        midi_bytes=original,
        settings=READABLE,
        performance=ingested.performance,
        context=context,
        corrections=[{"source_note_id": sid, "articulation": None}],
    )
    row = next(
        note
        for note in cleared.editor_model["notes"]
        if note.get("source_note_id") == sid
    )
    assert not row.get("articulation")
    assert row.get("articulation_source") == "user_edit"
    cleared_marks = musicxml_note_marks(cleared.musicxml)
    assert any(not row["articulations"] for row in cleared_marks)
    assert any("staccato" in row["articulations"] for row in cleared_marks)
    again = recompute_notation(
        midi_bytes=original,
        settings=READABLE,
        performance=ingested.performance,
        context=context,
        corrections=[{"source_note_id": sid, "articulation": None}],
    )
    row2 = next(
        note
        for note in again.editor_model["notes"]
        if note.get("source_note_id") == sid
    )
    assert not row2.get("articulation")
    assert path.read_bytes() == original
    others = [
        note for note in again.editor_model["notes"] if note.get("source_note_id") != sid
    ]
    assert all(note.get("articulation") == "staccato" for note in others)


def test_playback_duration_helper_halves_staccato_only():
    plain = _ev(72, 0.0, 1.0, "q")
    marked = _ev(72, 0.0, 1.0, "s", articulation="staccato")
    assert STACCATO_PLAYBACK_FRACTION == 0.5
    assert playback_duration_beats(plain) == 1.0
    assert abs(playback_duration_beats(marked) - 0.5) < 1e-9


def test_case3_development_midi_fills_under_fixed_four_four():
    """Development material, not musician-validated. Meter stays the supplied 4/4."""
    if not CASE3.is_file():
        return
    original = CASE3.read_bytes()
    ingested = ingest_midi(CASE3)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    readable, _, _ = _quantize(events, READABLE, meter=METER)
    literal, _, _ = _quantize(events, LITERAL, meter=METER)
    assert CASE3.read_bytes() == original
    assert len(readable) == 24
    assert all(round(e.duration_beats, 4) == 1.0 for e in readable)
    assert all(e.duration_beats <= 0.30 + 1e-9 for e in literal)
    assert len({e.note_id for e in readable}) == 24
