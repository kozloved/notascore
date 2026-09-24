"""Opt-in readable-v2 vs default on short notes and small release gaps."""

from __future__ import annotations

from pathlib import Path

from evaluation.notation_fixtures import FIXTURES
from evaluation.readable_v2_cases import HELDOUT_CASES, READABLE_V2_CASES
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi, tagged_pedal_events
from mir.models import MeterHypothesis
from mir.notation_settings import NotationSettings
from mir.performance_score import quantize_notation
from mir.quantizer import QuantizerConfig

METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
V1 = NotationSettings.from_dict(
    {"interpretation": "readable", "algorithm_version": "performance-score-1"}
)
V2 = NotationSettings.from_dict(
    {"interpretation": "readable", "algorithm_version": "performance-score-2"}
)


def _quantize(path: Path, settings: NotationSettings):
    ingested = ingest_midi(path)
    events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
    pedal = tagged_pedal_events(ingested.performance) or ingested.pedal_events
    out, decisions, _report = quantize_notation(
        events,
        METER,
        config=QuantizerConfig(),
        settings=settings,
        pedal_events=pedal,
    )
    return out, decisions, ingested


def test_paired_detached_vs_short_rest_fill_uses_relative_gap():
    from fractions import Fraction

    from mir.performance_score import _readable_v2_fill_small_release_gap

    kwargs = dict(release_reason="performed_release", settings=V2)
    # Case A: detached quarters. ~80ms leftover on a beat is articulation.
    assert _readable_v2_fill_small_release_gap(0.84, 0, 1.0, 4, **kwargs) == 1
    # Deliberate sixteenth + rest. Leftover 0.05 of a 0.25 slot is 20% — keep rest.
    assert _readable_v2_fill_small_release_gap(0.20, 0, 0.25, 4, **kwargs) is None
    # A leftover equal to a sixteenth is already a rest.
    assert _readable_v2_fill_small_release_gap(0.75, 0, 1.0, 4, **kwargs) is None
    # Remaining as large as the sounding note is not detached playing.
    assert _readable_v2_fill_small_release_gap(0.10, 0, 0.20, 4, **kwargs) is None
    # v1 never fills the detached line.
    assert _readable_v2_fill_small_release_gap(
        0.84, 0, 1.0, 4, release_reason="performed_release", settings=V1
    ) is None
    # Triplet group-end still uses the local pulse, not this relative test.
    assert _readable_v2_fill_small_release_gap(
        0.28, Fraction(17, 3), None, Fraction(7, 3), local_pulse=Fraction(1, 3), **kwargs
    ) == Fraction(1, 3)


def test_short_rests_repeats_keep_v1_durations_on_v2(tmp_path):
    source = tmp_path / "short_rests.mid"
    FIXTURES["short_rests_repeats"](source)
    original = source.read_bytes()
    v1, _dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert [round(e.start_beat, 4) for e in v1] == [round(e.start_beat, 4) for e in v2]
    assert [round(e.duration_beats, 4) for e in v1] == [round(e.duration_beats, 4) for e in v2]
    assert any(e.duration_beats <= 0.25 + 1e-9 for e in v2)


def test_irregular_triplet_intervals_preserve_rests(tmp_path):
    source = tmp_path / "irregular.mid"
    HELDOUT_CASES["irregular_triplet_intervals"](source)
    original = source.read_bytes()
    v1, _dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert [round(e.duration_beats, 4) for e in v1] == [round(e.duration_beats, 4) for e in v2]
    assert all(abs(float(e.duration_beats) - (1 / 3)) > 1e-3 for e in v2)


def test_v2_group_end_uses_triplet_pulse_not_the_beat():
    from fractions import Fraction

    from mir.performance_score import _readable_v2_fill_small_release_gap

    kwargs = dict(release_reason="phrase_end", settings=V2)
    # Last mixed-triplet note: raw ~0.28, pulse 1/3, leftover < sixteenth.
    assert _readable_v2_fill_small_release_gap(
        0.28, Fraction(17, 3), None, Fraction(7, 3), local_pulse=Fraction(1, 3), **kwargs
    ) == Fraction(1, 3)
    # Intentional short note: leftover to the pulse is a full sixteenth.
    assert _readable_v2_fill_small_release_gap(
        0.08, Fraction(2, 3), None, Fraction(10, 3), local_pulse=Fraction(1, 3), **kwargs
    ) is None
    # Do not fill past a closer next attack.
    assert _readable_v2_fill_small_release_gap(
        0.28, Fraction(0), Fraction(1, 6), Fraction(4), local_pulse=Fraction(1, 3), **kwargs
    ) is None
    # v1 never fills, even with a coherent pulse.
    assert _readable_v2_fill_small_release_gap(
        0.28, Fraction(17, 3), None, Fraction(7, 3),
        release_reason="phrase_end", settings=V1, local_pulse=Fraction(1, 3),
    ) is None


