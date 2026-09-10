"""Exact score-to-notation lowering for the performance engine."""

from collections import defaultdict
from fractions import Fraction

from mir.models import PlannedMeasure, PlannedNote, PlannedRest, PlannedStaff, PlannedVoice, PlannedTuplet
from mir.quantizer import tie_chain


def _pieces(start, duration, beat_length=Fraction(1)):
    values = sorted({Fraction(n, d) for d in (1, 2, 4, 8, 16, 3, 6, 12, 24, 48)
                     for n in (1, 2, 3, 4, 6, 8)}, reverse=True)
    cursor, remaining = start, duration
    while remaining:
        cap = remaining
        beat_position = cursor / beat_length
        if beat_position.denominator != 1:
            cap = min(cap, (int(beat_position) + 1) * beat_length - cursor)
        candidates = [value for value in values if value <= cap]
        if not candidates:
            raise ValueError(f"Unspellable exact duration {remaining} at {cursor}")
        piece = candidates[0]
        yield cursor, piece
        cursor += piece
        remaining -= piece


def build_exact_measures(events, report, meter, key_name):
    by_id = {ev.note_id: ev for ev in events}
    mql = Fraction(str(meter.measure_quarter_length))
    beat_length = Fraction(3, 2) if meter.denominator == 8 and meter.numerator > 3 and meter.numerator % 3 == 0 else Fraction(4, meter.denominator)
    end = max((n.onset + n.duration for n in report.notes), default=mql)
    count = max(1, -(-end // mql))
    lanes = defaultdict(list)
    for note in report.notes:
        lanes[(note.staff, note.voice)].append(note)
    measures = []
    for index in range(count):
        bar_start, bar_end = index * mql, (index + 1) * mql
        staves = []
        for staff in (0, 1):
            staff_lanes = sorted(key for key in lanes if key[0] == staff)
            voices = []
            for key in staff_lanes:
                groups = defaultdict(list)
                for note in lanes[key]:
                    if note.onset < bar_end and note.onset + note.duration > bar_start:
                        start = max(bar_start, note.onset) - bar_start
                        end = min(bar_end, note.onset + note.duration) - bar_start
                        before = note.onset < bar_start
                        after = note.onset + note.duration > bar_end
                        tie = "continue" if before and after else "stop" if before else "start" if after else None
                        groups[(start, end, tie)].append(note)
                if not groups:
                    continue
                elements, cursor = [], Fraction(0)
                for (start, end, tie), group in sorted(groups.items(), key=lambda item: item[0][0]):
                    if start < cursor:
                        raise ValueError("Exact voice lane contains overlapping attacks")
                    for offset, length in _pieces(cursor, start - cursor, beat_length):
                        elements.append(PlannedRest(offset, length, key[1], hidden=key != staff_lanes[0]))
                    pieces = list(_pieces(start, end - start, beat_length))
                    ties = tie_chain(len(pieces), tie)
                    for (offset, length), piece_tie in zip(pieces, ties):
                        elements.append(PlannedNote(
                            pitches=[by_id[n.source_id].pitch for n in group],
                            start_q=offset, duration_q=length, voice=key[1],
                            velocity=max(by_id[n.source_id].velocity for n in group),
                            tie=piece_tie, event_ids=[n.source_id for n in group],
                        ))
                    cursor = end
                for offset, length in _pieces(cursor, mql - cursor, beat_length):
                    elements.append(PlannedRest(offset, length, key[1], hidden=key != staff_lanes[0]))
                annotate_rhythm(elements, meter.time_signature, f"{index}:{staff}:{key[1]}")
                voices.append(PlannedVoice(key[1], elements))
            if not voices:
                voices = [PlannedVoice(0, [PlannedRest(Fraction(0), mql, 0)])]
            staves.append(PlannedStaff(staff, "treble" if staff == 0 else "bass", voices=voices))
        measures.append(PlannedMeasure(index + 1, index * mql, mql,
                                       meter.time_signature, key_name if index == 0 else None, staves))
    validate_source_coverage(measures, report, by_id)
    return measures


def annotate_rhythm(elements, time_signature, prefix):
    """Use music21's meter grammar during planning, before serialization."""
    from music21 import meter, note, stream
    from music21.stream.makeNotation import makeTupletBrackets

    timeline = stream.Stream()
    signature = meter.TimeSignature(time_signature)
    timeline.insert(0, signature)
    objects = []
    for element in elements:
        obj = note.Rest() if isinstance(element, PlannedRest) else note.Note()
        obj.quarterLength = element.duration_q
        timeline.insert(element.start_q, obj)
        objects.append(obj)
    makeTupletBrackets(timeline, inPlace=True)
    beams = signature.getBeams(objects)
    group = 0
    for element, obj, beam_set in zip(elements, objects, beams):
        if isinstance(element, PlannedNote):
            element.beams = [(beam.type, beam.direction) for beam in beam_set] if beam_set else []
        tuplets = obj.duration.tuplets
        if tuplets:
            tuplet = tuplets[0]
            if tuplet.type in ("start", "startStop"):
                group += 1
            element.tuplet = PlannedTuplet(tuplet.numberNotesActual, tuplet.numberNotesNormal,
                                          tuplet.type, f"{prefix}:tuplet:{group}")


def validate_source_coverage(measures, report, by_id):
    fragments = defaultdict(list)
    for measure in measures:
        for staff in measure.staves:
            for voice in staff.voices:
                for element in voice.elements:
                    if not isinstance(element, PlannedNote):
                        continue
                    if len(element.pitches) != len(element.event_ids):
                        raise ValueError("Notation chord lost source identity")
                    for ident, pitch in zip(element.event_ids, element.pitches):
                        if ident not in by_id or pitch != by_id[ident].pitch:
                            raise ValueError("Notation changed a source pitch")
                        fragments[ident].append((measure.start_beat + element.start_q,
                                                 element.duration_q, staff.staff_id,
                                                 voice.voice_id, element.tie))
    if set(fragments) != {note.source_id for note in report.notes}:
        raise ValueError("Notation lost or introduced source notes")
    for note in report.notes:
        pieces = sorted(fragments[note.source_id])
        cursor = note.onset
        expected_ties = tie_chain(len(pieces), None)
        for (start, duration, staff, voice, tie), expected_tie in zip(pieces, expected_ties):
            if (start != cursor or staff != note.staff or voice != note.voice
                    or tie != expected_tie):
                raise ValueError(f"Broken source timeline for {note.source_id}")
            cursor += duration
        if cursor != note.onset + note.duration:
            raise ValueError(f"Notation changed duration for {note.source_id}")
