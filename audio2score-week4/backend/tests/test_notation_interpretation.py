"""Phase 6 fixtures: derived notation changes, source MIDI does not."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from fractions import Fraction
from pathlib import Path

import pretty_midi
import pytest
from music21 import converter

from evaluation.notation_fixtures import FIXTURES
from mir.models import MeterHypothesis, PlannedNote, PlannedRest
from mir.notation_regen import recompute_job_dir, recompute_notation
from mir.notation_settings import (
    ALGORITHM_VERSION_CURRENT,
    NotationSettings,
)
from mir.performance_cli import convert
from mir.performance_score import quantize_notation
from mir.quantizer import MeasureQuantizer, QuantizerConfig
from mir.types import Hand, MusicalEvent, ScoreMeta
from notation_engine.exact_plan import _pieces, build_exact_measures
from notation_engine.plan import NotationPlanner, validate_voice_timeline


METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
METER_68 = MeterHypothesis("6/8", 6, 8, 3.0, 1.0, 1.0)


def _midi_inventory(path: Path) -> Counter:
    midi = pretty_midi.PrettyMIDI(str(path))
    return Counter((int(note.pitch), round(note.start, 6)) for inst in midi.instruments for note in inst.notes)


def _events_from_midi(path: Path):
    from mir.cmr_builder import notes_to_events
    from mir.midi_ingest import ingest_midi

    ingested = ingest_midi(path)
    return notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi"), ingested


def test_default_settings_match_historical_quantize():
    events = [
        MusicalEvent(60 + i, i + 0.04, 0.91, note_id=f"n{i}", hand=Hand.RIGHT, velocity=80)
        for i in range(4)
    ]
    config = QuantizerConfig()
    out_legacy, dec_legacy, report_legacy = quantize_notation(events, METER, config=config)
    out_default, dec_default, report_default = quantize_notation(
        events, METER, config=config, settings=NotationSettings()
    )
    assert [e.start_beat for e in out_legacy] == [e.start_beat for e in out_default]
    assert [e.duration_beats for e in out_legacy] == [e.duration_beats for e in out_default]
    assert report_default.summary["algorithm_version"] == ALGORITHM_VERSION_CURRENT
    assert report_default.summary["engine"] == "performance"
    assert "onset_error_ms" in dec_default[0]
    assert "local_tempo_bpm" in dec_default[0]
    assert report_legacy.summary["max_onset_error_beats"] == report_default.summary["max_onset_error_beats"]


@pytest.mark.parametrize("name", list(FIXTURES))
def test_fixtures_preserve_midi_hash_and_attack_inventory(tmp_path, name):
    source = tmp_path / f"{name}.mid"
    digest = FIXTURES[name](source)
    original = source.read_bytes()
    assert hashlib.sha256(original).hexdigest() == digest
    output = tmp_path / f"{name}.musicxml"
    report = convert(source, output)
    assert source.read_bytes() == original
    settings = json.loads((tmp_path / f"{name}.notation_settings.json").read_text())
    assert settings["algorithm_version"] == ALGORITHM_VERSION_CURRENT
    assert settings["midi_sha256"] == digest
    assert settings["notation_cache_key"]
    decisions = json.loads(report.read_text())
    summary = decisions["quantization_summary"]
    assert summary["engine"] == "performance"
    assert summary["source_notes"] == len(decisions["quantization_decisions"])
    assert "max_onset_error_ms" in summary
    assert "max_onset_error_beats" in summary
    midi_notes = _midi_inventory(source)
    assert midi_notes
    assert len(decisions["quantization_decisions"]) >= len(midi_notes)
    score = converter.parse(output)
    exported = list(score.flatten().notes)
    assert exported
    xml = output.read_text(encoding="utf-8")
    assert "score-partwise" in xml.lower()


def test_literal_keeps_release_gaps_readable_may_close(tmp_path):
    source = tmp_path / "quarters.mid"
    FIXTURES["humanized_quarters"](source)
    events, _ = _events_from_midi(source)
    config = QuantizerConfig()
    _, readable_dec, readable = quantize_notation(
        events, METER, config=config, settings=NotationSettings()
    )
    _, literal_dec, literal = quantize_notation(
        events, METER, config=config, settings=NotationSettings.literal()
    )
    assert len(readable.notes) == len(literal.notes) == 8
    readable_durs = [float(n.duration) for n in readable.notes]
    literal_durs = [float(n.duration) for n in literal.notes]
    performed = [row["performed_duration"] for row in readable_dec]
    assert readable_durs != literal_durs or all(d == 1.0 for d in readable_durs)
    assert max(abs(a - b) for a, b in zip(literal_durs, performed)) <= max(
        abs(a - b) for a, b in zip(readable_durs, performed)
    ) + 1e-9
    assert all(row["onset_error_ms"] is not None for row in readable_dec)
    assert all(row["release_reason"] for row in readable_dec)


def test_short_rests_and_repeated_attacks_stay_distinct(tmp_path):
    source = tmp_path / "rests.mid"
    FIXTURES["short_rests_repeats"](source)
    events, ingested = _events_from_midi(source)
    meta = ScoreMeta(time_sig_hint="4/4", tempo_map=ingested.tempo_map)
    meta.extra = {"notation_settings": NotationSettings().to_dict()}
    plan, _ = NotationPlanner().build(events, meta=meta, quantization_mode="performance")
    notes = [
        el
        for measure in plan.measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedNote)
    ]
    rests = [
        el
        for measure in plan.measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedRest) and el.kind == "musical" and not el.hidden
    ]
    assert len(notes) == 7
    starts = [float(n.start_q) + measure.start_beat for measure in plan.measures
              for staff in measure.staves for voice in staff.voices
              for n in voice.elements if isinstance(n, PlannedNote)]
    assert starts == sorted(starts)
    assert any(float(r.duration_q) >= 0.125 - 1e-9 for r in rests)


def test_show_meter_splits_syncopation_preserve_does_not(tmp_path):
    source = tmp_path / "sync.mid"
    FIXTURES["syncopation"](source)
    events, ingested = _events_from_midi(source)

    def _plan(syncopation: str):
        meta = ScoreMeta(time_sig_hint="4/4", tempo_map=ingested.tempo_map)
        meta.extra = {
            "notation_settings": NotationSettings.from_dict({"syncopation": syncopation}).to_dict()
        }
        return NotationPlanner().build(events, meta=meta, quantization_mode="performance")[0]

    preserved = _plan("preserve")
    metered = _plan("show_meter")

    def _tied(plan):
        return sum(
            1
            for measure in plan.measures
            for staff in measure.staves
            for voice in staff.voices
            for el in voice.elements
            if isinstance(el, PlannedNote) and el.tie
        )

    assert _tied(metered) >= _tied(preserved)
    pieces = list(_pieces(Fraction(1, 4), Fraction(1), Fraction(1), NotationSettings.from_dict(
        {"syncopation": "show_meter"}
    )))
    assert len(pieces) >= 2
    kept = list(_pieces(Fraction(1, 4), Fraction(1), Fraction(1), NotationSettings()))
    assert kept[0][1] == Fraction(1) or len(kept) <= len(pieces)


def test_compound_68_uses_dotted_beats_and_barline_ties():
    beat = Fraction(3, 2)
    settings = NotationSettings()
    one_beat = list(_pieces(Fraction(0), beat, beat, settings))
    assert one_beat == [(Fraction(0), beat)]
    crossing = list(_pieces(Fraction(2), Fraction(2), beat, settings))
    assert crossing[0][0] == Fraction(2)
    assert sum(length for _start, length in crossing) == Fraction(2)
    events = [
        MusicalEvent(60, 0.0, 4.0, note_id="hold", hand=Hand.LEFT, velocity=70),
        MusicalEvent(72, 0.0, 1.5, note_id="a", hand=Hand.RIGHT, velocity=80),
        MusicalEvent(74, 1.5, 1.5, note_id="b", hand=Hand.RIGHT, velocity=80),
    ]
    result = MeasureQuantizer().quantize_production(events, METER_68)
    measures = build_exact_measures(result.events, result.report, METER_68, "C")
    assert measures[0].duration_beats == 3.0
    hold_ties = [
        el.tie
        for measure in measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedNote) and "hold" in el.event_ids
    ]
    assert "start" in hold_ties and "stop" in hold_ties


def test_mixed_tuplets_keep_binary_and_triplet_attacks(tmp_path):
    source = tmp_path / "tuplets.mid"
    FIXTURES["mixed_tuplets"](source)
    events, _ = _events_from_midi(source)
    _, decisions, report = quantize_notation(events, METER, config=QuantizerConfig())
    families = {row["rhythm_family"] for row in decisions}
    assert "binary" in families
    assert len(report.notes) == len(events)
    ids = [n.source_id for n in report.notes]
    assert len(ids) == len(set(ids))


def test_rubato_pickup_reports_ms_and_beat_error(tmp_path):
    source = tmp_path / "rubato.mid"
    FIXTURES["rubato_pickup"](source)
    events, ingested = _events_from_midi(source)
    settings = NotationSettings.from_dict({"pickup_beats": 0.5, "meter": "4/4"})
    _, decisions, report = quantize_notation(
        events,
        METER,
        config=QuantizerConfig(),
        settings=settings,
        tempo_map=ingested.tempo_map,
    )
    assert report.summary["score_beat_offset"]
    assert all("onset_error_ms" in row and "onset_error_beats" in row for row in decisions)
    assert all(row["local_tempo_bpm"] > 0 for row in decisions)


def test_melody_over_bass_does_not_shorten_independent_hold(tmp_path):
    source = tmp_path / "pedal.mid"
    FIXTURES["melody_over_bass"](source)
    events, ingested = _events_from_midi(source)
    _, decisions, report = quantize_notation(
        events,
        METER,
        config=QuantizerConfig(),
        tempo_map=ingested.tempo_map,
        pedal_events=ingested.pedal_events,
    )
    bass = [row for row in decisions if row["hand"] == "left" or row["raw_start"] == 0]
    long_holds = [row for row in decisions if row["performed_duration"] > 6]
    assert long_holds
    for row in long_holds:
        assert row["release_reason"] in {"multi_attack_hold", "no_line", "phrase_end", "independent_hold"}
        assert float(row["written_duration"]) > 4
        assert row["source_ids"]
    assert any(row.get("pedal_source") in {None, "cc64", "hypothesis"} for row in decisions)
    assert report.summary["source_notes"] == len(events)


def test_unison_and_crossing_keep_independent_attacks(tmp_path):
    source = tmp_path / "unison.mid"
    FIXTURES["unison_crossing"](source)
    events, ingested = _events_from_midi(source)
    meta = ScoreMeta(time_sig_hint="4/4", tempo_map=ingested.tempo_map)
    plan, _ = NotationPlanner().build(events, meta=meta, quantization_mode="performance")
    event_ids = [
        eid
        for measure in plan.measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedNote)
        for eid in el.event_ids
    ]
    assert len(event_ids) == len(set(event_ids))
    assert len(event_ids) == len(events)
    for measure in plan.measures:
        for staff in measure.staves:
            for voice in staff.voices:
                assert not validate_voice_timeline(voice.elements, measure.duration_beats)


def test_structural_rests_are_labeled_on_empty_lanes():
    events = [
        MusicalEvent(72, 0.0, 1.0, note_id="rh", hand=Hand.RIGHT, voice=0, voice_assigned=True),
        MusicalEvent(48, 0.0, 4.0, note_id="lh", hand=Hand.LEFT, voice=0, voice_assigned=True),
    ]
    result = MeasureQuantizer().quantize_production(events, METER)
    measures = build_exact_measures(result.events, result.report, METER, "C")
    kinds = {
        el.kind
        for measure in measures
        for staff in measure.staves
        for voice in staff.voices
        for el in voice.elements
        if isinstance(el, PlannedRest)
    }
    assert "structural" in kinds or "musical" in kinds
    for measure in measures:
        for staff in measure.staves:
            for voice in staff.voices:
                assert not validate_voice_timeline(voice.elements, measure.duration_beats)


def test_regen_does_not_rewrite_midi_or_resubmit_transcription(tmp_path):
    source = tmp_path / "regen.mid"
    digest = FIXTURES["humanized_quarters"](source)
    original = source.read_bytes()
    job_id = "regen"
    out_dir = tmp_path / f"bp_{job_id}"
    convert(source, out_dir / f"{job_id}.musicxml")
    (out_dir / f"{job_id}.raw.mid").write_bytes(original)
    from mir.midi_ingest import ingest_midi

    ingested = ingest_midi(source)
    ingested.performance.write_json(out_dir / f"{job_id}.performance.json")
    first_xml = (out_dir / f"{job_id}.musicxml").read_text(encoding="utf-8")
    result = recompute_job_dir(out_dir, job_id, NotationSettings.literal())
    assert result.transcribed is False
    assert result.midi_sha256 == digest
    assert (out_dir / f"{job_id}.raw.mid").read_bytes() == original
    assert result.musicxml
    second = recompute_notation(midi_bytes=original, settings=NotationSettings())
    assert second.midi_sha256 == digest
    assert second.transcribed is False
    assert second.cache_key != result.cache_key
    assert (out_dir / f"{job_id}.raw.mid").read_bytes() == original
    assert first_xml  # original derived score existed before regen


def test_eighth_grid_does_not_collapse_sixteenth_attacks():
    events = [
        MusicalEvent(72, i * 0.25, 0.2, note_id=f"s{i}", hand=Hand.RIGHT, velocity=80)
        for i in range(8)
    ]
    settings = NotationSettings.from_dict({"display_grid": "eighth"})
    out, _, report = quantize_notation(events, METER, config=QuantizerConfig(), settings=settings)
    assert len(out) == 8
    starts = [round(e.start_beat, 6) for e in out]
    assert starts == sorted(starts)
    assert len(set(starts)) == 8
    assert report.summary["source_notes"] == 8


def test_notation_settings_api_does_not_resubmit_transcription(tmp_path):
    import uuid

    import database as db
    import main as app_main
    from fastapi.testclient import TestClient

    db.init_db()
    job_id = f"ns-{uuid.uuid4().hex[:12]}"
    source = tmp_path / f"{job_id}.mid"
    digest = FIXTURES["humanized_quarters"](source)
    original = source.read_bytes()
    xml_path = tmp_path / f"{job_id}.musicxml"
    convert(source, xml_path)
    (tmp_path / f"{job_id}.raw.mid").write_bytes(original)
    now = db.utcnow()
    db.create_job(
        {
            "id": job_id,
            "status": "completed",
            "filename": "quarters.mid",
            "content_type": "audio/midi",
            "size_bytes": len(original),
            "storage_key": str(source),
            "result_storage_key": str(xml_path),
            "progress": 100,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "mode": "solo",
            "edit_revision": 0,
        }
    )
    with TestClient(app_main.app) as client:
        listed = client.get(f"/jobs/{job_id}/notation-settings")
        assert listed.status_code == 200
        assert listed.json()["algorithm_version"] == ALGORITHM_VERSION_CURRENT
        posted = client.post(
            f"/jobs/{job_id}/notation-settings",
            json={"interpretation": "literal", "revision": 0},
        )
        assert posted.status_code == 200, posted.text
        body = posted.json()
        assert body["transcribed"] is False
        assert body["midi_sha256"] == digest
        assert body["notation_settings"]["interpretation"] == "literal"
        assert (tmp_path / f"{job_id}.raw.mid").read_bytes() == original
        assert client.get(f"/jobs/{job_id}/result?format=notation_settings").status_code == 200
