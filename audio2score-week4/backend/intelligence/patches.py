"""Apply validated Gemini patches to notes, events, and score meta."""

from __future__ import annotations

from dataclasses import replace

from intelligence.schemas import Correction
from mir.types import Hand, InstrumentKind, MusicalEvent, NoteEvent, ScoreMeta, TempoMap, TempoPoint


def apply_note_patches(
    notes: list[NoteEvent], corrections: list[Correction]
) -> list[NoteEvent]:
    keep: list[NoteEvent] = []
    for note in notes:
        drop = False
        current = note
        for corr in corrections:
            if corr.type not in {"pitch", "timing"}:
                continue
            if not _matches_note(current, corr):
                continue
            proposed = corr.proposed_value or {}
            if proposed.get("drop") or proposed.get("action") == "delete":
                drop = True
                break
            if corr.type == "pitch" and proposed.get("pitch") is not None:
                current = replace(current, pitch=int(proposed["pitch"]))
            if corr.type == "timing":
                start = float(proposed.get("start_time", current.start_time))
                end = float(proposed.get("end_time", current.end_time))
                current = replace(current, start_time=start, end_time=max(end, start + 0.02))
        if not drop:
            keep.append(current)
    return sorted(keep, key=lambda n: (n.start_time, n.pitch))


def apply_event_patches(
    events: list[MusicalEvent],
    corrections: list[Correction],
    tempo_map: TempoMap | None = None,
) -> list[MusicalEvent]:
    result: list[MusicalEvent] = []
    for ev in events:
        current = ev
        for corr in corrections:
            if corr.type not in {"hand", "voice"}:
                continue
            if not _matches_event(current, corr, tempo_map):
                continue
            proposed = corr.proposed_value or {}
            if corr.type == "hand" and proposed.get("hand"):
                try:
                    hand = Hand(str(proposed["hand"]).lower())
                except ValueError:
                    continue
                current = replace(current, hand=hand)
            if corr.type == "voice" and proposed.get("voice") is not None:
                current = replace(current, voice=int(proposed["voice"]))
        result.append(current)
    return result


def apply_meta_patches(
    meta: ScoreMeta,
    tempo_map: TempoMap,
    corrections: list[Correction],
) -> tuple[ScoreMeta, TempoMap]:
    tempo = tempo_map
    for corr in corrections:
        proposed = corr.proposed_value or {}
        if corr.type == "meter" and proposed.get("time_signature"):
            meta = replace(meta, time_sig_hint=str(proposed["time_signature"]))
        if corr.type == "key":
            key = proposed.get("key") or proposed.get("tonality")
            if key:
                meta = replace(meta, key_hint=str(key))
        if corr.type == "tempo":
            bpm = proposed.get("bpm") or proposed.get("global_bpm")
            if bpm is None:
                continue
            bpm_f = float(bpm)
            meta = replace(meta, display_tempo_bpm=int(round(bpm_f)))
            if tempo.points:
                first = tempo.sorted_points()[0]
                tempo = TempoMap(
                    points=[
                        TempoPoint(
                            time_sec=first.time_sec,
                            beat=first.beat,
                            bpm=bpm_f,
                            confidence=max(first.confidence, corr.final_confidence),
                        ),
                        *[p for p in tempo.sorted_points()[1:]],
                    ]
                )
        if corr.type == "instrument" and meta.instrument_prediction:
            name = str(
                proposed.get("instrument") or proposed.get("primary") or ""
            ).lower()
            try:
                kind = InstrumentKind(name)
            except ValueError:
                continue
            pred = meta.instrument_prediction
            meta = replace(
                meta,
                instrument_prediction=replace(
                    pred,
                    instrument=kind,
                    confidence=max(pred.confidence, corr.final_confidence),
                ),
            )
    return meta, tempo


def _matches_note(note: NoteEvent, corr: Correction) -> bool:
    if note.start_time < corr.time_start - 0.06 or note.start_time > corr.time_end + 0.06:
        return False
    existing_pitch = corr.existing_value.get("pitch")
    proposed = corr.proposed_value or {}
    if existing_pitch is None:
        proposed_pitch = proposed.get("pitch")
        if proposed.get("drop") or proposed.get("action") == "delete":
            return proposed_pitch is None or int(note.pitch) == int(proposed_pitch)
        return False
    return int(note.pitch) == int(existing_pitch)


def _matches_event(
    event: MusicalEvent,
    corr: Correction,
    tempo_map: TempoMap | None = None,
) -> bool:
    existing_pitch = corr.existing_value.get("pitch")
    if existing_pitch is not None and int(event.pitch) != int(existing_pitch):
        return False
    start_beat = corr.existing_value.get("start_beat")
    if start_beat is not None:
        return abs(event.start_beat - float(start_beat)) <= 0.08
    if tempo_map is not None:
        lo = tempo_map.seconds_to_beats(corr.time_start) - 0.08
        hi = tempo_map.seconds_to_beats(corr.time_end) + 0.08
        return lo <= event.start_beat <= hi
    return existing_pitch is not None
