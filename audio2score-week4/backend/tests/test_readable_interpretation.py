"""Paired Readable vs Literal interpretation: written intent, not finger release."""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pretty_midi

from evaluation.notation_fixtures import FIXTURES
from evaluation.literal_vs_readable_render import PAIRS
from evaluation.readable_v2_cases import EXPECTED_NOTATION, READABLE_V2_CASES
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.models import MeterHypothesis
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings
from mir.performance_score import quantize_notation
from mir.quantizer import QuantizerConfig
from mir.types import Hand, MusicalEvent
from tests.test_shared_engraving import _context_for

METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
METER_34 = MeterHypothesis("3/4", 3, 4, 3.0, 1.0, 1.0)
METER_68 = MeterHypothesis("6/8", 6, 8, 3.0, 1.5, 1.0)
READABLE = NotationSettings()
LITERAL = NotationSettings.literal()
LEGACY = NotationSettings.legacy_readable()
CONFIG = QuantizerConfig()


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


def test_literal_vs_readable_pairs_have_independent_expected_notation():
    ids = {row["id"] for row in PAIRS}
    assert "A_detached_regular_line" in ids
    assert "B_short_notes_with_rests" in ids
    assert "humanized_ceg_chord" in ids
    assert "rapid_sixteenth_run" in ids
    for row in PAIRS:
        expected = row["expected"]
        assert expected["onset"]
        assert expected["release"]
        assert expected["engraving"]
        if row["id"] in EXPECTED_NOTATION:
            assert expected["engraving"]


def test_early_release_fills_to_conventional_duration_in_readable_not_literal():
    events = [_ev(72, 0.0, 3.85, "whole")]
    readable, _, _ = _quantize(events, READABLE)
    literal, _, _ = _quantize(events, LITERAL)
    assert round(readable[0].duration_beats, 4) == 4.0
    assert literal[0].duration_beats < 4.0
    assert abs(literal[0].duration_beats - 3.85) < 0.1


def test_unlocked_one_point_seventy_five_becomes_half_note():
    events = [_ev(72, 0.0, 1.75, "n")]
    readable, _, _ = _quantize(events, READABLE)
    assert round(readable[0].duration_beats, 4) == 2.0
    locked = [_ev(72, 0.0, 1.75, "n", score_timing_locked=True)]
    out, _, _ = _quantize(locked, READABLE)
    assert abs(out[0].duration_beats - 1.75) < 1e-9


def test_intentional_short_notes_keep_rests_in_readable():
    events = [_ev(76, i * 1.0, 0.20, f"s{i}") for i in range(4)]
    readable, _, _ = _quantize(events, READABLE)
    literal, _, _ = _quantize(events, LITERAL)
    assert [round(e.duration_beats, 4) for e in readable] == [
        round(e.duration_beats, 4) for e in literal
    ]
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in readable)


def test_detached_quarter_line_fills_in_readable(tmp_path):
    source = tmp_path / "A.mid"
    READABLE_V2_CASES["A_detached_regular_line"](source)
    original = source.read_bytes()
    ingested = ingest_midi(source)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    readable, _, _ = _quantize(events, READABLE)
    literal, _, _ = _quantize(events, LITERAL)
    assert source.read_bytes() == original
    assert [round(e.duration_beats, 4) for e in readable] == [1.0] * 8
    assert all(e.duration_beats < 0.95 for e in literal)


def test_uneven_chord_releases_unify_in_readable():
    events = [
        _ev(60, 0.00, 1.82, "c"),
        _ev(64, 0.03, 1.94, "e"),
        _ev(67, 0.04, 2.01, "g"),
    ]
    readable, dec, _ = _quantize(events, READABLE)
    starts = {round(e.start_beat, 4) for e in readable}
    durs = {round(e.duration_beats, 4) for e in readable}
    assert len(starts) == 1
    assert durs == {2.0}
    reasons = {row.get("reason") for row in dec}
    assert reasons & {"readable_chord_coincidence", "readable_chord_duration", "readable_shared_beat"}


def test_independent_held_voice_is_not_stretched_to_melody():
    events = [
        MusicalEvent(64, 0.0, 4.0, note_id="inner", velocity=80, source_backend="midi"),
        MusicalEvent(76, 0.0, 0.84, note_id="m0", velocity=80, source_backend="midi"),
        MusicalEvent(77, 1.0, 0.84, note_id="m1", velocity=80, source_backend="midi"),
        MusicalEvent(79, 2.0, 0.84, note_id="m2", velocity=80, source_backend="midi"),
        MusicalEvent(81, 3.0, 0.84, note_id="m3", velocity=80, source_backend="midi"),
    ]
    out, _, _ = _quantize(events, READABLE)
    held = next(e for e in out if e.note_id == "inner")
    moving = [e for e in out if e.note_id != "inner"]
    assert round(held.duration_beats, 4) >= 3.9
    assert all(e.duration_beats <= 1.0 + 1e-9 for e in moving)
    assert all(e.musical_voice != held.musical_voice for e in moving)


