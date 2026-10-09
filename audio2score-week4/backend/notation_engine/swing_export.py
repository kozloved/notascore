"""Isolated MusicXML swing metadata. music21 does not serialize <swing>.

Correct MusicXML 4 placement::

    <direction>
      <direction-type><words>Swing</words></direction-type>
      <offset>DIVISIONS</offset>   <!-- inherited measure divisions -->
      <staff>1</staff>
      <sound>
        <swing>
          <first>2</first><second>1</second>
          <swing-type>eighth</swing-type>
          <swing-style>standard</swing-style>
        </swing>
      </sound>
    </direction>

Visible words belong in direction-type. Playback metadata belongs in
direction/sound/swing. This module never flattens measures across parts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import gcd
from typing import Any
from xml.etree import ElementTree as ET

from mir.swing import (
    LOCAL_EVEN_LABEL,
    InterpretationSpan,
    cluster_even_exceptions,
    indication_for_span,
    local_even_exceptions,
    simplest_ratio_parts,
    span_at,
    spans_from_payload,
)

_MUSICXML_NS = "http://www.musicxml.org/ns/musicxml"


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _measure_number(elem: ET.Element) -> str:
    return str(elem.attrib.get("number") or "")


def _child(elem: ET.Element, name: str) -> ET.Element | None:
    for child in list(elem):
        if _local(child.tag) == name:
            return child
    return None


def _children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(elem) if _local(child.tag) == name]


def _text(elem: ET.Element | None) -> str:
    if elem is None or elem.text is None:
        return ""
    return str(elem.text).strip()


@dataclass(frozen=True)
class PartMeasure:
    part_id: str
    index: int
    number: str
    element: ET.Element
    start_beat: float
    duration_beats: float
    divisions: int


def _time_signature_beats(attributes: ET.Element | None, fallback: float) -> float:
    if attributes is None:
        return fallback
    beats = _text(_child(attributes, "beats"))
    beat_type = _text(_child(attributes, "beat-type"))
    try:
        return float(beats) * (4.0 / float(beat_type))
    except (TypeError, ValueError):
        return fallback


def _measure_consumed_beats(measure: ET.Element, divisions: int) -> float:
    """Voice-aware duration of a measure from notes/backup/forward."""
    div = max(int(divisions or 1), 1)
    cursor = 0
    farthest = 0
    for child in list(measure):
        name = _local(child.tag)
        if name == "note":
            if _child(child, "chord") is not None:
                continue
            duration = _text(_child(child, "duration"))
            try:
                cursor += int(duration)
            except ValueError:
                continue
            farthest = max(farthest, cursor)
        elif name == "backup":
            duration = _text(_child(child, "duration"))
            try:
                cursor = max(0, cursor - int(duration))
            except ValueError:
                continue
        elif name == "forward":
            duration = _text(_child(child, "duration"))
            try:
                cursor += int(duration)
            except ValueError:
                continue
            farthest = max(farthest, cursor)
    return farthest / float(div)


def iter_part_measures(
    root: ET.Element,
    *,
    plan_measures: list[dict] | None = None,
) -> list[PartMeasure]:
    """Build a per-part measure timeline. Never flatten parts together."""
    out: list[PartMeasure] = []
    planned = list(plan_measures or ())
    for part in [elem for elem in root if _local(elem.tag) == "part"]:
        part_id = str(part.attrib.get("id") or "")
        divisions = 1
        nominal = 4.0
        cursor = 0.0
        index = 0
        for measure in [elem for elem in part if _local(elem.tag) == "measure"]:
            attributes = _child(measure, "attributes")
            if attributes is not None:
                raw_div = _text(_child(attributes, "divisions"))
                if raw_div.isdigit():
                    divisions = max(int(raw_div), 1)
                nominal = _time_signature_beats(attributes, nominal)
            consumed = _measure_consumed_beats(measure, divisions)
            if index < len(planned):
                start = float(planned[index].get("start_beat") or cursor)
                duration = float(planned[index].get("duration_beats") or consumed or nominal)
            else:
                start = cursor
                duration = consumed if consumed > 1e-9 else nominal
            out.append(
                PartMeasure(
                    part_id=part_id,
                    index=index,
                    number=_measure_number(measure),
                    element=measure,
                    start_beat=start,
                    duration_beats=max(duration, 1e-6),
                    divisions=divisions,
                )
            )
            cursor = start + max(duration, 1e-6)
            index += 1
    return out


def _swing_type(span: InterpretationSpan) -> str:
    if span.feel == "swing_sixteenths" or float(span.subdivision_unit) <= 0.26:
        return "16th"
    return "eighth"


def _swing_element(span: InterpretationSpan) -> ET.Element:
    swing = ET.Element("swing")
    if span.feel == "straight" or span.ratio is None:
        ET.SubElement(swing, "straight")
        return swing
    first_n, second_n = simplest_ratio_parts(float(span.ratio))
    first = ET.SubElement(swing, "first")
    second = ET.SubElement(swing, "second")
    first.text = str(first_n)
    second.text = str(second_n)
    swing_type = ET.SubElement(swing, "swing-type")
    swing_type.text = _swing_type(span)
    style = ET.SubElement(swing, "swing-style")
    style.text = "standard"
    return swing


def _words_text(direction: ET.Element) -> str:
    for dtype in _children(direction, "direction-type"):
        words = _child(dtype, "words")
        if words is not None:
            return _text(words)
    return ""


def _direction_offset_div(direction: ET.Element) -> int:
    offset = _child(direction, "offset")
    raw = _text(offset)
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def _has_metronome(direction: ET.Element) -> bool:
    for dtype in _children(direction, "direction-type"):
        if _child(dtype, "metronome") is not None:
            return True
    return False


def _ensure_sound_swing(direction: ET.Element, span: InterpretationSpan) -> None:
    sound = _child(direction, "sound")
    if sound is None:
        sound = ET.SubElement(direction, "sound")
    existing = _child(sound, "swing")
    if existing is not None:
        sound.remove(existing)
    sound.append(_swing_element(span))


def _ensure_words(direction: ET.Element, label: str, *, beside_metronome: bool) -> None:
    existing = None
    for dtype in _children(direction, "direction-type"):
        words = _child(dtype, "words")
        if words is not None:
            existing = words
            break
    if existing is None:
        dtype = ET.Element("direction-type")
        existing = ET.SubElement(dtype, "words")
        insert_at = len(list(direction))
        staff = _child(direction, "staff")
        sound = _child(direction, "sound")
        offset = _child(direction, "offset")
        for index, child in enumerate(list(direction)):
            if child is staff or child is sound or child is offset:
                insert_at = index
                break
        direction.insert(insert_at, dtype)
    existing.text = label
    if beside_metronome:
        # Sit to the right of ♩= n so OSMD does not stack Swing on the tempo.
        existing.set("relative-x", "80")
        existing.set("default-y", "18")
    else:
        existing.attrib.pop("relative-x", None)
        existing.attrib.pop("default-y", None)


def _remove_duplicate_words_directions(
    measure: PartMeasure, *, offset_div: int, label: str
) -> None:
    kept_metronome = False
    for direction in list(_children(measure.element, "direction")):
        if _direction_offset_div(direction) != offset_div:
            continue
        if _has_metronome(direction):
            kept_metronome = True
            continue
        words = _words_text(direction)
        if label and words == label:
            measure.element.remove(direction)
    del kept_metronome


def _insert_direction(
    measure: PartMeasure,
    span: InterpretationSpan,
    label: str | None,
    *,
    local_beats: float,
) -> None:
    offset_div = int(round(max(0.0, local_beats) * measure.divisions))
    metronome = None
    for direction in _children(measure.element, "direction"):
        if _has_metronome(direction) and _direction_offset_div(direction) == offset_div:
            metronome = direction
            break
    if metronome is not None and label:
        _ensure_words(metronome, label, beside_metronome=True)
        _ensure_sound_swing(metronome, span)
        _remove_duplicate_words_directions(measure, offset_div=offset_div, label=label)
        return
    for direction in _children(measure.element, "direction"):
        words = _words_text(direction)
        if label and words == label and _direction_offset_div(direction) == offset_div:
            _ensure_sound_swing(direction, span)
            return
    direction = ET.Element("direction")
    direction.set("placement", "above")
    dtype = ET.SubElement(direction, "direction-type")
    if label:
        words = ET.SubElement(dtype, "words")
        words.text = label
    else:
        # Machine-only change (restore swing after a local even, or continue
        # after a pickup). Keep a direction-type so the element stays schema-shaped.
        words = ET.SubElement(dtype, "words")
        words.text = ""
    if offset_div > 0:
        offset = ET.SubElement(direction, "offset")
        offset.text = str(offset_div)
    staff = ET.SubElement(direction, "staff")
    staff.text = "1"
    sound = ET.SubElement(direction, "sound")
    sound.append(_swing_element(span))
    insert_at = 0
    for index, child in enumerate(list(measure.element)):
        if _local(child.tag) == "attributes":
            insert_at = index + 1
            continue
        if _local(child.tag) == "direction" and _has_metronome(child):
            insert_at = index + 1
    measure.element.insert(insert_at, direction)


def _even_restore_span(enclosing: InterpretationSpan, start_beat: float) -> InterpretationSpan:
    return InterpretationSpan(
        start_beat=float(start_beat),
        end_beat=float(enclosing.end_beat),
        feel=enclosing.feel,
        subdivision_unit=enclosing.subdivision_unit,
        ratio=enclosing.ratio,
        confidence=enclosing.confidence,
        evidence_count=enclosing.evidence_count,
        origin="local_even_restore",
        triplet_exceptions=enclosing.triplet_exceptions,
        unmapped_streams=enclosing.unmapped_streams,
        maps_written_timing=enclosing.maps_written_timing,
    )


def _even_span(start_beat: float, end_beat: float) -> InterpretationSpan:
    return InterpretationSpan(
        start_beat=float(start_beat),
        end_beat=float(end_beat),
        feel="straight",
        subdivision_unit=0.5,
        ratio=None,
        confidence=1.0,
        evidence_count=1,
        origin="local_even",
        maps_written_timing=False,
    )


def inject_swing_metadata(
    xml: str,
    spans: list[InterpretationSpan] | list[dict] | None,
    *,
    measure_quarter_length: float = 4.0,
    pickup_shift: float = 0.0,
    measure_map: list[dict] | None = None,
    events=None,
) -> str:
    """Add MusicXML 4 <sound><swing> at span boundaries, per part.

    Local even exceptions (performed straight inside a swing span) are printed
    as ``even`` plus ``<swing><straight/>``. Swing is restored after the figure
    with a machine-only sound node so OSMD does not print a second Swing.
    """
    del measure_quarter_length, pickup_shift
    if not xml or not spans:
        return xml
    parsed_spans = spans_from_payload(spans)
    markings = []
    previous = None
    for span in parsed_spans:
        label = indication_for_span(span, previous_feel=previous)
        previous = span.feel
        if label is None:
            continue
        if span.feel in {"swing_eighths", "swing_sixteenths", "shuffle"} and not span.maps_written_timing:
            continue
        markings.append((span, label))
    for start, end in cluster_even_exceptions(local_even_exceptions(events or (), parsed_spans)):
        enclosing = span_at(parsed_spans, start)
        markings.append((_even_span(start, end), LOCAL_EVEN_LABEL))
        if enclosing is not None and enclosing.feel in {"swing_eighths", "swing_sixteenths", "shuffle"}:
            markings.append((_even_restore_span(enclosing, end), ""))
    if not markings:
        return xml
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return xml
    part_measures = iter_part_measures(root, plan_measures=measure_map)
    if not part_measures:
        return xml
    by_part: dict[str, list[PartMeasure]] = {}
    for row in part_measures:
        by_part.setdefault(row.part_id, []).append(row)
    markings.sort(key=lambda item: (float(item[0].start_beat), 0 if item[1] else 1))
    used: set[tuple] = set()
    for span, label in markings:
        start = float(span.start_beat)
        for part_id, measures in by_part.items():
            target = None
            for meas in measures:
                if meas.start_beat - 1e-9 <= start < meas.start_beat + meas.duration_beats - 1e-9:
                    target = meas
                    break
            if target is None and measures:
                # Closing boundary of the last measure.
                last = measures[-1]
                if abs(start - (last.start_beat + last.duration_beats)) <= 1e-6:
                    target = last
            if target is None:
                continue
            local = max(0.0, start - target.start_beat)
            key = (part_id, target.index, round(local, 4), span.feel)
            if key in used:
                continue
            used.add(key)
            _insert_direction(target, span, label, local_beats=local)
    body = ET.tostring(root, encoding="unicode")
    match = re.match(r"^\s*<\?xml[^?]*\?>\s*", xml)
    header = match.group(0) if match else '<?xml version="1.0" encoding="utf-8"?>\n'
    if body.startswith("<?xml"):
        return body
    return header + body


def swing_sound_nodes(xml: str) -> list[dict[str, Any]]:
    """Exact placement of swing metadata. Substring search is not enough."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    found = []
    for part in [elem for elem in root if _local(elem.tag) == "part"]:
        part_id = str(part.attrib.get("id") or "")
        for measure in [elem for elem in part if _local(elem.tag) == "measure"]:
            for direction in _children(measure, "direction"):
                sound = _child(direction, "sound")
                if sound is None:
                    continue
                swing = _child(sound, "swing")
                if swing is None:
                    continue
                dtype = _child(direction, "direction-type")
                words = _child(dtype, "words") if dtype is not None else None
                parent_sound = _local(sound.tag)
                parent_dir = _local(direction.tag)
                first = _text(_child(swing, "first"))
                second = _text(_child(swing, "second"))
                found.append(
                    {
                        "part_id": part_id,
                        "measure_number": _measure_number(measure),
                        "direction_parent": parent_dir,
                        "sound_parent": parent_sound,
                        "swing_parent": _local(sound.tag),
                        "words": _text(words),
                        "words_in_direction_type": words is not None and dtype is not None,
                        "swing_in_sound": True,
                        "sound_in_direction": True,
                        "straight": _child(swing, "straight") is not None,
                        "first": first,
                        "second": second,
                        "swing_type": _text(_child(swing, "swing-type")),
                        "swing_style": _text(_child(swing, "swing-style")),
                        "offset": _text(_child(direction, "offset")),
                    }
                )
    return found


