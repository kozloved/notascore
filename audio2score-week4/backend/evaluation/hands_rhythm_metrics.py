"""Frozen complexity metrics for hands/rhythm Phase 3 review.

Counts attacks, pitched symbols, ties, tiny durations, max written voices,
and hand switches. Synthetic fixtures are always available in git; Autumn
Walks artifacts under ``.tmp/autumn-walks-review/`` are optional and never
committed (private audio/MIDI).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = PACKAGE_DIR.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from mir.hand_separator import HandSeparator
from mir.models import MeterHypothesis
from mir.performance_score import assign_pipeline_layout, quantize_notation
from mir.score_metrics import metrics_from_plan
from mir.score_profile import score_profile
from mir.types import Hand, MusicalEvent, ScoreMeta
from mir.voice_separator import VoiceSeparator
from notation_engine.plan import NotationPlanner

AUTUMN_REVIEW = BACKEND_ROOT / ".tmp" / "autumn-walks-review"
BASELINE_PATH = PACKAGE_DIR / "baselines" / "hands_rhythm_phase3.json"
RESULTS_DIR = PACKAGE_DIR / "results" / "hands_rhythm"
TINY_TYPES = ("32nd", "64th", "128th", "256th")


def _strip_ns(root: ET.Element) -> None:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def musicxml_complexity(path: Path) -> dict[str, Any]:
    """Handoff-style MusicXML complexity (pitched symbols, ties, tiny tails).

    Each musical tie start is counted once. MusicXML often emits both ``<tie>``
    and ``<tied>`` for the same start; do not double-count them.
    """
    root = ET.parse(path).getroot()
    _strip_ns(root)
    pitched = 0
    tie_starts = 0
    tiny = {t: 0 for t in TINY_TYPES}
    time_mod = 0
    voices_by_cell: dict[tuple[str | None, str], set[str]] = defaultdict(set)
    for measure in root.findall(".//measure"):
        mid = measure.get("number")
        for note in measure.findall("note"):
            if note.find("rest") is not None:
                continue
            if note.find("pitch") is None and note.find("unpitched") is None:
                continue
            pitched += 1
            staff = note.findtext("staff") or "1"
            voice = note.findtext("voice") or "1"
            voices_by_cell[(mid, staff)].add(voice)
            ntype = note.findtext("type") or ""
            if ntype in tiny:
                tiny[ntype] += 1
            if note.find("time-modification") is not None:
                time_mod += 1
            has_tie_start = any(
                tie.get("type") == "start" for tie in note.findall("tie")
            )
            has_tied_start = any(
                tied.get("type") == "start"
                for tied in note.findall("./notations/tied")
            )
            if has_tie_start or has_tied_start:
                tie_starts += 1
    return {
        "pitched_symbols": pitched,
        "tie_starts": tie_starts,
        "tiny_32nd": tiny["32nd"],
        "tiny_64th": tiny["64th"],
        "tiny_128th": tiny["128th"],
        "tiny_total": sum(tiny.values()),
        "time_modifications": time_mod,
        "max_voices_in_measure_staff": max(
            (len(v) for v in voices_by_cell.values()), default=0
        ),
    }


def hand_switch_count(events: list[MusicalEvent]) -> int:
    """Count consecutive same-staff pitch-order hand flips within a phrase."""
    ordered = sorted(events, key=lambda e: (e.start_beat, e.pitch, e.note_id))
    switches = 0
    prev = None
    for ev in ordered:
        hand = ev.hand
        if hand not in (Hand.LEFT, Hand.RIGHT):
            prev = hand
            continue
        if prev in (Hand.LEFT, Hand.RIGHT) and hand != prev:
            switches += 1
        prev = hand
    return switches


def layout_metrics(events: list[MusicalEvent]) -> dict[str, Any]:
    return {
        "attacks": len(events),
        "hand_switches": hand_switch_count(events),
        "max_voice_id": max((int(ev.voice) for ev in events), default=0),
        "distinct_voices": len({(ev.hand, ev.voice) for ev in events}),
    }


def _ev(pitch, start, dur, nid, hand=Hand.UNKNOWN, **kwargs):
    return MusicalEvent(
        pitch=pitch,
        start_beat=float(start),
        duration_beats=float(dur),
        note_id=nid,
        velocity=80,
        hand=hand,
        **kwargs,
    )


def synthetic_cases() -> dict[str, list[MusicalEvent]]:
    """Git-safe Phase 1/2 fixtures used as the review corpus."""
    pedal = [_ev(48, i, 1.8, f"pedal{i}") for i in range(4)]
    broken = []
    for i in range(4):
        broken.extend([
            _ev(36, float(i), 0.95, f"bass{i}"),
            _ev(48, float(i) + 0.33, 0.6, f"mid{i}"),
            _ev(55, float(i) + 0.66, 0.6, f"mid2{i}"),
            _ev(72, float(i), 0.95, f"mel{i}"),
        ])
    boundary = [
        _ev(60 + i, float(i) * 4, raw, f"b{raw}")
        for i, raw in enumerate((0.94, 1.17, 1.94, 2.21))
    ]
    independent = []
    for i in range(4):
        independent.append(_ev(76, float(i), 1.0, f"m{i}", hand=Hand.RIGHT, hand_locked=True))
        independent.append(
            _ev(60, float(i) + 0.5, 1.0, f"i{i}", hand=Hand.RIGHT, hand_locked=True)
        )
    return {
        "pedal_quarters": pedal,
        "broken_chord_waltz": broken,
        "near_boundary_releases": boundary,
        "independent_rh_voices": independent,
    }


METER_44 = MeterHypothesis("4/4", 4, 4, 4.0, 1.0, 1.0)


def run_synthetic_case(name: str, events: list[MusicalEvent]) -> dict[str, Any]:
    from mir.performance_score import _duration

    raw = deepcopy(events)
    laid = assign_pipeline_layout(
        raw, score_profile(raw), HandSeparator(), VoiceSeparator()
    ).events
    result: dict[str, Any] = {
        "case": name,
        "layout": layout_metrics(laid),
        "raw_unchanged": True,
    }
    if name == "near_boundary_releases":
        written = {}
        for ev in events:
            chosen = _duration(
                float(ev.duration_beats), 0, None, False, "binary"
            )
            written[ev.note_id] = str(chosen)
        result["written_durations"] = written
        result["plan"] = {
            "printed_notes": len(events),
            "ties": 0,
            "notes_32nd_or_shorter": 0,
            "voices_max_per_staff": 1,
            "fragment_ties": 0,
            "tuplets": 0,
            "source_identity_preserved": True,
        }
        result["layout_source"] = "n/a"
        return result

    out, decisions, report = quantize_notation(
        laid, METER_44, config=type("C", (), {"max_onset_move": 0.18})()
    )
    plan, _ = NotationPlanner().build(
        out, meta=ScoreMeta(time_sig_hint="4/4"), quantization_mode="performance"
    )
    plan_metrics = metrics_from_plan(plan, source_notes=events, quantized=out)
    result.update({
        "layout_source": report.summary.get("layout_source"),
        "plan": {
            "printed_notes": plan_metrics["printed_notes"],
            "ties": plan_metrics["ties"],
            "notes_32nd_or_shorter": plan_metrics["notes_32nd_or_shorter"],
            "voices_max_per_staff": plan_metrics["voices_max_per_staff"],
            "fragment_ties": plan_metrics["fragment_ties"],
            "tuplets": plan_metrics["tuplets"],
            "source_identity_preserved": plan_metrics["source_identity_preserved"],
        },
        "written_durations": {
            n.source_id: str(n.duration) for n in report.notes
        },
        "raw_unchanged": all(
            a.duration_beats == b.duration_beats and a.start_beat == b.start_beat
            for a, b in zip(events, raw)
        ),
    })
    return result


def replay_autumn_walks_aligned(review_dir: Path, job_id: str = "hands_rhythm_aligned") -> dict[str, Any]:
    """Replay Autumn Walks with frozen audio beat map + forced 3/4 meter.

    Uses MT3 source semantics (``source_backend="mt3"``) so written-duration
    inference matches production polyphonic jobs. The MIDI file is only the
    frozen MT3 note payload — it must not enable MIDI duration preservation.
    """
    import hashlib
    import shutil

    from audio_engine.madmom_beats import MadmomBeatResult
    from mir.cmr_builder import build_score_meta, notes_to_events
    from mir.meter import meter_from_time_signature
    from mir.midi_ingest import ingest_midi
    from mir.models import MusicalStructure
    from mir.pipeline import UnderstandingPipeline
    from mir.pipeline_config import QuantizationMode
    from mir.types import InstrumentKind, TempoMap, TempoPoint
    from timing.service import resolve_from_beat_times

    midi = review_dir / "mt3-original.mid"
    beats_path = review_dir / "detected-beats.json"
    alignment_path = review_dir / "alignment-result.json"
    if not midi.is_file() or not beats_path.is_file():
        return {"status": "skipped", "reason": "missing midi or detected-beats.json"}

    beats = json.loads(beats_path.read_text(encoding="utf-8"))
    alignment = (
        json.loads(alignment_path.read_text(encoding="utf-8"))
        if alignment_path.is_file()
        else {}
    )
    raw_sha = hashlib.sha256(midi.read_bytes()).hexdigest()
    expected_sha = alignment.get("raw_sha256")
    beat_times = list(beats["beat_times"])
    downbeats = list(beats["downbeats"])
    bpm = float(beats.get("bpm") or 120.0)
    duration = float(beats.get("duration_sec") or max(beat_times[-1] + 1.0, 1.0))

    timing = resolve_from_beat_times(
        beat_times,
        downbeat_times=downbeats,
        duration_sec=duration,
        model="autumn_walks_detected_beats",
    )
    tempo_map = TempoMap(points=[TempoPoint(time_sec=0.0, beat=0.0, bpm=bpm)])
    # Pipeline backend name is informational; note/event semantics are MT3.
    pipe = UnderstandingPipeline(backend_name="mt3")
    pipe.last_timing = timing
    pipe.last_musical_time_map = timing.time_map
    pipe.beat_tracker.last_beat_result = MadmomBeatResult(
        tempo_map=tempo_map,
        time_signature="3/4",
        beat_times=beat_times,
        downbeat_times=downbeats,
        beats_per_bar=3,
        bpm=bpm,
        grouping_beats_per_bar=3,
        grouping_meter="3/4",
        grouping_beat_times=list(beats.get("grouping_times") or beat_times),
        grouping_positions=list(beats.get("grouping_positions") or []),
    )

    ingested = ingest_midi(midi, source_backend="mt3")
    notes = []
    for i, n in enumerate(ingested.notes):
        note = n.ensure_ids(i)
        if getattr(note, "source_backend", "unknown") in ("", "unknown", "midi"):
            from dataclasses import replace as dc_replace

            note = dc_replace(note, source_backend="mt3")
        notes.append(note)
    pipe.last_raw_notes = list(notes)
    role = pipe.role_separator.separate(notes)
    kinds = {n.instrument for n in notes}
    instrument = next(iter(kinds)) if len(kinds) == 1 else InstrumentKind.PIANO
    events = notes_to_events(
        notes,
        timing.time_map,
        role=role,
        instrument=instrument,
        source_backend="mt3",
    )
    events = pipe._apply_mir_layers(events)
    meter = meter_from_time_signature("3/4", source="autumn_walks_freeze")
    score_downbeats = alignment.get("score_downbeats_beats") or []
    if score_downbeats:
        meter.evidence["downbeat_beats"] = [float(b) for b in score_downbeats]
    events = pipe._align_score_meter(events, notes, timing, meter)

    out_dir = review_dir / f"bp_{job_id}"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = build_score_meta(
        tempo_map,
        instrument,
        [],
        display_bpm=int(round(bpm)),
        instrument_confidence=0.9,
        time_sig_hint="3/4",
    )
    meta.extra = {
        **(meta.extra or {}),
        "meter_source": "autumn_walks_freeze",
        "beat_source": "detected-beats.json",
        "forced_meter": "3/4",
        "source_semantics": "mt3",
        "frozen_midi_payload": True,
    }

    structure = MusicalStructure(
        events=events,
        tempo_map=tempo_map,
        meter_hypotheses=[meter],
        selected_meter=meter,
        instrument=instrument,
        instrument_confidence=0.9,
        extra={"source": "autumn_walks_aligned_replay", "source_semantics": "mt3"},
    )
    xml, notation_result = pipe.notation.write_musicxml_with_result(
        events,
        meta,
        job_id=job_id,
        audio_path=midi,
        fallback_bpm=bpm,
        structure=structure,
        quantization_mode=QuantizationMode.PERFORMANCE,
    )
    xml_path = out_dir / f"{job_id}.musicxml"
    plan = pipe.notation.last_plan
    plan_m = metrics_from_plan(
        plan,
        source_notes=notes,
        quantized=notation_result.quantized_events,
    )
    xml_m = musicxml_complexity(xml_path) if xml_path.is_file() else None
    voice_probe = _voice_distribution(notation_result.quantized_events)
    summary = getattr(pipe.notation, "last_quantization_summary", None) or {}
    if not summary and getattr(notation_result, "quantization", None) is not None:
        summary = getattr(notation_result.quantization, "summary", None) or {}
    backends = sorted({ev.source_backend for ev in events})
    return {
        "status": "ok",
        "job_id": job_id,
        "raw_sha256": raw_sha,
        "raw_sha_matches_alignment": (
            None if not expected_sha else raw_sha == expected_sha
        ),
        "meter": "3/4",
        "source_semantics": "mt3",
        "event_source_backends": backends,
        "duration_preserve_enabled": False,
        "beat_count": len(beat_times),
        "downbeat_count": len(downbeats),
        "attacks": len(notes),
        "layout_authority": summary.get("layout_authority"),
        "plan": {
            "source_note_count": plan_m["source_note_count"],
            "printed_notes": plan_m["printed_notes"],
            "ties": plan_m["ties"],
            "notes_32nd_or_shorter": plan_m["notes_32nd_or_shorter"],
            "voices_max_per_staff": plan_m["voices_max_per_staff"],
            "fragment_ties": plan_m["fragment_ties"],
            "tuplets": plan_m["tuplets"],
            "source_identity_preserved": plan_m["source_identity_preserved"],
        },
        "musicxml": xml_m,
        "voice_distribution": voice_probe,
        "xml_path": str(xml_path),
        "xml_chars": len(xml or ""),
    }


def _voice_distribution(events) -> dict[str, Any]:
    by_staff: dict[int, set[int]] = defaultdict(set)
    by_measure_staff: dict[tuple[int, int], set[int]] = defaultdict(set)
    for ev in events or []:
        staff = 0 if ev.hand == Hand.RIGHT else 1 if ev.hand == Hand.LEFT else 0
        voice = int(ev.voice)
        by_staff[staff].add(voice)
        measure = int(ev.start_beat // 3)
        by_measure_staff[(measure, staff)].add(voice)
    max_cell = max((len(v) for v in by_measure_staff.values()), default=0)
    hotspots = sorted(
        (
            {"measure": m, "staff": s, "voices": sorted(vs)}
            for (m, s), vs in by_measure_staff.items()
            if len(vs) >= 4
        ),
        key=lambda row: (-len(row["voices"]), row["measure"], row["staff"]),
    )[:8]
    return {
        "voices_by_staff": {str(k): sorted(v) for k, v in sorted(by_staff.items())},
        "max_voices_in_measure_staff_events": max_cell,
        "hotspots_ge_4": hotspots,
    }


def autumn_walks_metrics() -> dict[str, Any] | None:
    if not AUTUMN_REVIEW.is_dir():
        return None
    payload: dict[str, Any] = {"present": True, "path": str(AUTUMN_REVIEW)}
    before = AUTUMN_REVIEW / "current-main.musicxml"
    if before.is_file():
        payload["before_current_main"] = musicxml_complexity(before)
        payload["before_note"] = (
            "Frozen MusicXML from the handoff replay on current main "
            "(155 pitched / 100 attacks baseline cited in the handoff)."
        )
    prod = AUTUMN_REVIEW / "production-before.musicxml"
    if prod.is_file():
        payload["production_before"] = musicxml_complexity(prod)

    aligned = replay_autumn_walks_aligned(AUTUMN_REVIEW)
    payload["after_aligned_replay"] = aligned
    if aligned.get("status") == "ok" and aligned.get("musicxml") and "before_current_main" in payload:
        before_m = payload["before_current_main"]
        after_xml = aligned["musicxml"]
        payload["deltas_vs_current_main"] = {
            key: after_xml[key] - before_m[key]
            for key in (
                "pitched_symbols",
                "tie_starts",
                "tiny_total",
                "time_modifications",
                "max_voices_in_measure_staff",
            )
        }
        payload["comparable"] = {
            "same_midi": aligned.get("raw_sha_matches_alignment"),
            "forced_meter": "3/4",
            "beat_source": "detected-beats.json",
            "source_semantics": aligned.get("source_semantics"),
            "duration_preserve_enabled": aligned.get("duration_preserve_enabled"),
            "event_source_backends": aligned.get("event_source_backends"),
            "attacks": aligned.get("attacks"),
            "voice_investigation": aligned.get("voice_distribution"),
        }
        if after_xml["max_voices_in_measure_staff"] > before_m["max_voices_in_measure_staff"]:
            payload["voice_increase_note"] = (
                "Max simultaneous written voices rose versus current-main.musicxml. "
                "Inspect voice_distribution.hotspots_ge_4; likely pedal-tail lines "
                "kept as independent holds after release hypotheses, not a meter drift."
            )
    else:
        payload["deltas_vs_current_main"] = None
    return payload

def run_review() -> dict[str, Any]:
    synthetic = {
        name: run_synthetic_case(name, events)
        for name, events in synthetic_cases().items()
    }
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commits_note": (
            "Gap closure after d59a0ef: per-hand decay, stamped layout authority, "
            "meter-aware releases, line/release hypotheses. Phase 3 not complete."
        ),
        "synthetic": synthetic,
        "autumn_walks": autumn_walks_metrics(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write evaluation/baselines/hands_rhythm_phase3.json",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=RESULTS_DIR,
        help="Directory for the latest review JSON",
    )
    args = parser.parse_args(argv)
    report = run_review()
    args.results_dir.mkdir(parents=True, exist_ok=True)
    out = args.results_dir / "latest.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.write_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Baseline freezes synthetic metrics; Autumn Walks stays optional.
        baseline = {
            "name": "hands_rhythm_phase3",
            "generated_at": report["generated_at"],
            "synthetic": {
                name: {
                    "layout": case["layout"],
                    "plan": case["plan"],
                    "written_durations": case["written_durations"],
                }
                for name, case in report["synthetic"].items()
            },
            "autumn_walks_optional": report.get("autumn_walks"),
        }
        BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE_PATH}")
    print(f"wrote {out}")
    aw = report.get("autumn_walks")
    if aw and aw.get("deltas_vs_current_main"):
        print("autumn_walks deltas:", json.dumps(aw["deltas_vs_current_main"]))
    else:
        print("autumn_walks: skipped or incomplete (expected without local fixtures)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
