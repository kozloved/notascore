"""Isolated MusicXML swing metadata. music21 does not serialize <swing>."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from mir.swing import InterpretationSpan, indication_for_span

_MUSICXML_NS = "http://www.musicxml.org/ns/musicxml"


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _measure_number(elem: ET.Element) -> int | None:
    raw = elem.attrib.get("number")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _ensure_direction(measure: ET.Element, payload: ET.Element, *, offset_beats: float = 0.0) -> None:
    direction = ET.Element("direction")
    direction.set("placement", "above")
    dtype = ET.SubElement(direction, "direction-type")
    dtype.append(payload)
    if offset_beats > 1e-6:
        ET.SubElement(direction, "offset").text = str(int(round(offset_beats * 8)))
    staff = ET.SubElement(direction, "staff")
    staff.text = "1"
    # Insert after attributes when present so the marking leads the measure.
    insert_at = 0
    for index, child in enumerate(list(measure)):
        if _local(child.tag) == "attributes":
            insert_at = index + 1
    measure.insert(insert_at, direction)


def _swing_payload(span: InterpretationSpan) -> ET.Element:
    swing = ET.Element("swing")
    if span.feel == "straight" or span.ratio is None:
        ET.SubElement(swing, "straight")
        return swing
    first = ET.SubElement(swing, "first")
    second = ET.SubElement(swing, "second")
    ratio = float(span.ratio)
    # Represent r:1 as integers when close; otherwise tenths.
    if abs(ratio - round(ratio)) < 0.08:
        first.text = str(int(round(ratio)))
        second.text = "1"
    else:
        first.text = str(int(round(ratio * 10)))
        second.text = "10"
    style = ET.SubElement(swing, "swing-style")
    style.text = "standard"
    return swing


def inject_swing_metadata(
    xml: str,
    spans: list[InterpretationSpan] | list[dict] | None,
    *,
    measure_quarter_length: float = 4.0,
    pickup_shift: float = 0.0,
) -> str:
    """Add MusicXML 4 <swing> elements at span boundaries.

    Visible 'Swing' / 'Straight' words are inserted by the writer as
    TextExpression so OSMD can render them. This pass only adds machine
    metadata that music21 omits. Score MIDI playback does not read it.
    """
    if not xml or not spans:
        return xml
    parsed_spans: list[InterpretationSpan] = []
    for item in spans:
        if isinstance(item, InterpretationSpan):
            parsed_spans.append(item)
        elif isinstance(item, dict):
            parsed_spans.append(
                InterpretationSpan(
                    start_beat=float(item.get("start_beat") or 0.0),
                    end_beat=float(item.get("end_beat") or 0.0),
                    feel=str(item.get("feel") or "straight"),
                    subdivision_unit=float(item.get("subdivision_unit") or 0.5),
                    ratio=item.get("ratio"),
                    confidence=float(item.get("confidence") or 0.0),
                    evidence_count=int(item.get("evidence_count") or 0),
                    origin=str(item.get("origin") or "inferred"),
                )
            )
    markings = []
    previous = None
    for span in parsed_spans:
        label = indication_for_span(span, previous_feel=previous)
        previous = span.feel
        if label is None and span.feel not in {"swing_eighths", "swing_sixteenths", "shuffle"}:
            continue
        markings.append((span, label))
    if not markings:
        return xml
    # Preserve the original declaration; ElementTree may rewrite namespaces.
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return xml
    measures = [elem for elem in root.iter() if _local(elem.tag) == "measure"]
    if not measures:
        return xml
    mql = max(float(measure_quarter_length) or 4.0, 1e-6)
    used = set()
    for span, _label in markings:
        written = max(0.0, float(span.start_beat) - float(pickup_shift))
        number = int(written / mql) + 1
        local = written - (number - 1) * mql
        target = None
        for measure in measures:
            num = _measure_number(measure)
            if num == number:
                target = measure
                break
        if target is None:
            target = measures[min(max(number - 1, 0), len(measures) - 1)]
            number = _measure_number(target) or number
        key = (number, round(local, 3), span.feel)
        if key in used:
            continue
        used.add(key)
        _ensure_direction(target, _swing_payload(span), offset_beats=max(0.0, local))
    body = ET.tostring(root, encoding="unicode")
    match = re.match(r"^\s*<\?xml[^?]*\?>\s*", xml)
    header = match.group(0) if match else '<?xml version="1.0" encoding="utf-8"?>\n'
    if body.startswith("<?xml"):
        return body
    return header + body
