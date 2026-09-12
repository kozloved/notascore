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
MAX_TEMPO_CURVE = 8192
MAX_START = 10_000.0
MAX_DURATION = 32.0
PITCH_MIN = 0
PITCH_MAX = 127
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
TIME_SIG_RE = re.compile(r"^([1-9]|1[0-6])/(1|2|4|8|16)$")
XML_ID_PREFIX = "nsid_"
PROVENANCE_PERFORMANCE = "performance"
PROVENANCE_MUSICXML_DEGRADED = "musicxml_degraded"


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
        start_sec = item.get("start_sec")
        end_sec = item.get("end_sec")
        if start_sec is not None:
            start_sec = float(start_sec)
            if not isfinite(start_sec) or start_sec < 0:
                raise EditError("Note start_sec is out of range.")
        if end_sec is not None:
            end_sec = float(end_sec)
            if not isfinite(end_sec) or (start_sec is not None and end_sec <= start_sec):
                raise EditError("Note end_sec is out of range.")
        notes.append(
            {
                "id": note_id,
                "source_note_id": validate_source_note_id(item.get("source_note_id")),
                "pitch": pitch,
                "start": start,
                "duration": duration,
                "velocity": velocity,
                "track": track,
                "voice": validate_voice(item.get("voice", 0)),
                "start_sec": start_sec,
                "end_sec": end_sec,
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
    printed = body.get("printed_tempo_marks")
    if printed is None:
        printed_marks = []
    elif not isinstance(printed, list):
        raise EditError("printed_tempo_marks must be a list.")
    else:
        printed_marks = []
        for item in printed:
            if not isinstance(item, dict):
                raise EditError("Each printed tempo mark must be an object.")
            printed_marks.append(
                {
                    "beat": float(item.get("beat", 0)),
                    "bpm": item.get("bpm"),
                    "mark": str(item.get("mark") or "metronome"),
                    "reason": str(item.get("reason") or ""),
                }
            )
    provenance = str(body.get("provenance") or "").strip() or None
    return {
        "tempo_bpm": tempo_bpm,
        "time_signature": validate_time_signature(body.get("time_signature")),
        "tempo_curve": validate_tempo_curve(body.get("tempo_curve"), fallback_bpm=tempo_bpm),
        "printed_tempo_marks": printed_marks,
        "provenance": provenance,
        "notes": notes,
    }


def encode_source_xml_id(source_note_id: str | None, note_id: str) -> str:
    import base64

    raw = (source_note_id or note_id).encode("utf-8")
    packed = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"{XML_ID_PREFIX}{packed}"


def decode_source_xml_id(xml_id: str | None) -> str | None:
    if not xml_id:
        return None
    text = str(xml_id).strip()
    if not text.startswith(XML_ID_PREFIX):
        return None
    import base64

    packed = text[len(XML_ID_PREFIX) :]
    pad = "=" * (-len(packed) % 4)
    try:
        raw = base64.urlsafe_b64decode(packed + pad).decode("utf-8")
    except Exception:
        return None
    return raw if ID_RE.match(raw) else None


def assign_overlap_voices(notes: list[dict]) -> list[dict]:
    """Give overlapping same-staff notes distinct per-measure voice lanes."""
    ordered = sorted(notes, key=lambda n: (n["track"], n["start"], n["pitch"], n["id"]))
    assigned: list[dict] = []
    for note in ordered:
        used = set()
        start = float(note["start"])
        end = start + float(note["duration"])
        for other in assigned:
            if other["track"] != note["track"]:
                continue
            other_end = float(other["start"]) + float(other["duration"])
            if start < other_end - 1e-9 and float(other["start"]) < end - 1e-9:
                used.add(int(other["voice"]))
        voice = int(note.get("voice") or 0)
        if voice in used:
            voice = 0
            while voice in used and voice < 15:
                voice += 1
        item = dict(note)
        item["voice"] = voice
        assigned.append(item)
    return assigned


def curve_from_time_map(time_map, *, fallback_bpm: float = 120.0) -> list[dict]:
    points: list[dict] = []
    exact = getattr(time_map, "exact_points", ()) or ()
    if exact:
        for _time_sec, beat, bpm in exact:
            points.append({"beat": max(0.0, float(beat)), "bpm": validate_tempo(bpm)})
    else:
        for beat, bpm in time_map.interval_bpms():
            points.append({"beat": max(0.0, float(beat)), "bpm": validate_tempo(bpm)})
    if not points:
        points = [{"beat": 0.0, "bpm": float(fallback_bpm)}]
    return validate_tempo_curve(points, fallback_bpm=fallback_bpm)


def time_map_from_tempo_payload(payload: dict):
    from timing.tempo_map import MusicalTimeMap

    if not isinstance(payload, dict):
        raise EditError("Tempo map is invalid.")
    performance = payload.get("performance") if isinstance(payload.get("performance"), dict) else {}
    times = performance.get("beat_times") or payload.get("beat_times") or []
    exact_raw = payload.get("exact_points") or []
    exact = []
    for item in exact_raw:
        if isinstance(item, dict):
            exact.append(
                (float(item["time_sec"]), float(item["beat"]), float(item["bpm"]))
            )
        else:
            exact.append((float(item[0]), float(item[1]), float(item[2])))
    try:
        time_map = MusicalTimeMap.from_beat_times(
            times, source=str(payload.get("source") or "tempo_json")
        )
    except Exception:
        duration = 4.0
        if times:
            try:
                duration = max(float(times[-1]), 4.0)
            except (TypeError, ValueError):
                duration = 4.0
        time_map = MusicalTimeMap.from_bpm(120.0, duration_sec=duration)
    if exact:
        return MusicalTimeMap(
            time_map.beat_times, source=time_map.source, exact_points=tuple(exact)
        )
    return time_map


def extract_from_performance(snapshot, time_map, *, printed_marks=None, time_signature: str = "4/4") -> dict:
    """Editor model from acoustic notes + the full seconds-to-beats map."""
    notes_sec = [n for n in snapshot.notes if not getattr(n, "is_drum", False)]
    if not notes_sec:
        raise EditError("Score is empty.")
    earliest = min(time_map.seconds_to_beats(n.start_sec) for n in notes_sec)
    from math import ceil

    shift = max(0.0, -earliest) if earliest >= -0.04 else float(ceil(-earliest))
    notes: list[dict] = []
    for index, source in enumerate(notes_sec):
        start_beat = time_map.seconds_to_beats(source.start_sec) + shift
        end_beat = time_map.seconds_to_beats(source.end_sec) + shift
        duration = max(end_beat - start_beat, 1e-6)
        hand = str(getattr(source, "hand_hint", "") or "")
        track = 1 if hand == "left" else 0
        track_id = str(getattr(source, "track_id", "") or "")
        if track_id.startswith("track:"):
            try:
                track = min(3, max(0, int(track_id.split(":")[1])))
            except (IndexError, ValueError):
                pass
        note_id = str(source.note_id or f"n-{index:04d}")
        notes.append(
            {
                "id": note_id if ID_RE.match(note_id) else f"n-{index:04d}",
                "source_note_id": source.note_id if ID_RE.match(str(source.note_id or "")) else None,
                "pitch": max(PITCH_MIN, min(PITCH_MAX, int(source.pitch))),
                "start": max(0.0, float(start_beat)),
                "duration": min(MAX_DURATION, max(1e-6, float(duration))),
                "velocity": max(1, min(127, int(source.velocity))),
                "track": track,
                "voice": 0,
                "start_sec": float(source.start_sec),
                "end_sec": float(source.end_sec),
            }
        )
    notes = assign_overlap_voices(notes)
    series = time_map.interval_bpms()
    tempo_bpm = validate_tempo(series[0][1] if series else 120.0)
    printed = []
    for mark in printed_marks or []:
        if hasattr(mark, "beat"):
            printed.append(
                {
                    "beat": float(mark.beat),
                    "bpm": mark.bpm,
                    "mark": str(mark.mark),
                    "reason": str(mark.reason),
                }
            )
        elif isinstance(mark, dict):
            printed.append(
                {
                    "beat": float(mark.get("beat", 0)),
                    "bpm": mark.get("bpm"),
                    "mark": str(mark.get("mark") or "metronome"),
                    "reason": str(mark.get("reason") or ""),
                }
            )
    return {
        "tempo_bpm": tempo_bpm,
        "time_signature": validate_time_signature(time_signature),
        "tempo_curve": curve_from_time_map(time_map, fallback_bpm=tempo_bpm),
        "printed_tempo_marks": printed,
        "provenance": PROVENANCE_PERFORMANCE,
        "notes": validate_notes(notes),
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
        source_id = None
        notes.append(
            {
                "id": note_id,
                "source_note_id": source_id,
                "pitch": max(PITCH_MIN, min(PITCH_MAX, attack.pitch)),
                "start": attack.start,
                "duration": attack.end - attack.start,
                "velocity": max(1, min(127, attack.velocity)),
                "track": attack.track,
                "voice": validate_voice(voice),
                "start_sec": None,
                "end_sec": None,
            }
        )
    # Restore identities written as xml:id when the XML came from this editor.
    identity_by_key: dict[tuple, str] = {}
    voice_by_key: dict[tuple, int] = {}
    for part_index, part in enumerate(score.parts):
        for measure in part.getElementsByClass("Measure"):
            for element in measure.recurse().notes:
                onset = float(element.getOffsetInHierarchy(part))
                members = list(element.notes) if element.isChord else [element]
                for member in members:
                    decoded = _source_id_from_element(member)
                    key = (part_index, member.pitch.midi, round(onset, 6))
                    if decoded:
                        identity_by_key[key] = decoded
                    stored_voice = _voice_from_element(member)
                    if stored_voice is not None:
                        voice_by_key[key] = stored_voice
    used: set[str] = set()
    for item in notes:
        decoded = identity_by_key.get((item["track"], item["pitch"], round(item["start"], 6)))
        if not decoded:
            nearest = None
            nearest_dist = 0.08
            for (track, pitch, onset), source in identity_by_key.items():
                if track != item["track"] or pitch != item["pitch"] or source in used:
                    continue
                dist = abs(onset - item["start"])
                if dist < nearest_dist:
                    nearest = source
                    nearest_dist = dist
            decoded = nearest
        if decoded:
            used.add(decoded)
            item["source_note_id"] = decoded
            if ID_RE.match(decoded):
                item["id"] = decoded
        voice = voice_by_key.get((item["track"], item["pitch"], round(item["start"], 6)))
        if voice is None and decoded:
            for (track, pitch, onset), source in identity_by_key.items():
                if source == decoded:
                    voice = voice_by_key.get((track, pitch, onset))
                    break
        if voice is not None:
            item["voice"] = voice
    provenance = (
        PROVENANCE_PERFORMANCE
        if any(item["source_note_id"] for item in notes)
        else PROVENANCE_MUSICXML_DEGRADED
    )
    return {
        "tempo_bpm": tempo_bpm,
        "time_signature": time_signature,
        "tempo_curve": validate_tempo_curve(tempo_curve, fallback_bpm=tempo_bpm),
        "printed_tempo_marks": [
            {"beat": point["beat"], "bpm": point["bpm"], "mark": "metronome", "reason": "printed_xml"}
            for point in tempo_curve
        ],
        "provenance": provenance,
        "notes": validate_notes(notes),
    }


def _attach_source_identity(event, source_note_id: str | None, note_id: str, voice: int = 0) -> None:
    from music21 import note as m21note

    xml_id = encode_source_xml_id(source_note_id, note_id)
    event.id = xml_id
    identity = m21note.Lyric(text=xml_id, number=99)
    identity.style.hideObjectOnPrint = True
    event.lyrics.append(identity)
    voice_text = str(int(voice or 0))
    voice_lyric = m21note.Lyric(text=voice_text, number=98)
    voice_lyric.style.hideObjectOnPrint = True
    event.lyrics.append(voice_lyric)
    editorial = getattr(event, "editorial", None)
    if editorial is None:
        return
    misc = getattr(editorial, "misc", None)
    payload = {"source_note_id": source_note_id, "note_id": note_id}
    if misc is None:
        editorial.misc = payload
    elif isinstance(misc, dict):
        misc.update(payload)


def _voice_from_element(element) -> int | None:
    for lyric in getattr(element, "lyrics", None) or []:
        if int(getattr(lyric, "number", 0) or 0) == 98:
            try:
                return validate_voice(lyric.text)
            except Exception:
                return None
    return None


def _source_id_from_element(element) -> str | None:
    for lyric in getattr(element, "lyrics", None) or []:
        if int(getattr(lyric, "number", 0) or 0) == 99:
            decoded = decode_source_xml_id(getattr(lyric, "text", None))
            if decoded:
                return decoded
    return decode_source_xml_id(getattr(element, "id", None))


def expressible_quarter_length(value: float) -> float:
    from music21 import duration as m21dur

    raw = float(value)
    try:
        written = m21dur.Duration(raw)
        too_short = {"2048th", "1024th", "512th", "256th"}
        if written.type != "inexpressible" and written.type not in too_short:
            return float(written.quarterLength)
    except Exception:
        pass
    grid = 1.0 / 64.0
    snapped = round(raw / grid) * grid
    return max(grid, snapped)


def _expressible_offset(value: float) -> float:
    raw = float(value)
    if raw <= 1e-9:
        return 0.0
    from music21 import duration as m21dur

    try:
        written = m21dur.Duration(raw)
        too_short = {"2048th", "1024th", "512th", "256th"}
        if written.type != "inexpressible" and written.type not in too_short:
            return float(written.quarterLength)
    except Exception:
        pass
    grid = 0.25
    return max(0.0, round(raw / grid) * grid)


def _scrub_inexpressible_durations(part) -> None:
    from music21 import note as m21note

    forbidden = {"inexpressible", "2048th", "1024th", "512th", "256th"}
    for element in list(part.recurse().notesAndRests):
        duration_type = getattr(element.duration, "type", "")
        component_types = {
            getattr(component, "type", "")
            for component in getattr(element.duration, "components", []) or []
        }
        bad = duration_type in forbidden or bool(component_types & forbidden)
        if not bad:
            continue
        site = element.activeSite
        if isinstance(element, m21note.Rest):
            if site is not None:
                site.remove(element)
            continue
        element.quarterLength = max(0.25, round(float(element.quarterLength) / 0.25) * 0.25)


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
    from notation_engine.playback import playback_score

    events = [
        MusicalEvent(
            n["pitch"],
            n["start"],
            n["duration"],
            velocity=n["velocity"],
            note_id=n.get("source_note_id") or n["id"],
            voice=int(n.get("voice") or 0),
            source_track_id=str(n["track"]),
            start_time_sec=n.get("start_sec"),
            end_time_sec=n.get("end_sec"),
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
    printed = data.get("printed_tempo_marks") or []
    if data.get("provenance") == PROVENANCE_PERFORMANCE and printed:
        xml_curve = [
            {"beat": float(mark["beat"]), "bpm": validate_tempo(mark.get("bpm") or data["tempo_bpm"])}
            for mark in printed
            if mark.get("bpm") is not None
        ] or [{"beat": 0.0, "bpm": data["tempo_bpm"]}]
    elif len(curve) <= 12:
        xml_curve = curve
    else:
        xml_curve = [{"beat": 0.0, "bpm": data["tempo_bpm"]}]
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
            event.quarterLength = expressible_quarter_length(item["duration"])
            event.volume.velocity = item["velocity"]
            _attach_source_identity(
                event, item.get("source_note_id"), item["id"], int(item.get("voice") or 0)
            )
            part.insert(0.0 if not item["start"] else _expressible_offset(item["start"]), event)
        # makeNotation fills measures/rests/beams from the note list.
        # This is music21 engraving, not the transcription notation planner.
        # Do not wrap the whole part in Voice: makeNotation drops those streams.
        if part.recurse().notes:
            part.makeNotation(inPlace=True)
        else:
            if not list(part.recurse().getElementsByClass("Rest")):
                part.append(note.Rest(quarterLength=4.0))
            part.makeNotation(inPlace=True)
        _scrub_inexpressible_durations(part)
        _apply_tempo_curve(part, xml_curve)
        score.insert(0, part)

    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "edited.musicxml"
        midi_path = Path(tmp) / "edited.mid"
        try:
            score.write("musicxml", fp=str(xml_path))
        except Exception as exc:
            from music21.musicxml.xmlObjects import MusicXMLExportException

            if not isinstance(exc, MusicXMLExportException):
                raise
            for element in score.recurse().notesAndRests:
                quarter = float(element.quarterLength or 0)
                element.quarterLength = max(0.25, round(quarter / 0.25) * 0.25) if quarter else 0.25
            score.write("musicxml", fp=str(xml_path))
        tempo_points = [(float(point["beat"]), float(point["bpm"])) for point in data["tempo_curve"]]
        seconds_midi = _midi_bytes_from_seconds(data)
        if seconds_midi is not None:
            midi_path.write_bytes(seconds_midi)
            _validate_editor_exports(xml_path, midi_path, events, seconds_notes=data["notes"])
        else:
            playback = playback_score(events, data["time_signature"], tempo_points)
            playback.write("midi", fp=str(midi_path))
            _validate_editor_exports(xml_path, midi_path, events)
        xml_text = xml_path.read_text(encoding="utf-8")
        midi_bytes = midi_path.read_bytes()

    # Confirm the written MusicXML still parses.
    converter.parse(xml_text, format="musicxml")
    return xml_text, midi_bytes


def _midi_bytes_from_seconds(data: dict) -> bytes | None:
    notes = data.get("notes") or []
    if not notes or any(note.get("start_sec") is None or note.get("end_sec") is None for note in notes):
        return None
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=float(data.get("tempo_bpm") or 120))
    instruments: dict[int, pretty_midi.Instrument] = {}
    for item in notes:
        inst = instruments.setdefault(
            int(item.get("track") or 0), pretty_midi.Instrument(program=0)
        )
        inst.notes.append(
            pretty_midi.Note(
                velocity=int(item["velocity"]),
                pitch=int(item["pitch"]),
                start=float(item["start_sec"]),
                end=float(item["end_sec"]),
            )
        )
    midi.instruments.extend(instruments[key] for key in sorted(instruments))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "edited.mid"
        midi.write(str(path))
        return path.read_bytes()


def _validate_editor_exports(xml_path: Path, midi_path: Path, events, *, seconds_notes=None) -> None:
    """MIDI must keep source attacks; engraved XML may snap inexpressible durations."""
    from collections import Counter

    import mido
    from notation_engine.integrity import NotationIntegrityError, musicxml_attacks

    xml = musicxml_attacks(xml_path)
    if Counter(attack[0] for attack in xml) != Counter(event.pitch for event in events):
        raise NotationIntegrityError("MusicXML added, removed, or changed pitched attacks")
    if seconds_notes is not None:
        import pretty_midi

        midi = pretty_midi.PrettyMIDI(str(midi_path))
        actual = sorted(
            (int(note.pitch), float(note.start), float(note.end))
            for inst in midi.instruments
            for note in inst.notes
        )
        expected = sorted(
            (int(note["pitch"]), float(note["start_sec"]), float(note["end_sec"]))
            for note in seconds_notes
        )
        if [row[0] for row in actual] != [row[0] for row in expected]:
            raise NotationIntegrityError("MIDI added, removed, or changed pitched attacks")
        for got, want in zip(actual, expected):
            if abs(got[1] - want[1]) > 2e-3 or abs(got[2] - want[2]) > 2e-3:
                raise NotationIntegrityError(f"MIDI changed attack timing for pitch {want[0]}")
        return

    midi = mido.MidiFile(str(midi_path))
    attacks = []
    for track in midi.tracks:
        tick = 0
        active = {}
        for message in track:
            tick += message.time
            if message.type == "note_on" and message.velocity > 0:
                key = (message.channel, message.note)
                if key in active:
                    raise NotationIntegrityError("MIDI contains overlapping unison attacks in one lane")
                active[key] = tick / midi.ticks_per_beat
            elif message.type == "note_off" or (message.type == "note_on" and message.velocity == 0):
                key = (message.channel, message.note)
                if key not in active:
                    raise NotationIntegrityError("MIDI contains an unmatched note-off")
                attacks.append((message.note, active.pop(key), tick / midi.ticks_per_beat))
        if active:
            raise NotationIntegrityError("MIDI contains unmatched note-on messages")
    expected = [(event.pitch, event.start_beat, event.start_beat + event.duration_beats) for event in events]
    wanted, found = {}, {}
    for pitch, start, end in expected:
        wanted.setdefault(pitch, []).append((start, end))
    for pitch, start, end in attacks:
        found.setdefault(pitch, []).append((start, end))
    if {pitch: len(rows) for pitch, rows in wanted.items()} != {pitch: len(rows) for pitch, rows in found.items()}:
        raise NotationIntegrityError("MIDI added, removed, or changed pitched attacks")
    tolerance = 1 / midi.ticks_per_beat + 1e-9
    for pitch, rows in wanted.items():
        for left, right in zip(sorted(rows), sorted(found[pitch])):
            if any(abs(a - b) > tolerance for a, b in zip(left, right)):
                raise NotationIntegrityError(f"MIDI changed attack timing for pitch {pitch}")


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
