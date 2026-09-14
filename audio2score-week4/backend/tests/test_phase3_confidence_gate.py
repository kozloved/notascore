"""Phase 3: gated low-confidence note drop for spurious transcription FPs."""

from evaluation.matching import match_notes
from mir.confidence_gate import apply_optional_filter, drop_low_confidence_notes
from mir.types import NoteEvent


def _note(pitch, confidence, start=0.0, *, source="calibrated", model_score=None):
    return NoteEvent(
        pitch=pitch,
        start_time=start,
        end_time=start + 0.25,
        velocity=80,
        confidence=confidence,
        model_score=model_score,
        confidence_source=source,
        note_id=f"n{pitch:04d}",
    )


def test_confidence_gate_off_by_default_keeps_spurious_notes():
    notes = [_note(60, 0.9), _note(72, 0.1)]
    kept = drop_low_confidence_notes(notes, enabled=False, threshold=0.45)
    assert len(kept) == 2


def test_confidence_gate_drops_low_calibrated_confidence_when_enabled():
    notes = [_note(60, 0.9), _note(72, 0.1), _note(64, 0.45)]
    kept = drop_low_confidence_notes(notes, enabled=True, threshold=0.45)
    assert [n.pitch for n in kept] == [60, 64]


def test_confidence_gate_reduces_false_positives_against_reference():
    reference = [_note(60, 1.0, 0.0), _note(64, 1.0, 0.5)]
    predicted = [
        _note(60, 0.9, 0.0),
        _note(64, 0.8, 0.5),
        _note(72, 0.1, 0.1),  # spurious overtone
        _note(48, 0.05, 0.2),  # spurious rumble
    ]
    before = match_notes(predicted, reference, onset_tolerance_sec=0.05)
    after_notes = drop_low_confidence_notes(predicted, enabled=True, threshold=0.45)
    after = match_notes(after_notes, reference, onset_tolerance_sec=0.05)
    assert after.false_positives < before.false_positives
    assert after.false_negatives == before.false_negatives
    assert after.false_positives == 0


def test_quiet_amplitude_notes_are_not_dropped():
    notes = [
        _note(60, 0.9, source="amplitude", model_score=0.9),
        _note(48, 0.1, source="amplitude", model_score=0.1),
    ]
    kept, report = apply_optional_filter(notes, enabled=True, threshold=0.45)
    assert [n.pitch for n in kept] == [60, 48]
    assert report.removals == []


def test_mt3_default_confidence_is_not_treated_as_calibrated():
    notes = [_note(60, 1.0, source="default")]
    kept, report = apply_optional_filter(notes, enabled=True, threshold=0.45)
    assert len(kept) == 1
    assert report.removals == []


def test_filter_records_source_id_criterion_score_and_threshold():
    notes = [_note(72, 0.1, source="calibrated")]
    kept, report = apply_optional_filter(notes, enabled=True, threshold=0.45)
    assert kept == []
    assert len(report.removals) == 1
    row = report.removals[0]
    assert row.note_id == "n0072"
    assert row.criterion == "calibrated_confidence"
    assert row.score == 0.1
    assert row.threshold == 0.45
    assert row.confidence_source == "calibrated"