def test_humanized_chord_vs_deliberate_rapid_run():
    chord = [
        _ev(60, 0.00, 1.90, "c"),
        _ev(64, 0.04, 1.85, "e"),
        _ev(67, 0.05, 1.88, "g"),
    ]
    readable, _, _ = _quantize(chord, READABLE)
    assert len({round(e.start_beat, 4) for e in readable}) == 1
    assert {round(e.duration_beats, 4) for e in readable} == {2.0}

    run = [
        _ev(60, 0.0, 0.0625, "c"),
        _ev(64, 0.0625, 0.0625, "e"),
        _ev(67, 0.125, 0.0625, "g"),
    ]
    out, _, _ = _quantize(run, READABLE)
    starts = [round(e.start_beat, 6) for e in sorted(out, key=lambda e: e.start_beat)]
    assert starts == [0.0, 0.0625, 0.125]
    assert all(e.duration_beats <= 0.125 + 1e-9 for e in out)


def test_locked_timing_survives_readable_chord_unify():
    events = [
        _ev(60, 0.00, 1.82, "c"),
        _ev(64, 0.03, 1.94, "e", score_timing_locked=True),
        _ev(67, 0.04, 2.01, "g"),
    ]
    out, _, _ = _quantize(events, READABLE)
    by_id = {e.note_id: e for e in out}
    assert abs(by_id["e"].duration_beats - 1.94) < 1e-9
    assert abs(by_id["e"].start_beat - 0.03) < 1e-9


def test_repeated_quarter_pattern_stays_consistent():
    events = [_ev(72 + (i % 3), float(i), 0.84, f"n{i}") for i in range(8)]
    out, _, _ = _quantize(events, READABLE)
    assert [round(e.start_beat, 4) for e in out] == [float(i) for i in range(8)]
    assert [round(e.duration_beats, 4) for e in out] == [1.0] * 8


def test_compound_and_triple_meters_fill_conventional_slots():
    waltz = [_ev(72, i * 1.0, 0.88, f"w{i}") for i in range(3)]
    out, _, _ = _quantize(waltz, READABLE, meter=METER_34)
    assert [round(e.duration_beats, 4) for e in out] == [1.0] * 3

    compound = [
        _ev(72, 0.0, 0.42, "a"),
        _ev(74, 0.5, 0.42, "b"),
        _ev(76, 1.0, 0.42, "c"),
        _ev(77, 1.5, 0.42, "d"),
        _ev(79, 2.0, 0.42, "e"),
        _ev(81, 2.5, 0.42, "f"),
    ]
    out68, _, _ = _quantize(compound, READABLE, meter=METER_68)
    assert [round(e.start_beat, 4) for e in out68] == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]
    assert all(abs(e.duration_beats - 0.5) < 0.05 for e in out68)


def test_syncopation_and_tuplets_are_not_flattened():
    events = [
        _ev(72, 0.25, 0.5, "a"),
        _ev(74, 0.75, 0.5, "b"),
        _ev(76, 1.25, 0.5, "c"),
        _ev(77, 1.75, 0.75, "d"),
        _ev(79, 2.5, 1.5, "e"),
    ]
    out, _, _ = _quantize(events, READABLE)
    by_id = {e.note_id: e for e in out}
    assert abs(by_id["a"].start_beat - 0.25) < 1e-9
    assert abs(by_id["b"].start_beat - 0.75) < 1e-9
    assert by_id["a"].start_beat != 0.0

    triplets = [
        _ev(72, i / 3, 0.28, f"t{i}") for i in range(3)
    ]
    tout, tdec, _ = _quantize(triplets, READABLE)
    starts = [round(e.start_beat, 4) for e in tout]
    assert starts == [round(i / 3, 4) for i in range(3)]
    assert {row["rhythm_family"] for row in tdec} <= {"triplet", "binary"}


def test_cross_bar_sustain_and_pickup_survive(tmp_path):
    source = tmp_path / "sync.mid"
    FIXTURES["syncopation"](source)
    original = source.read_bytes()
    ingested = ingest_midi(source)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    out, _, _ = _quantize(events, READABLE)
    assert source.read_bytes() == original
    assert max(e.start_beat + e.duration_beats for e in out) > 4.0

    pickup = tmp_path / "pickup.mid"
    FIXTURES["rubato_pickup"](pickup)
    original = pickup.read_bytes()
    ingested = ingest_midi(pickup)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    _quantize(events, READABLE)
    assert pickup.read_bytes() == original


