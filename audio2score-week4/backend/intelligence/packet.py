"""Build a compact musical analysis packet from pipeline state."""

from __future__ import annotations

from collections import defaultdict

from intelligence.schemas import AudioMetadata, MidiNoteSummary, MusicalAnalysisPacket
from mir.types import Chord, InstrumentPrediction, MusicalEvent, NoteEvent, TempoMap
from notation_engine.meter import estimate_key, estimate_time_signature

MAX_NOTES = 360
MAX_BEATS = 80
MAX_CHORDS = 48
LOW_CONFIDENCE = 0.45


def _note_summaries(notes: list[NoteEvent]) -> tuple[list[dict], bool]:
    ordered = sorted(notes, key=lambda n: (n.start_time, n.pitch))
    truncated = len(ordered) > MAX_NOTES
    if truncated:
        low = [n for n in ordered if n.confidence < LOW_CONFIDENCE]
        step = max(1, len(ordered) // MAX_NOTES)
        sampled = ordered[::step][:MAX_NOTES]
        seen = {(n.pitch, round(n.start_time, 3)) for n in sampled}
        for n in low:
            key = (n.pitch, round(n.start_time, 3))
            if key not in seen and len(sampled) < MAX_NOTES:
                sampled.append(n)
                seen.add(key)
        ordered = sorted(sampled, key=lambda n: (n.start_time, n.pitch))
    rows = [
        MidiNoteSummary(
            pitch=int(n.pitch),
            start=round(float(n.start_time), 3),
            duration=round(float(n.duration), 3),
            velocity=int(n.velocity),
            confidence=round(float(n.confidence), 3),
            hand=getattr(n.hand, "value", str(n.hand)),
        ).to_dict()
        for n in ordered
    ]
    return rows, truncated


def _confidence_summary(notes: list[NoteEvent]) -> dict:
    if not notes:
        return {"mean": 0.0, "min": 0.0, "low_count": 0}
    confs = [float(n.confidence) for n in notes]
    return {
        "mean": round(sum(confs) / len(confs), 3),
        "min": round(min(confs), 3),
        "low_count": sum(1 for c in confs if c < LOW_CONFIDENCE),
    }


def _polyphony_summary(notes: list[NoteEvent]) -> dict:
    if not notes:
        return {"max": 0, "mean": 0.0}
    events: list[tuple[float, int]] = []
    for n in notes:
        events.append((n.start_time, 1))
        events.append((n.end_time, -1))
    events.sort()
    current = 0
    peak = 0
    area = 0.0
    prev = events[0][0]
    duration = max(n.end_time for n in notes) - min(n.start_time for n in notes)
    for t, delta in events:
        area += current * max(0.0, t - prev)
        current += delta
        peak = max(peak, current)
        prev = t
    mean = area / duration if duration > 0 else float(peak)
    return {"max": peak, "mean": round(mean, 2)}


def _low_confidence_regions(notes: list[NoteEvent]) -> list[dict]:
    lows = sorted(
        (n for n in notes if n.confidence < LOW_CONFIDENCE),
        key=lambda n: n.start_time,
    )
    if not lows:
        return []
    regions: list[dict] = []
    start = lows[0].start_time
    end = lows[0].end_time
    count = 1
    for n in lows[1:]:
        if n.start_time <= end + 0.35:
            end = max(end, n.end_time)
            count += 1
        else:
            regions.append(
                {
                    "time_start": round(start, 3),
                    "time_end": round(end, 3),
                    "note_count": count,
                }
            )
            start, end, count = n.start_time, n.end_time, 1
    regions.append(
        {
            "time_start": round(start, 3),
            "time_end": round(end, 3),
            "note_count": count,
        }
    )
    return regions[:24]


def _octave_conflicts(notes: list[NoteEvent]) -> list[dict]:
    conflicts: list[dict] = []
    ordered = sorted(notes, key=lambda n: n.start_time)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 : i + 12]:
            if abs(a.start_time - b.start_time) > 0.05:
                break
            interval = abs(a.pitch - b.pitch)
            if interval not in (12, 24):
                continue
            sa = a.confidence if 0 < a.confidence < 1 else a.velocity / 127.0
            sb = b.confidence if 0 < b.confidence < 1 else b.velocity / 127.0
            quiet, loud = (a, b) if sa <= sb else (b, a)
            conflicts.append(
                {
                    "time_start": round(min(a.start_time, b.start_time), 3),
                    "time_end": round(max(a.end_time, b.end_time), 3),
                    "pitches": [a.pitch, b.pitch],
                    "quiet_pitch": quiet.pitch,
                    "strength_ratio": round(min(sa, sb) / max(max(sa, sb), 1e-6), 3),
                }
            )
            if len(conflicts) >= 24:
                return conflicts
    return conflicts


def _hand_crossings(events: list[MusicalEvent]) -> list[dict]:
    crossings: list[dict] = []
    by_start: dict[float, list[MusicalEvent]] = defaultdict(list)
    for ev in events:
        by_start[round(ev.start_beat, 2)].append(ev)
    for beat, group in by_start.items():
        left = [e for e in group if e.hand.value == "left"]
        right = [e for e in group if e.hand.value == "right"]
        if not left or not right:
            continue
        if max(e.pitch for e in left) > min(e.pitch for e in right) + 2:
            crossings.append(
                {
                    "start_beat": beat,
                    "left_max": max(e.pitch for e in left),
                    "right_min": min(e.pitch for e in right),
                }
            )
        if len(crossings) >= 16:
            break
    return crossings