def assert_swing_metadata_placement(xml: str) -> list[dict]:
    """Raise if <swing> is anywhere except direction/sound/swing."""
    nodes = swing_sound_nodes(xml)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise AssertionError(f"MusicXML is not well-formed: {exc}") from exc
    for elem in root.iter():
        if _local(elem.tag) != "swing":
            continue
        parent_ok = False
        for sound in root.iter():
            if _local(sound.tag) != "sound":
                continue
            if any(child is elem for child in list(sound)):
                grand = None
                for direction in root.iter():
                    if _local(direction.tag) == "direction" and any(
                        child is sound for child in list(direction)
                    ):
                        grand = direction
                        break
                parent_ok = grand is not None
                break
        if not parent_ok:
            raise AssertionError("Swing metadata must live in direction/sound/swing")
    for node in nodes:
        if not node["swing_in_sound"] or not node["sound_in_direction"]:
            raise AssertionError(f"Swing node is misplaced: {node}")
        if node["first"] and node["second"]:
            a, b = int(node["first"]), int(node["second"])
            if gcd(a, b) != 1:
                raise AssertionError(f"Swing ratio {a}:{b} is not in simplest form")
        if node["swing_type"] and node["swing_type"] not in {"eighth", "16th"}:
            raise AssertionError(f"Invalid swing-type {node['swing_type']!r}")
        dtype_parent_ok = node["words_in_direction_type"] or node["words"] == ""
        if node["words"] and not dtype_parent_ok:
            raise AssertionError("Visible swing words must live in direction-type")
    return nodes


