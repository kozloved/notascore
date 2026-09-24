"""Evidence runner uses ingested meter/tempo, not a 4/4 test helper."""

from evaluation.notation_correctness_evidence import context_from_ingest, inspect_xml
from evaluation.notation_fixtures import FIXTURE_META, fixture_68
from mir.midi_ingest import ingest_midi
from mir.notation_regen import recompute_notation
from mir.notation_settings import NotationSettings


def test_context_from_ingest_uses_6_8_and_tempo(tmp_path):
    path = tmp_path / "meter.mid"
    fixture_68(path)
    original = path.read_bytes()
    ingested = ingest_midi(path)
    meta = FIXTURE_META["meter_6_8"]
    assert ingested.time_sig_hint == meta["meter"]
    context = context_from_ingest(
        ingested, meter=meta["meter"], display_bpm=meta["tempo"]
    )
    assert context.selected_meter == "6/8"
    assert context.display_bpm == 90
    result = recompute_notation(
        midi_bytes=original,
        settings=NotationSettings(),
        performance=ingested.performance,
        context=context,
    )
    assert path.read_bytes() == original
    inspected = inspect_xml(result.musicxml)
    assert "6/8" in inspected["shape"]["time_signatures"]
    assert inspected["shape"]["trailing_empty_measures"] >= 0