def build_analysis_packet(
    *,
    job_id: str,
    notes: list[NoteEvent],
    events: list[MusicalEvent],
    tempo_map: TempoMap,
    prediction: InstrumentPrediction | None,
    chords: list[Chord] | None = None,
    duration_seconds: float = 0.0,
    sample_rate: int = 0,
    pedal_events: list[tuple[float, int]] | None = None,
    instrument_candidates: list[dict] | None = None,
) -> MusicalAnalysisPacket:
    rows, truncated = _note_summaries(notes)
    conf = _confidence_summary(notes)
    poly = _polyphony_summary(notes)
    bpm = tempo_map.bpm_at(0.0) if tempo_map.points else None
    tempo_points = tempo_map.sorted_points()
    changes = []
    prev_bpm = None
    for pt in tempo_points:
        if prev_bpm is None or abs(pt.bpm - prev_bpm) / max(prev_bpm, 1e-6) >= 0.08:
            changes.append(
                {
                    "time_sec": round(pt.time_sec, 3),
                    "bpm": round(pt.bpm, 2),
                    "confidence": round(pt.confidence, 3),
                }
            )
            prev_bpm = pt.bpm
    beat_times = [round(pt.time_sec, 3) for pt in tempo_points[:MAX_BEATS]]
    downbeats = beat_times[::4][:24]
    ts = estimate_time_signature(events) if events else "4/4"
    key = estimate_key(events)
    chord_rows = []
    for ch in (chords or [])[:MAX_CHORDS]:
        chord_rows.append(
            {
                "name": ch.name,
                "time": round(ch.start_time, 3),
                "confidence": round(ch.confidence, 3),
                "notes": list(ch.notes),
            }
        )
    phrases = sorted(
        {
            int(ev.phrase_id)
            for ev in events
            if ev.phrase_id is not None
        }
    )
    inst = prediction.instrument.value if prediction else "unknown"
    inst_conf = float(prediction.confidence) if prediction else 0.0
    candidates = instrument_candidates or [
        {"instrument": inst, "confidence": round(inst_conf, 3)}
    ]
    return MusicalAnalysisPacket(
        job_id=job_id,
        audio_metadata=AudioMetadata(
            duration_seconds=round(float(duration_seconds), 3),
            sample_rate=int(sample_rate or 0),
            channels=1,
        ),
        transcription={
            "midi_summary": {"notes": rows, "truncated": truncated},
            "note_count": len(notes),
            "instrument_candidates": candidates,
            "note_confidence_summary": conf,
            "polyphony_summary": poly,
        },
        tempo={
            "global_bpm": round(float(bpm), 2) if bpm else None,
            "tempo_confidence": round(
                sum(p.confidence for p in tempo_points) / max(len(tempo_points), 1),
                3,
            )
            if tempo_points
            else 0.0,
            "tempo_changes": changes[:16],
        },
        meter={"time_signature_candidates": [{"name": ts, "confidence": 0.7}]},
        beats={"beat_times": beat_times, "downbeat_times": downbeats},
        musical_features={
            "key_candidates": [{"name": key, "confidence": 0.6}] if key else [],
            "chord_candidates": chord_rows,
            "sections": [],
            "phrase_candidates": [{"id": pid} for pid in phrases[:32]],
            "repetition_candidates": [],
        },
        uncertainties={
            "low_confidence_regions": _low_confidence_regions(notes),
            "instrument_conflicts": []
            if inst_conf >= 0.5
            else [{"instrument": inst, "confidence": round(inst_conf, 3)}],
            "timing_conflicts": [],
            "pitch_conflicts": _octave_conflicts(notes),
        },
        piano={
            "hand_crossings": _hand_crossings(events),
            "pedal_events": [
                {"time": round(t, 3), "value": int(v)}
                for t, v in (pedal_events or [])[:80]
            ],
        },
    )


def packet_for_regions(
    packet: MusicalAnalysisPacket, windows: list[tuple[float, float]]
) -> MusicalAnalysisPacket:
    notes = packet.transcription.get("midi_summary", {}).get("notes") or []
    kept = []
    for row in notes:
        start = float(row.get("start") or 0.0)
        if any(lo - 0.05 <= start <= hi + 0.05 for lo, hi in windows):
            kept.append(row)
    clone = MusicalAnalysisPacket(
        job_id=packet.job_id,
        audio_metadata=packet.audio_metadata,
        transcription={
            **packet.transcription,
            "midi_summary": {"notes": kept, "truncated": False},
            "note_count": len(kept),
        },
        tempo=packet.tempo,
        meter=packet.meter,
        beats=packet.beats,
        musical_features=packet.musical_features,
        uncertainties={
            **packet.uncertainties,
            "focus_windows": [
                {"time_start": lo, "time_end": hi} for lo, hi in windows
            ],
        },
        piano=packet.piano,
    )
    return clone