def test_mode_switch_regenerates_and_preserves_edits(tmp_path):
    path = tmp_path / "mode.mid"
    READABLE_V2_CASES["A_detached_regular_line"](path)
    original = path.read_bytes()
    ingested = ingest_midi(path)
    context = _context_for(ingested)
    readable = recompute_notation(
        midi_bytes=original,
        settings=READABLE,
        performance=ingested.performance,
        context=context,
    )
    literal = recompute_notation(
        midi_bytes=original,
        settings=LITERAL,
        performance=ingested.performance,
        context=context,
    )
    assert path.read_bytes() == original
    assert readable.midi_sha256 == hashlib.sha256(original).hexdigest()
    assert readable.cache_key != literal.cache_key
    sid = readable.editor_model["notes"][0].get("source_note_id") or readable.editor_model["notes"][0]["id"]
    edited = recompute_notation(
        midi_bytes=original,
        settings=READABLE,
        performance=ingested.performance,
        context=context,
        corrections=[{"source_note_id": sid, "velocity": 108}],
    )
    assert path.read_bytes() == original
    row = next(
        note
        for note in edited.editor_model["notes"]
        if (note.get("source_note_id") or note["id"]) == sid
    )
    assert int(row["velocity"]) == 108
    locked = recompute_notation(
        midi_bytes=original,
        settings=READABLE,
        performance=ingested.performance,
        context=context,
        corrections=[{"source_note_id": sid, "start": 0.0, "duration": 1.75}],
    )
    locked_row = next(
        note
        for note in locked.editor_model["notes"]
        if (note.get("source_note_id") or note["id"]) == sid
    )
    assert abs(float(locked_row["duration"]) - 1.75) < 1e-6


def test_score_playback_matches_readable_written_durations(tmp_path):
    events = [
        _ev(60, 0.00, 1.82, "c"),
        _ev(64, 0.03, 1.94, "e"),
        _ev(67, 0.04, 2.01, "g"),
    ]
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
    path = tmp_path / "chord.mid"
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
    written = {round(float(n["duration"]), 4) for n in result.editor_model["notes"]}
    assert written == {2.0}
    score = pretty_midi.PrettyMIDI(BytesIO(result.score_midi))
    played = sorted((round(n.end - n.start, 3), n.pitch) for n in score.instruments[0].notes)
    assert played
    assert all(abs(dur - 1.0) < 0.05 for dur, _pitch in played)


def test_midi_humanized_chord_vs_rapid_run_through_ingest(tmp_path):
    chord_path = tmp_path / "humanized.mid"
    READABLE_V2_CASES["humanized_ceg_chord"](chord_path)
    original = chord_path.read_bytes()
    ingested = ingest_midi(chord_path)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    readable, _, _ = _quantize(events, READABLE)
    literal, _, _ = _quantize(events, LITERAL)
    assert chord_path.read_bytes() == original
    assert len({round(e.start_beat, 4) for e in readable}) == 1
    assert {round(e.duration_beats, 4) for e in readable} == {2.0}
    assert max(e.start_beat for e in literal) > 0.0 or min(
        e.duration_beats for e in literal
    ) < 2.0 - 1e-6

    run_path = tmp_path / "run.mid"
    READABLE_V2_CASES["rapid_sixteenth_run"](run_path)
    original = run_path.read_bytes()
    ingested = ingest_midi(run_path)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    out, _, _ = _quantize(events, READABLE)
    assert run_path.read_bytes() == original
    starts = [round(e.start_beat, 6) for e in sorted(out, key=lambda e: e.start_beat)]
    assert starts == [0.0, 0.0625, 0.125]
    assert all(e.duration_beats <= 0.125 + 1e-9 for e in out)


def test_midi_early_release_and_uneven_chord_through_ingest(tmp_path):
    whole = tmp_path / "whole.mid"
    READABLE_V2_CASES["early_release_whole"](whole)
    original = whole.read_bytes()
    ingested = ingest_midi(whole)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    readable, _, _ = _quantize(events, READABLE)
    literal, _, _ = _quantize(events, LITERAL)
    assert whole.read_bytes() == original
    assert round(readable[0].duration_beats, 4) == 4.0
    assert literal[0].duration_beats < 4.0

    chord = tmp_path / "uneven.mid"
    READABLE_V2_CASES["uneven_chord_releases"](chord)
    original = chord.read_bytes()
    ingested = ingest_midi(chord)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    readable, _, _ = _quantize(events, READABLE)
    assert chord.read_bytes() == original
    assert len({round(e.start_beat, 4) for e in readable}) == 1
    assert {round(e.duration_beats, 4) for e in readable} == {2.0}


def test_legacy_saved_readable_does_not_fill_detached_quarters():
    events = [_ev(72, float(i), 0.84, f"n{i}") for i in range(4)]
    legacy, _, _ = _quantize(events, LEGACY)
    current, _, _ = _quantize(events, READABLE)
    assert all(e.duration_beats < 0.95 for e in legacy)
    assert [round(e.duration_beats, 4) for e in current] == [1.0] * 4
