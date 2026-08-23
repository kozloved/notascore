"""Before/after MIDICleaner fixture tests."""

from benchmark.fixtures import (
    ALL_CLEANER_FIXTURES,
    FIXTURE_CHORD_MISALIGNED,
    notes_from_dicts,
)
from benchmark.metrics import match_notes
from benchmark.readability import readability_report
from mir.midi_cleaner import MIDICleaner


def test_chord_fixture_aligns_starts():
    raw = notes_from_dicts(FIXTURE_CHORD_MISALIGNED["raw"])
    cleaned = MIDICleaner().clean(raw)
    starts = {n.start_time for n in cleaned}
    assert len(starts) == 1
    assert min(starts) == 0.5


def test_all_fixtures_match_expected():
    cleaner = MIDICleaner()
    for fixture in ALL_CLEANER_FIXTURES:
        cleaned = cleaner.clean(notes_from_dicts(fixture["raw"]))
        expected = notes_from_dicts(fixture["expected_after"])
        metrics = match_notes(cleaned, expected, onset_tolerance_sec=0.02)
        assert metrics.f1 >= 0.99, f"{fixture['name']} F1={metrics.f1}"


def test_readability_improves_or_holds():
    cleaner = MIDICleaner()
    for fixture in ALL_CLEANER_FIXTURES:
        raw = notes_from_dicts(fixture["raw"])
        cleaned = cleaner.clean(raw)
        before = readability_report(raw)
        after = readability_report(cleaned)
        assert after.score >= before.score - 1e-9, fixture["name"]
        assert after.micro_note_count <= before.micro_note_count
        assert after.duplicate_near_onset_count <= before.duplicate_near_onset_count