def test_detached_regular_line_becomes_quarters_only_on_v2(tmp_path):
    source = tmp_path / "A.mid"
    READABLE_V2_CASES["A_detached_regular_line"](source)
    original = source.read_bytes()
    v1, dec1, _ = _quantize(source, V1)
    v2, dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert [round(e.start_beat, 4) for e in v1] == [float(i) for i in range(8)]
    assert [round(e.start_beat, 4) for e in v2] == [float(i) for i in range(8)]
    assert [round(e.duration_beats, 4) for e in v1] == [0.75] * 8
    assert [round(e.duration_beats, 4) for e in v2] == [1.0] * 8
    assert all(not e.articulation for e in v2)
    assert [row["release_reason"] for row in dec1][0] == "performed_release"
    assert [n.pitch for n in v1] == [n.pitch for n in v2]


def test_short_notes_keep_meaningful_rests_on_both_versions(tmp_path):
    source = tmp_path / "B.mid"
    READABLE_V2_CASES["B_short_notes_with_rests"](source)
    original = source.read_bytes()
    v1, _dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert [round(e.start_beat, 4) for e in v2] == [0.0, 1.0, 2.0, 3.0]
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in v1)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in v2)
    assert [round(e.duration_beats, 4) for e in v1] == [round(e.duration_beats, 4) for e in v2]
    assert all(not e.articulation for e in v1)
    assert all(not e.articulation for e in v2)


def test_independent_sustain_is_not_clipped_by_v2(tmp_path):
    source = tmp_path / "D.mid"
    READABLE_V2_CASES["D_independent_sustain"](source)
    original = source.read_bytes()
    v1, _dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    bass1 = next(e for e in v1 if e.pitch == 48)
    bass2 = next(e for e in v2 if e.pitch == 48)
    assert round(bass1.duration_beats, 4) == 4.0
    assert round(bass2.duration_beats, 4) == 4.0
    treble2 = [e for e in v2 if e.pitch != 48]
    assert [round(e.start_beat, 4) for e in treble2] == [i * 0.5 for i in range(8)]
    assert len(v1) == len(v2) == 9


def test_repeated_attacks_under_pedal_are_four_quarters(tmp_path):
    """C: FIFO ingest plus re-attack release writes four separate quarters.

    pretty_midi still collapses the file's unisons; new ingest repairs ends
    from the original bytes. Readable mode must not tie across re-attacks.
    """
    source = tmp_path / "C.mid"
    READABLE_V2_CASES["C_repeated_attacks_under_pedal"](source)
    original = source.read_bytes()
    v1, dec1, ingested = _quantize(source, V1)
    v2, dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert ingested.performance.midi_sha256 is not None
    performed = [(round(n.start_sec, 3), round(n.end_sec - n.start_sec, 3)) for n in ingested.performance.notes]
    assert [row[0] for row in performed] == [0.0, 0.5, 1.0, 1.5]
    assert all(abs(row[1] - 0.58) < 0.03 for row in performed)
    for events, decisions in ((v1, dec1), (v2, dec2)):
        assert [round(e.start_beat, 4) for e in events] == [0.0, 1.0, 2.0, 3.0]
        assert [n.pitch for n in events] == [67, 67, 67, 67]
        assert [round(e.duration_beats, 4) for e in events] == [1.0, 1.0, 1.0, 1.0]
        assert [row["release_reason"] for row in decisions[:3]] == ["pedal_tail", "pedal_tail", "pedal_tail"]
        assert all(row.get("pedal_source") == "cc64" for row in decisions[:3])
        assert len({e.note_id for e in events}) == 4


def test_repeated_attacks_without_pedal_are_four_quarters(tmp_path):
    source = tmp_path / "E.mid"
    READABLE_V2_CASES["E_repeated_attacks_no_pedal"](source)
    original = source.read_bytes()
    v1, dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert [round(e.duration_beats, 4) for e in v1] == [1.0, 1.0, 1.0, 1.0]
    assert [round(e.duration_beats, 4) for e in v2] == [1.0, 1.0, 1.0, 1.0]
    assert all(row["pedal_source"] is None for row in dec1[:3])


def test_overlapping_unisons_keep_two_attacks(tmp_path):
    source = tmp_path / "F.mid"
    READABLE_V2_CASES["F_overlapping_unisons"](source)
    original = source.read_bytes()
    v2, dec2, ingested = _quantize(source, V2)
    assert source.read_bytes() == original
    assert len(v2) == 2
    assert len(ingested.performance.notes) == 2
    assert all(round(e.duration_beats, 4) >= 1.75 for e in v2)
    assert {row["release_reason"] for row in dec2} <= {"overlapping_repeat", "phrase_end", "no_line"}


def test_held_voice_on_same_staff_is_not_clipped(tmp_path):
    source = tmp_path / "G.mid"
    READABLE_V2_CASES["G_held_voice_same_staff"](source)
    original = source.read_bytes()
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    held = next(e for e in v2 if e.pitch == 67)
    moving = [e for e in v2 if e.pitch != 67]
    assert round(held.duration_beats, 4) == 4.0
    assert [round(e.start_beat, 4) for e in moving] == [0.0, 1.0, 2.0, 3.0]
    assert all(e.duration_beats <= 1.0 + 1e-9 for e in moving)