def spans_from_musicxml(xml: str) -> list[InterpretationSpan]:
    """Read sound/swing, including local even/straight, back from MusicXML.

    Recoverable: sectional Swing/Straight words, ``<swing>`` ratios, local
    ``even`` plus ``<straight/>``, and machine-only restore-swing nodes.
    Not recoverable: performed_* timestamps, stream_key, triplet-exception
    owners, or unmarked local exceptions. Those need the editor/score model.
    """
    nodes = swing_sound_nodes(xml)
    if not nodes:
        return []
    spans = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    measures = iter_part_measures(root)
    first_part = next(iter({row.part_id: None for row in measures}), None)
    part_rows = [row for row in measures if row.part_id == first_part]
    for node in nodes:
        if node["part_id"] != first_part:
            continue
        target = next((row for row in part_rows if row.number == node["measure_number"]), None)
        if target is None:
            continue
        local = 0.0
        if node["offset"]:
            try:
                local = int(node["offset"]) / float(target.divisions or 1)
            except ValueError:
                local = 0.0
        start = target.start_beat + max(0.0, local)
        if node["straight"]:
            feel = "straight"
            ratio = None
            unit = 0.5
        else:
            try:
                first_n = int(node["first"] or "2")
                second_n = int(node["second"] or "1")
                ratio = first_n / max(second_n, 1)
            except ValueError:
                ratio = 2.0
            feel = "swing_sixteenths" if node["swing_type"] == "16th" else "swing_eighths"
            unit = 0.25 if feel == "swing_sixteenths" else 0.5
        spans.append(
            InterpretationSpan(
                start_beat=start,
                end_beat=target.start_beat + target.duration_beats,
                feel=feel,
                subdivision_unit=unit,
                ratio=ratio,
                confidence=1.0,
                evidence_count=1,
                origin="musicxml",
                maps_written_timing=feel != "straight",
            )
        )
    if not spans:
        return []
    spans.sort(key=lambda span: (span.start_beat, span.end_beat))
    # Extend each span to the next marking / piece end.
    for index, span in enumerate(spans):
        end = part_rows[-1].start_beat + part_rows[-1].duration_beats if part_rows else span.end_beat
        if index + 1 < len(spans):
            end = spans[index + 1].start_beat
        if end <= span.start_beat:
            end = span.start_beat + 1e-4
        spans[index] = InterpretationSpan(
            start_beat=span.start_beat,
            end_beat=end,
            feel=span.feel,
            subdivision_unit=span.subdivision_unit,
            ratio=span.ratio,
            confidence=span.confidence,
            evidence_count=span.evidence_count,
            origin=span.origin,
            maps_written_timing=span.maps_written_timing,
        )
    return spans
