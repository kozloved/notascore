"""Opt-in readable-v2 vs default on short notes and small release gaps."""

from __future__ import annotations

from pathlib import Path

from evaluation.readable_v2_cases import READABLE_V2_CASES
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
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
    out, decisions, _report = quantize_notation(
        events,
        METER,
        config=QuantizerConfig(),
        settings=settings,
        pedal_events=ingested.pedal_events,
    )
    return out, decisions, ingested


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


def test_repeated_attacks_under_pedal_keep_four_attacks_on_both(tmp_path):
    """C remains a known limitation: overlapping same-pitch MIDI is not four quarters.

    The small-gap fill does not apply (leftover >= a sixteenth after ingest).
    v2 must not merge the re-attacks into one tied sustain or drop attacks.
    """
    source = tmp_path / "C.mid"
    READABLE_V2_CASES["C_repeated_attacks_under_pedal"](source)
    original = source.read_bytes()
    v1, _dec1, _ = _quantize(source, V1)
    v2, _dec2, _ = _quantize(source, V2)
    assert source.read_bytes() == original
    assert [round(e.start_beat, 4) for e in v1] == [0.0, 1.0, 2.0, 3.0]
    assert [round(e.start_beat, 4) for e in v2] == [0.0, 1.0, 2.0, 3.0]
    assert [n.pitch for n in v1] == [67, 67, 67, 67]
    assert [round(e.duration_beats, 4) for e in v1] == [round(e.duration_beats, 4) for e in v2]
    assert [round(e.duration_beats, 4) for e in v2] == [1.0, 0.1875, 0.1875, 0.1875]