def test_mixed_tuplets_v1_stays_sixteenths_v2_fills_last_triplet(tmp_path):
    from evaluation.notation_fixtures import FIXTURES

    source = tmp_path / "mixed_tuplets.mid"
    FIXTURES["mixed_tuplets"](source)
    original = source.read_bytes()
    v1, dec1, _ = _quantize(source, V1)
    v2, dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    treble1 = [e for e in v1 if e.pitch >= 72]
    treble2 = [e for e in v2 if e.pitch >= 72]
    assert [round(e.start_beat, 4) for e in treble1] == [round(4 + i / 3, 4) for i in range(6)]
    assert [round(e.start_beat, 4) for e in treble2] == [round(4 + i / 3, 4) for i in range(6)]
    assert [round(e.duration_beats, 4) for e in treble1] == [0.25] * 6
    assert [round(e.duration_beats, 4) for e in treble2] == [round(1 / 3, 4)] * 6
    assert dec2[-1]["release_reason"] == "phrase_end"
    assert [round(e.duration_beats, 4) for e in v1 if e.pitch < 72] == [1.0] * 4
    assert [round(e.duration_beats, 4) for e in v2 if e.pitch < 72] == [1.0] * 4
    assert all(row["rhythm_family"] == "binary" for row in dec1 if row["raw_start"] < 4)
    assert {row["rhythm_family"] for row in dec2 if row["raw_start"] >= 4} == {"triplet"}


def test_detached_triplet_groups_fill_last_note_only_on_v2(tmp_path):
    source = tmp_path / "I.mid"
    READABLE_V2_CASES["I_detached_triplet_groups"](source)
    original = source.read_bytes()
    v1, _dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    starts = [0.0, 1 / 3, 2 / 3, 2.0, 7 / 3, 8 / 3]
    assert [round(e.start_beat, 4) for e in v2] == [round(s, 4) for s in starts]
    assert [round(e.duration_beats, 4) for e in v1] == [0.25] * 6
    assert [round(e.duration_beats, 4) for e in v2] == [round(1 / 3, 4)] * 6


def test_intentional_short_triplet_rests_keep_rests_on_both(tmp_path):
    source = tmp_path / "J.mid"
    READABLE_V2_CASES["J_intentional_short_triplet_rests"](source)
    original = source.read_bytes()
    v1, _dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert [round(e.start_beat, 4) for e in v2] == [0.0, round(1 / 3, 4), round(2 / 3, 4)]
    assert all(e.duration_beats <= 0.125 + 1e-9 for e in v1)
    assert all(e.duration_beats <= 0.125 + 1e-9 for e in v2)
    assert [round(e.duration_beats, 4) for e in v1] == [round(e.duration_beats, 4) for e in v2]


def test_repeated_triplet_pitches_last_note_matches_siblings_on_v2(tmp_path):
    source = tmp_path / "K.mid"
    READABLE_V2_CASES["K_repeated_triplet_pitches"](source)
    original = source.read_bytes()
    v1, _dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert [n.pitch for n in v2] == [72] * 6
    assert [round(e.duration_beats, 4) for e in v1] == [0.25] * 6
    assert [round(e.duration_beats, 4) for e in v2] == [round(1 / 3, 4)] * 6


def test_held_voice_under_triplets_is_not_clipped(tmp_path):
    source = tmp_path / "L.mid"
    READABLE_V2_CASES["L_held_voice_under_triplets"](source)
    original = source.read_bytes()
    v1, _dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    bass1 = next(e for e in v1 if e.pitch == 48)
    bass2 = next(e for e in v2 if e.pitch == 48)
    assert round(bass1.duration_beats, 4) >= 1.75
    assert round(bass2.duration_beats, 4) >= 1.75
    treble2 = [e for e in v2 if e.pitch != 48]
    assert [round(e.duration_beats, 4) for e in treble2] == [round(1 / 3, 4)] * 6
    assert [round(e.duration_beats, 4) for e in v1 if e.pitch != 48][-1] == 0.25


def test_foreign_track_pedal_does_not_lengthen_short_notes(tmp_path):
    source = tmp_path / "H.mid"
    READABLE_V2_CASES["H_foreign_track_pedal"](source)
    original = source.read_bytes()
    v1, dec1, ingested = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert len(tagged_pedal_events(ingested.performance)) == 2
    assert all(row[2] == "track:1" for row in tagged_pedal_events(ingested.performance))
    sounded = [e for e in v2 if e.pitch == 76]
    assert [round(e.start_beat, 4) for e in sounded] == [0.0, 1.0, 2.0, 3.0]
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in v1 if e.pitch == 76)
    assert all(e.duration_beats <= 0.25 + 1e-9 for e in v2 if e.pitch == 76)
    treble_dec = [row for row in dec1 if row.get("note_id") in {e.note_id for e in v1 if e.pitch == 76}]
    assert treble_dec
    assert all(row.get("pedal_source") is None for row in treble_dec)
    assert all(row.get("release_reason") != "pedal_tail" for row in treble_dec)
