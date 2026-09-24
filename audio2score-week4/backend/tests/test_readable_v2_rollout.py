"""readable-v2 stays opt-in; rollout comparison preserves MIDI and silence."""

from __future__ import annotations

from mir.notation_settings import (
    ALGORITHM_VERSION_CURRENT,
    ALGORITHM_VERSION_READABLE,
    NotationSettings,
)
from mir.performance_score import quantize_notation
from mir.quantizer import QuantizerConfig
from mir.types import Hand, MusicalEvent
from mir.models import MeterHypothesis

from evaluation.notation_fixtures import FIXTURE_META, FIXTURES
from evaluation.readable_v2_cases import HELDOUT_CASES, READABLE_V2_CASES
from evaluation.readable_v2_rollout import (
    CORPUS_FOCUS,
    TUNING_SET,
    _assignments,
    _timing_delta,
    compare_case,
    compare_staff_voice,
    inventory,
    recommend,
    run,
)


def test_default_stays_performance_score_1():
    assert NotationSettings().algorithm_version == ALGORITHM_VERSION_CURRENT
    assert NotationSettings().algorithm_version == "performance-score-1"
    opt = NotationSettings.readable_opt_in()
    assert opt.algorithm_version == ALGORITHM_VERSION_READABLE
    assert opt.algorithm_version == "performance-score-2"


def test_inventory_reports_synthetic_provenance_and_real_gap():
    inv = inventory()
    assert inv["evidence_kind"] == "synthetic_midi"
    assert inv["real_audio_evidence"] is False
    assert inv["real_material"]["licensed_performances_available"] is False
    assert inv["real_material"]["real_performances_available"] is False
    assert inv["real_material"]["gap"]
    assert "licensed" in inv["real_material"]["gap"].lower()
    samples = inv["real_material"]["nota_test_samples"]
    if samples:
        assert inv["real_material"]["local_reference_midi_available"] is True
        assert all(row["kind"] == "local_reference_midi" for row in samples)
        assert all(row["license"] == "undocumented_in_repo" for row in samples)
    assert "generated" in inv["note"].lower()
    ids = {row["id"] for row in inv["fixtures"] + inv["readable_v2_cases"] + inv["heldout_cases"] + inv["corpus"]}
    assert TUNING_SET <= ids
    assert {row["id"] for row in inv["heldout_cases"]}.isdisjoint(TUNING_SET)
    assert all(row["kind"] == "synthetic_midi" for row in inv["corpus"])
    assert all(row["held_out_of_last_note_tune"] for row in inv["heldout_cases"])
    assert all(row["held_out_of_last_note_tune"] for row in inv["corpus"])


class _Result:
    def __init__(self, notes):
        self.editor_model = {"notes": notes}


def _note(ident, *, pitch, start, duration, track, voice, source_note_id=None):
    return {
        "id": ident,
        "source_note_id": source_note_id if source_note_id is not None else ident,
        "pitch": pitch,
        "start": start,
        "duration": duration,
        "track": track,
        "voice": voice,
    }


def test_swapped_staff_and_voice_is_not_unchanged():
    left = _assignments(
        _Result(
            [
                _note("src-a", pitch=72, start=0, duration=1, track=0, voice=0),
                _note("src-b", pitch=48, start=0, duration=1, track=1, voice=1),
            ]
        )
    )
    right = _assignments(
        _Result(
            [
                _note("src-a", pitch=72, start=0, duration=1, track=1, voice=1),
                _note("src-b", pitch=48, start=0, duration=1, track=0, voice=0),
            ]
        )
    )
    compared = compare_staff_voice(left, right)
    assert compared["assignments_unchanged"] is False
    assert compared["staff_equal"] is False
    assert compared["grouping_equal"] is False
    assert {row["id"] for row in compared["staff_changes"]} == {"src-a", "src-b"}


def test_voice_label_permutation_on_one_staff_is_unchanged_grouping():
    left = _assignments(
        _Result(
            [
                _note("src-a", pitch=72, start=0, duration=1, track=0, voice=0),
                _note("src-b", pitch=74, start=1, duration=1, track=0, voice=1),
            ]
        )
    )
    right = _assignments(
        _Result(
            [
                _note("src-a", pitch=72, start=0, duration=1, track=0, voice=1),
                _note("src-b", pitch=74, start=1, duration=1, track=0, voice=0),
            ]
        )
    )
    compared = compare_staff_voice(left, right)
    assert compared["staff_equal"] is True
    assert compared["grouping_equal"] is True
    assert compared["assignments_unchanged"] is True


def test_timing_matches_stable_identity_not_array_index():
    left = _assignments(
        _Result(
            [
                _note("src-a", pitch=72, start=0, duration=1.0, track=0, voice=0),
                _note("src-b", pitch=48, start=0, duration=2.0, track=1, voice=0),
            ]
        )
    )
    reordered = _assignments(
        _Result(
            [
                _note("src-b", pitch=48, start=0, duration=2.0, track=1, voice=0),
                _note("src-a", pitch=72, start=0, duration=1.0, track=0, voice=0),
            ]
        )
    )
    swapped_durations = _assignments(
        _Result(
            [
                _note("src-a", pitch=72, start=0, duration=2.0, track=0, voice=0),
                _note("src-b", pitch=48, start=0, duration=1.0, track=1, voice=0),
            ]
        )
    )
    same = _timing_delta(left, reordered)
    assert same["durations_equal"] is True
    assert same["starts_equal"] is True
    assert same["matched_by"] == "source_note_id_or_editor_id"
    changed = _timing_delta(left, swapped_durations)
    assert changed["durations_equal"] is False
    by_id = {row["id"]: row for row in changed["duration_changes"]}
    assert by_id["src-a"] == {"id": "src-a", "pitch": 72, "v1": 1.0, "v2": 2.0}
    assert by_id["src-b"] == {"id": "src-b", "pitch": 48, "v1": 2.0, "v2": 1.0}


