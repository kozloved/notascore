"""Strongly detached playing becomes written pulse notes, not tiny notes plus rests.

Readable convention, not recovered certainty. Four-attack rest figures and
locked / Literal notes stay short. Score playback of inferred staccato must
not sound the full written duration.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pretty_midi

from evaluation.readable_v2_cases import READABLE_V2_CASES
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.models import MeterHypothesis
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings
from mir.performance_score import quantize_notation
from mir.quantizer import QuantizerConfig
from mir.types import Hand, MusicalEvent
from notation_engine.playback import playback_duration_beats
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


def test_strongly_detached_quarters_become_written_quarters():
    events = [_ev(72 + i, float(i), 0.20, f"n{i}") for i in range(8)]
    readable, _, _ = _quantize(events, READABLE)
    literal, _, _ = _quantize(events, LITERAL)
    v2, _, _ = _quantize(events, V2)
    legacy, _, _ = _quantize(events, LEGACY)
    assert [round(e.duration_beats, 4) for e in readable] == [1.0] * 8
    assert [round(e.start_beat, 4) for e in readable] == [float(i) for i in range(8)]
    assert {e.note_id for e in readable} == {f"n{i}" for i in range(8)}
    assert all(e.articulation == "staccato" for e in readable)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in literal)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in v2)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in legacy)
    assert all(not e.articulation for e in literal)


def test_four_short_notes_with_rests_stay_short():
    events = [_ev(76, float(i), 0.20, f"s{i}") for i in range(4)]
    readable, _, _ = _quantize(events, READABLE)
    literal, _, _ = _quantize(events, LITERAL)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in readable)
    assert [round(e.duration_beats, 4) for e in readable] == [
        round(e.duration_beats, 4) for e in literal
    ]
    assert all(not e.articulation for e in readable)


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


def test_short_four_chords_with_rests_stay_short():
    events = []
    for i in range(4):
        for pitch in (60, 64, 67):
            events.append(_ev(pitch, float(i), 0.20, f"{pitch}-{i}"))
    readable, _, _ = _quantize(events, READABLE)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in readable)
    assert all(not e.articulation for e in readable)


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
    # Last attack at beat 8 (bar 3 beat 1); leftover to the barline is 4.
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


def test_ambiguous_five_shorts_keep_the_rest_convention():
    events = [_ev(76, float(i), 0.20, f"s{i}") for i in range(5)]
    readable, _, _ = _quantize(events, READABLE)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in readable)
    assert all(not e.articulation for e in readable)


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

    rests = tmp_path / "B.mid"
    READABLE_V2_CASES["B_short_notes_with_rests"](rests)
    out, _, _ = _from_midi(rests, READABLE)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in out)


def test_staccato_score_playback_stays_detached_not_legato(tmp_path):
    events = [_ev(72 + i, float(i), 0.20, f"n{i}") for i in range(8)]
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
    score = pretty_midi.PrettyMIDI(BytesIO(result.score_midi))
    played = sorted(n.end - n.start for inst in score.instruments for n in inst.notes)
    assert played
    assert all(dur <= 0.30 + 1e-3 for dur in played)
    assert all(dur >= 0.10 for dur in played)


def test_playback_duration_helper_halves_staccato_only():
    plain = _ev(72, 0.0, 1.0, "q")
    marked = _ev(72, 0.0, 1.0, "s", articulation="staccato")
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
