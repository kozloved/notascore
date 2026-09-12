"""Post-transcription score correction.

Edits operate on a simple note list derived from the stored MusicXML.
Original transcription files are never overwritten.

This module does not call the transcription pipeline, quantizer, or
notation planner.
"""

from __future__ import annotations

import json
import re
import tempfile
from math import isfinite
from pathlib import Path
from typing import Any

GRID = 0.25  # sixteenth note in quarter-note beats
MAX_NOTES = 4000
MAX_TEMPO_CURVE = 512
MAX_START = 10_000.0
MAX_DURATION = 32.0
PITCH_MIN = 0
PITCH_MAX = 127
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TIME_SIG_RE = re.compile(r"^([1-9]|1[0-6])/(1|2|4|8|16)$")


class EditError(ValueError):
    """Invalid edited score payload."""


def validate_voice(value: Any) -> int:
    try:
        voice = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(15, voice))


def validate_source_note_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not ID_RE.match(text):
        raise EditError("Invalid source_note_id.")
    return text


def validate_tempo_curve(raw: Any, *, fallback_bpm: float) -> list[dict]:
    if raw is None:
        return [{"beat": 0.0, "bpm": float(fallback_bpm)}]
    if not isinstance(raw, list):
        raise EditError("tempo_curve must be a list.")
    if len(raw) > MAX_TEMPO_CURVE:
        raise EditError("tempo_curve is too long.")
    points: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise EditError("Each tempo_curve point must be an object.")
        beat = float(item.get("beat", 0))
        if beat != beat or beat < 0 or beat > MAX_START:
            raise EditError("tempo_curve beat is out of range.")
        bpm = validate_tempo(item.get("bpm", fallback_bpm))
        points.append({"beat": beat, "bpm": bpm})
    points.sort(key=lambda row: (row["beat"], row["bpm"]))
    if not points or points[0]["beat"] > 1e-9:
        points.insert(0, {"beat": 0.0, "bpm": float(fallback_bpm)})
    deduped: list[dict] = []
    for point in points:
        if deduped and abs(deduped[-1]["beat"] - point["beat"]) < 1e-9:
            deduped[-1] = point
        else:
            deduped.append(point)
    return deduped


def snap_grid(value: float) -> float:
    if not isinstance(value, (int, float)) or not isfinite(value):
        raise EditError("Timing values must be finite numbers.")
    snapped = round(float(value) / GRID) * GRID
    return float(snapped)


