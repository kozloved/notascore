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
from pathlib import Path
from typing import Any

GRID = 0.25  # sixteenth note in quarter-note beats
MAX_NOTES = 4000
MAX_START = 10_000.0
MAX_DURATION = 32.0
PITCH_MIN = 0
PITCH_MAX = 127
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
TIME_SIG_RE = re.compile(r"^([1-9]|1[0-6])/(1|2|4|8|16)$")


class EditError(ValueError):
    """Invalid edited score payload."""


def snap_grid(value: float) -> float:
    if not isinstance(value, (int, float)) or value != value:  # NaN
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
        start = snap_grid(float(item.get("start", 0)))
        duration = snap_grid(float(item.get("duration", GRID)))
        if start < 0 or start > MAX_START:
            raise EditError("Note start is out of range.")
        if duration < GRID or duration > MAX_DURATION:
            raise EditError("Note duration is out of range.")
        velocity = _as_int(item.get("velocity", 64), field="velocity", lo=1, hi=127)
        track = _as_int(item.get("track", 0), field="track", lo=0, hi=3)
        notes.append(
            {
                "id": note_id,
                "pitch": pitch,
                "start": start,
                "duration": duration,
                "velocity": velocity,
                "track": track,
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
    return {
        "tempo_bpm": validate_tempo(body.get("tempo_bpm")),
        "time_signature": validate_time_signature(body.get("time_signature")),
        "notes": notes,
    }


def extract_from_musicxml(musicxml_text: str) -> dict:
    from music21 import converter

    if not musicxml_text or not str(musicxml_text).strip():
        raise EditError("Score is empty.")

    score = converter.parse(musicxml_text, format="musicxml")
    tempo_bpm = 120.0
    marks = list(score.flatten().getElementsByClass("MetronomeMark"))
    if marks and getattr(marks[0], "number", None):
        tempo_bpm = validate_tempo(marks[0].number)

    time_signature = "4/4"
    signatures = list(score.flatten().getTimeSignatures())
    if signatures and getattr(signatures[0], "ratioString", None):
        time_signature = validate_time_signature(signatures[0].ratioString)

    parts = list(score.parts)
    if not parts:
        parts = [score]

    notes: list[dict] = []
    index = 0
    for track, part in enumerate(parts[:4]):
        for element in part.recurse().notes:
            if getattr(element.duration, "isGrace", False):
                continue
            try:
                offset = float(element.getOffsetInHierarchy(score))
            except Exception:
                offset = float(element.offset)
            duration = float(element.quarterLength)
            if duration <= 0:
                continue
            velocity = 64
            volume = getattr(element, "volume", None)
            if volume is not None and volume.velocity:
                velocity = int(volume.velocity)
            pitches = (
                [int(pitch.midi) for pitch in element.pitches]
                if element.isChord
                else [int(element.pitch.midi)]
            )
            for pitch in pitches:
                notes.append(
                    {
                        "id": f"n-{index:04d}",
                        "pitch": max(PITCH_MIN, min(PITCH_MAX, pitch)),
                        "start": offset,
                        "duration": duration,
                        "velocity": max(1, min(127, velocity)),
                        "track": track,
                    }
                )
                index += 1
    return {
        "tempo_bpm": tempo_bpm,
        "time_signature": time_signature,
        "notes": validate_notes(notes),
    }


def build_musicxml_and_midi(payload: dict) -> tuple[str, bytes]:
    from music21 import clef, converter, instrument, meter, note, stream, tempo

    data = parse_edits_payload(payload)
    score = stream.Score()
    tracks: dict[int, list[dict]] = {}
    for item in data["notes"]:
        tracks.setdefault(item["track"], []).append(item)
    staff_indexes = sorted(tracks) or [0]
    if max(staff_indexes) >= 1 and 0 not in staff_indexes:
        staff_indexes = [0, *staff_indexes]

    for staff_index in staff_indexes:
        part = stream.Part(id=f"P{staff_index + 1}")
        part.partName = "Piano"
        part.insert(0, instrument.Piano())
        part.insert(0, tempo.MetronomeMark(number=data["tempo_bpm"]))
        part.insert(0, meter.TimeSignature(data["time_signature"]))
        part.insert(0, clef.TrebleClef() if staff_index == 0 else clef.BassClef())
        for item in tracks.get(staff_index, []):
            event = note.Note(item["pitch"])
            event.quarterLength = item["duration"]
            event.volume.velocity = item["velocity"]
            part.insert(item["start"], event)
        # makeNotation fills measures/rests/beams from the note list.
        # This is music21 engraving, not the transcription notation planner.
        if part.recurse().notes:
            part.makeNotation(inPlace=True)
        else:
            part.append(note.Rest(quarterLength=4.0))
            part.makeNotation(inPlace=True)
        score.insert(0, part)

    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "edited.musicxml"
        midi_path = Path(tmp) / "edited.mid"
        score.write("musicxml", fp=str(xml_path))
        score.write("midi", fp=str(midi_path))
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
