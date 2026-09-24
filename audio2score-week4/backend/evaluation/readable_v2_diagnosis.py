"""Compare default readable (v1) with opt-in performance-score-2 (v2).

Does not change production behavior. Prints which policy branches fire and
writes MusicXML for OSMD rendering.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from evaluation.notation_fixtures import FIXTURES
from evaluation.readable_v2_cases import EXPECTED_NOTATION, READABLE_V2_CASES
from mir.cmr_builder import notes_to_events
from mir.midi_ingest import ingest_midi
from mir.models import MeterHypothesis
from mir.notation_settings import NotationSettings
from mir.performance_score import (
    _duration,
    _release_hypothesis,
    _search,
    _written_overlap,
    quantize_notation,
)
from mir.quantizer import QuantizerConfig
from notation_engine.writer import NotationWriter
from mir.types import ScoreMeta

METER = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)
V1 = NotationSettings.from_dict(
    {"interpretation": "readable", "algorithm_version": "performance-score-1"}
)
V2 = NotationSettings.from_dict(
    {"interpretation": "readable", "algorithm_version": "performance-score-2"}
)


class BranchLog:
    def __init__(self):
        self.counts = Counter()
        self.releases = []
        self.durations = []
        self.searches = []

    def as_dict(self):
        return {
            "counts": dict(self.counts),
            "releases": self.releases,
            "durations": self.durations,
            "searches": self.searches,
        }


def instrument(log: BranchLog):
    import mir.performance_score as ps

    orig_search = ps._search
    orig_release = ps._release_hypothesis
    orig_duration = ps._duration
    orig_overlap = ps._written_overlap

    def wrapped_search(groups, max_move, beam_width=24, settings=None, measure_length=None, exceptions=None):
        settings = settings or V1
        path = orig_search(groups, max_move, beam_width, settings, measure_length, exceptions)
        v2 = settings.uses_improved_readable()
        log.counts["search_calls"] += 1
        if not v2:
            log.counts["search_v1_return"] += 1
        elif len(path) < 3:
            log.counts["search_v2_skipped_short_path"] += 1
        else:
            families = [family for onset, family in path if onset.denominator != 1]
            if not families:
                log.counts["search_v2_skipped_all_integer"] += 1
            else:
                log.counts["search_v2_family_unify_attempted"] += 1
        log.searches.append(
            {
                "v2": v2,
                "path_len": len(path),
                "families": [family for _, family in path],
            }
        )
        return path

    def wrapped_release(ev, ordered_same_hand, *, settings=None, pedal=None):
        settings = settings or V1
        result = orig_release(ev, ordered_same_hand, settings=settings, pedal=pedal)
        target, reason, source = result
        log.counts[f"release:{reason}"] += 1
        if settings.uses_improved_readable():
            log.counts["release_v2_calls"] += 1
        else:
            log.counts["release_v1_calls"] += 1
        log.releases.append(
            {
                "note_id": ev.note_id,
                "pitch": ev.pitch,
                "raw": round(float(ev.duration_beats), 4),
                "reason": reason,
                "source": source,
                "v2": settings.uses_improved_readable(),
            }
        )
        return result

    def wrapped_overlap(raw, onset, next_onset, overlaps, *, release_reason=None, settings=None):
        settings = settings or V1
        result = orig_overlap(
            raw, onset, next_onset, overlaps, release_reason=release_reason, settings=settings
        )
        log.counts["overlap_calls"] += 1
        if settings.uses_improved_readable():
            log.counts["overlap_v2_calls"] += 1
        return result

    def wrapped_duration(*args, **kwargs):
        settings = kwargs.get("settings") or V1
        value = orig_duration(*args, **kwargs)
        raw = args[0]
        log.durations.append(
            {
                "raw": round(float(raw), 4),
                "written": str(value),
                "written_f": round(float(value), 4),
                "release_reason": kwargs.get("release_reason"),
                "v2": settings.uses_improved_readable(),
            }
        )
        log.counts["duration_calls"] += 1
        return value

    ps._search = wrapped_search
    ps._release_hypothesis = wrapped_release
    ps._written_overlap = wrapped_overlap
    ps._duration = wrapped_duration
    return orig_search, orig_release, orig_duration, orig_overlap


def restore(orig):
    import mir.performance_score as ps

    ps._search, ps._release_hypothesis, ps._duration, ps._written_overlap = orig


def compare(path: Path, settings: NotationSettings, log: BranchLog):
    orig = instrument(log)
    try:
        ingested = ingest_midi(path)
        events = notes_to_events(ingested.notes, ingested.tempo_map, source_backend="midi")
        out, decisions, report = quantize_notation(
            events, METER, config=QuantizerConfig(), settings=settings, pedal_events=ingested.pedal_events
        )
        return out, decisions, report, ingested
    finally:
        restore(orig)


def semantics(decisions):
    return [
        (
            row.get("note_id"),
            round(float(row["quantized_start"]), 4),
            round(float(row.get("written_duration", row.get("quantized_duration", 0))), 4),
            row.get("hand"),
            int(row.get("printed_voice", row.get("voice") or 0)),
            row.get("release_reason"),
        )
        for row in decisions
    ]


def write_xml(events, ingested, dest: Path, settings: NotationSettings):
    meta = ScoreMeta(
        time_sig_hint="4/4",
        tempo_map=ingested.tempo_map,
        display_tempo_bpm=round(ingested.tempo_map.bpm_at(0)),
    )
    meta.extra = {"notation_settings": settings.to_dict(), "pedal_events": list(ingested.pedal_events or [])}
    writer = NotationWriter()
    score = writer.write_from_events_direct(events, meta, quantization_mode="performance")
    dest.parent.mkdir(parents=True, exist_ok=True)
    writer._export_musicxml(score, dest)
    return dest


def run(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"fixtures": {}, "cases": {}}

    def one(name, builder, bucket):
        midi_path = out_dir / f"{name}.mid"
        builder(midi_path)
        log_v1, log_v2 = BranchLog(), BranchLog()
        out1, dec1, rep1, ing1 = compare(midi_path, V1, log_v1)
        out2, dec2, rep2, ing2 = compare(midi_path, V2, log_v2)
        same = semantics(dec1) == semantics(dec2)
        xml1 = write_xml(out1, ing1, out_dir / f"{name}.v1.musicxml", V1)
        xml2 = write_xml(out2, ing2, out_dir / f"{name}.v2.musicxml", V2)
        onset_err_v1 = [abs(float(r.get("onset_error_beats") or 0)) for r in dec1]
        onset_err_v2 = [abs(float(r.get("onset_error_beats") or 0)) for r in dec2]
        release_err_v1 = [
            abs(float(r.get("written_duration", r.get("quantized_duration", 0))) - float(r.get("performed_duration") or 0))
            for r in dec1
        ]
        release_err_v2 = [
            abs(float(r.get("written_duration", r.get("quantized_duration", 0))) - float(r.get("performed_duration") or 0))
            for r in dec2
        ]
        row = {
            "identical": same,
            "v1_semantics": semantics(dec1),
            "v2_semantics": semantics(dec2),
            "v1_release_reasons": [r.get("release_reason") for r in dec1],
            "v2_release_reasons": [r.get("release_reason") for r in dec2],
            "onset_mae_beats": {
                "v1": round(sum(onset_err_v1) / max(len(onset_err_v1), 1), 5),
                "v2": round(sum(onset_err_v2) / max(len(onset_err_v2), 1), 5),
            },
            "written_release_mae_beats": {
                "v1": round(sum(release_err_v1) / max(len(release_err_v1), 1), 5),
                "v2": round(sum(release_err_v2) / max(len(release_err_v2), 1), 5),
            },
            "v1_branches": log_v1.counts,
            "v2_branches": log_v2.counts,
            "xml_v1": str(xml1),
            "xml_v2": str(xml2),
        }
        if name in EXPECTED_NOTATION:
            row["expected"] = EXPECTED_NOTATION[name]
        bucket[name] = row
        print(f"{name}: identical={same} onset_mae={row['onset_mae_beats']} release_mae={row['written_release_mae_beats']}")
        print(f"  v1 reasons={row['v1_release_reasons']}")
        print(f"  v2 counts extra={ {k: v for k, v in log_v2.counts.items() if k not in log_v1.counts or log_v1.counts[k] != v} }")

    for name, builder in FIXTURES.items():
        one(name, builder, report["fixtures"])
    for name, builder in READABLE_V2_CASES.items():
        one(name, builder, report["cases"])

    (out_dir / "readable_v2_diagnosis.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    identical_fixtures = [name for name, row in report["fixtures"].items() if row["identical"]]
    differing_fixtures = [name for name, row in report["fixtures"].items() if not row["identical"]]
    identical_cases = [name for name, row in report["cases"].items() if row["identical"]]
    differing_cases = [name for name, row in report["cases"].items() if not row["identical"]]
    summary = {
        "identical_fixtures": identical_fixtures,
        "differing_fixtures": differing_fixtures,
        "identical_cases": identical_cases,
        "differing_cases": differing_cases,
        "v2_only_branches": [
            "search family unification when path>=3 and a dominant non-integer family",
            "release pedal continuation when CC64, 0.20-2.05 gap, duration ratio, no pulsed-line evidence",
            "duration: leftover release gap smaller than a sixteenth fills to the next attack, barline, or preceding triplet pulse at a group end",
        ],
    }
    (out_dir / "readable_v2_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return report, summary


if __name__ == "__main__":
    run(Path("/opt/cursor/artifacts/readable_v2"))