def pitch_name(midi: int) -> str:
    names = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"]
    pitch = int(midi)
    octave = (pitch // 12) - 1
    return f"{names[pitch % 12]}{octave}"


def _as_int(value: Any, *, field: str, lo: int, hi: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise EditError(f"Invalid {field}.") from exc
    if number < lo or number > hi:
        raise EditError(f"Invalid {field}.")
    return number


def validate_notes(raw_notes: Any) -> list[dict]:
    if not isinstance(raw_notes, list):
        raise EditError("Notes must be a list.")
    if len(raw_notes) > MAX_NOTES:
        raise EditError("Too many notes to save.")

    seen_ids: set[str] = set()
    notes: list[dict] = []
    for item in raw_notes:
        if not isinstance(item, dict):
            raise EditError("Each note must be an object.")
        note_id = str(item.get("id") or "").strip()
        if not ID_RE.match(note_id):
            raise EditError("Each note needs a stable id.")
        if note_id in seen_ids:
            raise EditError("Note ids must be unique.")
        seen_ids.add(note_id)

        pitch = _as_int(item.get("pitch"), field="pitch", lo=PITCH_MIN, hi=PITCH_MAX)
        start = float(item.get("start", 0))
        duration = float(item.get("duration", GRID))
        if not isfinite(start) or not isfinite(duration):
            raise EditError("Timing values must be finite numbers.")
        if start < 0 or start > MAX_START:
            raise EditError("Note start is out of range.")
        if duration <= 0 or duration > MAX_DURATION:
            raise EditError("Note duration is out of range.")
        velocity = _as_int(item.get("velocity", 64), field="velocity", lo=1, hi=127)
        track = _as_int(item.get("track", 0), field="track", lo=0, hi=3)
        notes.append(
            {
                "id": note_id,
                "source_note_id": validate_source_note_id(item.get("source_note_id", note_id)),
                "pitch": pitch,
                "start": start,
                "duration": duration,
                "velocity": velocity,
                "track": track,
                "voice": validate_voice(item.get("voice", 0)),
            }
        )
    notes.sort(key=lambda note: (note["start"], note["track"], note["pitch"], note["id"]))
    return notes


def validate_time_signature(value: Any) -> str:
    text = str(value or "4/4").strip()
    if not TIME_SIG_RE.match(text):
        return "4/4"
    return text


def validate_tempo(value: Any) -> float:
    try:
        tempo = float(value)
    except (TypeError, ValueError):
        return 120.0
    if tempo != tempo or tempo < 20 or tempo > 300:
        return 120.0
    return tempo


def parse_edits_payload(body: dict) -> dict:
    notes = validate_notes(body.get("notes"))
    tempo_bpm = validate_tempo(body.get("tempo_bpm"))
    return {
        "tempo_bpm": tempo_bpm,
        "time_signature": validate_time_signature(body.get("time_signature")),
        "tempo_curve": validate_tempo_curve(body.get("tempo_curve"), fallback_bpm=tempo_bpm),
        "notes": notes,
    }


def extract_from_musicxml(musicxml_text: str) -> dict:
    from music21 import converter
    from notation_engine.integrity import score_attacks

    if not musicxml_text or not str(musicxml_text).strip():
        raise EditError("Score is empty.")

    score = converter.parse(musicxml_text, format="musicxml")
    tempo_bpm = 120.0
    marks = list(score.flatten().getElementsByClass("MetronomeMark"))
    if marks and getattr(marks[0], "number", None):
        tempo_bpm = validate_tempo(marks[0].number)

    tempo_curve: list[dict] = []
    for mark in marks:
        bpm = getattr(mark, "number", None)
        if bpm is None:
            continue
        try:
            offset = float(mark.getOffsetInHierarchy(score))
        except Exception:
            offset = float(getattr(mark, "offset", 0) or 0)
        tempo_curve.append({"beat": offset, "bpm": validate_tempo(bpm)})
    if not tempo_curve:
        tempo_curve = [{"beat": 0.0, "bpm": float(tempo_bpm)}]

    time_signature = "4/4"
    signatures = list(score.flatten().getTimeSignatures())
    if signatures and getattr(signatures[0], "ratioString", None):
        time_signature = validate_time_signature(signatures[0].ratioString)

    notes: list[dict] = []
    for index, attack in enumerate(score_attacks(score)):
        if attack.end <= attack.start:
            continue
        note_id = f"n-{index:04d}"
        try:
            voice = max(0, int(str(attack.voice)) - 1)
        except (TypeError, ValueError):
            voice = 0
        notes.append(
            {
                "id": note_id,
                "source_note_id": note_id,
                "pitch": max(PITCH_MIN, min(PITCH_MAX, attack.pitch)),
                "start": attack.start,
                "duration": attack.end - attack.start,
                "velocity": max(1, min(127, attack.velocity)),
                "track": attack.track,
                "voice": validate_voice(voice),
            }
        )
    return {
        "tempo_bpm": tempo_bpm,
        "time_signature": time_signature,
        "tempo_curve": validate_tempo_curve(tempo_curve, fallback_bpm=tempo_bpm),
        "notes": validate_notes(notes),
    }


def _attach_source_identity(event, source_note_id: str | None) -> None:
    if not source_note_id:
        return
    editorial = getattr(event, "editorial", None)
    if editorial is None:
        return
    misc = getattr(editorial, "misc", None)
    if misc is None:
        editorial.misc = {"source_note_id": source_note_id}
    elif isinstance(misc, dict):
        misc["source_note_id"] = source_note_id


def _apply_tempo_curve(part, curve: list[dict]) -> None:
    from music21 import stream, tempo

    for mark in list(part.recurse().getElementsByClass("MetronomeMark")):
        site = mark.activeSite
        if site is not None:
            site.remove(mark)
    measures = list(part.getElementsByClass(stream.Measure))
    for point in curve:
        beat = float(point["beat"])
        mark = tempo.MetronomeMark(number=point["bpm"])
        target = None
        offset = beat
        for measure in measures:
            start = float(measure.offset)
            length = float(measure.barDuration.quarterLength) if measure.barDuration else 4.0
            if start - 1e-9 <= beat < start + length - 1e-12:
                target = measure
                offset = max(0.0, beat - start)
                break
        if target is None and measures:
            target = measures[-1]
            offset = max(0.0, beat - float(target.offset))
        if target is not None:
            target.insert(offset, mark)
        else:
            part.insert(beat, mark)


def build_musicxml_and_midi(payload: dict) -> tuple[str, bytes]:
    from music21 import clef, converter, instrument, meter, note, stream

    data = parse_edits_payload(payload)
    from mir.types import MusicalEvent
    from notation_engine.integrity import validate_exports
    from notation_engine.playback import playback_score

    events = [
        MusicalEvent(
            n["pitch"],
            n["start"],
            n["duration"],
            velocity=n["velocity"],
            note_id=n["id"],
            voice=int(n.get("voice") or 0),
            source_track_id=str(n["track"]),
        )
        for n in data["notes"]
    ]
    score = stream.Score()
    tracks: dict[int, list[dict]] = {}
    for item in data["notes"]:
        tracks.setdefault(item["track"], []).append(item)
    staff_indexes = sorted(tracks) or [0]
    if max(staff_indexes) >= 1 and 0 not in staff_indexes:
        staff_indexes = [0, *staff_indexes]

    curve = data["tempo_curve"]
    for staff_index in staff_indexes:
        part = stream.Part(id=f"P{staff_index + 1}")
        part.partName = "Piano"
        part.insert(0, instrument.Piano())
        part.insert(0, meter.TimeSignature(data["time_signature"]))
        part.insert(0, clef.TrebleClef() if staff_index == 0 else clef.BassClef())
        staff_notes = tracks.get(staff_index, [])
        if not staff_notes:
            part.append(note.Rest(quarterLength=4.0))
        for item in staff_notes:
            event = note.Note(item["pitch"])
            event.quarterLength = item["duration"]
            event.volume.velocity = item["velocity"]
            _attach_source_identity(event, item.get("source_note_id"))
            part.insert(item["start"], event)
        # makeNotation fills measures/rests/beams from the note list.
        # This is music21 engraving, not the transcription notation planner.
        if part.recurse().notes:
            part.makeNotation(inPlace=True)
        else:
            if not list(part.recurse().getElementsByClass("Rest")):
                part.append(note.Rest(quarterLength=4.0))
            part.makeNotation(inPlace=True)
        _apply_tempo_curve(part, curve)
        score.insert(0, part)

    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "edited.musicxml"
        midi_path = Path(tmp) / "edited.mid"
        score.write("musicxml", fp=str(xml_path))
        tempo_points = [(float(point["beat"]), float(point["bpm"])) for point in data["tempo_curve"]]
        playback = playback_score(events, data["time_signature"], tempo_points)
        playback.write("midi", fp=str(midi_path))
        validate_exports(xml_path, midi_path, events)
        xml_text = xml_path.read_text(encoding="utf-8")
        midi_bytes = midi_path.read_bytes()

    # Confirm the written MusicXML still parses.
    converter.parse(xml_text, format="musicxml")
    return xml_text, midi_bytes


def dumps_edits(payload: dict) -> str:
    data = parse_edits_payload(payload)
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def loads_edits(text: str) -> dict:
    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EditError("Saved edits could not be read.") from exc
    if not isinstance(body, dict):
        raise EditError("Saved edits could not be read.")
    return parse_edits_payload(body)


def edited_keys(job_id: str) -> dict[str, str]:
    return {
        "json": f"{job_id}.edits.json",
        "musicxml": f"{job_id}.edited.musicxml",
        "midi": f"{job_id}.edited.mid",
    }