def test_editor_model_uses_track_not_hand(tmp_path):
    row = compare_case(
        "unison_crossing",
        FIXTURES,
        FIXTURE_META["unison_crossing"],
        "synthetic_fixture",
        True,
        tmp_path,
    )
    notes = row["v1"]["assignments"]["notes"]
    assert {note["staff"] for note in notes} == {0, 1}
    assert row["hand_voice"]["assignments_unchanged"] is True
    assert row["hand_voice"]["staff_equal"] is True


def test_heldout_final_short_preserves_midi(tmp_path):
    row = compare_case(
        "final_short_then_silence",
        HELDOUT_CASES,
        {"meter": "4/4", "tempo": 120},
        "synthetic_heldout",
        True,
        tmp_path,
    )
    assert row["source_midi_unchanged"] is True
    assert row["provenance"]["held_out_of_last_note_tune"] is True
    assert row["measure_integrity"]["equal"] is True
    assert row["measure_integrity"]["structural_similar"] is True
    assert row["measure_integrity"]["v1_musical_valid"] is True
    assert row["measure_integrity"]["v2_musical_valid"] is True
    assert row["v1"]["algorithm_version"] == "performance-score-1"
    assert row["v2"]["algorithm_version"] == "performance-score-2"
    # The last attack is the intentional short note.
    assert row["v1"]["assignments"]["pitches"][-1] == 74
    assert row["v2"]["assignments"]["pitches"][-1] == 74


def test_locked_timing_survives_both_versions():
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
    v1 = NotationSettings()
    v2 = NotationSettings.readable_opt_in()
    out1, _, _ = quantize_notation(events, meter, config=QuantizerConfig(), settings=v1)
    out2, _, _ = quantize_notation(events, meter, config=QuantizerConfig(), settings=v2)
    for out in (out1, out2):
        by_id = {ev.note_id: ev for ev in out}
        assert by_id["locked"].start_beat == 0.51
        assert by_id["locked"].duration_beats == 0.97


def test_rollout_run_writes_report_and_keeps_v2_opt_in(tmp_path):
    report = run(tmp_path / "out", render=False)
    assert report["inventory"]["default_algorithm_version"] == "performance-score-1"
    assert all(row["source_midi_unchanged"] for row in report["cases"])
    assert all(row["source_midi_unchanged"] for row in report["corpus"])
    labels = {row["label"] for row in report["cases"]}
    assert "final_short_then_silence" in labels
    assert "irregular_triplet_intervals" in labels
    assert "near_barline_short_release" in labels
    assert "independent_voices_mixed_release" in labels
    assert "long_monophonic_phrase" in labels
    assert "grand_staff_pagination" in labels
    assert "short_rests_repeats" in labels
    short = next(row for row in report["cases"] if row["label"] == "short_rests_repeats")
    irregular = next(row for row in report["cases"] if row["label"] == "irregular_triplet_intervals")
    assert short["timing"]["durations_equal"] is True
    assert irregular["timing"]["durations_equal"] is True
    assert short["measure_integrity"]["v1_musical_valid"] is True
    assert short["measure_integrity"]["v2_musical_valid"] is True
    assert {row["label"] for row in report["corpus"]} == set(CORPUS_FOCUS)
    if report["inventory"]["real_material"]["nota_test_samples"]:
        assert report["reference_midi"]
        assert all(row["source_midi_unchanged"] for row in report["reference_midi"])
        assert all(row["provenance"]["kind"] == "local_reference_midi" for row in report["reference_midi"])
    rec = recommend(report)
    assert rec["migrate_existing_jobs"] is False
    assert rec["decision"] == "continued_opt_in"
    assert report["inventory"]["real_material"]["licensed_performances_available"] is False
    assert (tmp_path / "out" / "rollout_report.md").exists()
    assert (tmp_path / "out" / "B_short_notes_with_rests" / "v1.musicxml").exists()
    assert (tmp_path / "out" / "B_short_notes_with_rests" / "v2.musicxml").exists()


def test_tuning_set_does_not_include_heldout_investigation():
    assert "final_short_then_silence" not in TUNING_SET
    assert "near_barline_short_release" not in TUNING_SET
    assert "irregular_triplet_intervals" not in TUNING_SET
    assert "mixed_families_after_bar" not in TUNING_SET
    assert "grand_staff_pagination" not in TUNING_SET
    assert "short_rests_repeats" not in TUNING_SET
    assert set(HELDOUT_CASES).isdisjoint(READABLE_V2_CASES)
    assert set(HELDOUT_CASES).isdisjoint(TUNING_SET)
