"""Independent source and serialized attack checks for performance notation."""

from collections import Counter, defaultdict
from dataclasses import dataclass


class NotationIntegrityError(ValueError):
    """A score no longer represents the supplied source attacks."""


@dataclass(frozen=True)
class ExportedAttack:
    pitch: int
    start: float
    end: float
    track: int
    voice: str
    velocity: int


def validate_event_identity(source, quantized):
    def identity(event):
        return (event.pitch, event.velocity, event.source_track_id, event.source_program)

    if Counter(map(identity, source)) != Counter(map(identity, quantized)):
        raise NotationIntegrityError("Quantization added, removed, or changed source notes")
    ids = [event.note_id for event in quantized]
    if any(not ident for ident in ids) or len(ids) != len(set(ids)):
        raise NotationIntegrityError("Quantization lost unique source note IDs")
    by_id = {event.note_id: event for event in quantized}
    for event in source:
        if event.note_id and (event.note_id not in by_id
                             or identity(by_id[event.note_id]) != identity(event)):
            raise NotationIntegrityError(f"Quantization changed source identity {event.note_id}")


def musicxml_attacks(path):
    """Join only contiguous ties in the same part, voice, and pitch."""
    from music21 import converter

    score = converter.parse(path, forceSource=True)
    return [(n.pitch, n.start, n.end) for n in score_attacks(score)]


def score_attacks(score):
    from music21 import stream

    result, active = [], {}
    for part_index, part in enumerate(score.parts):
        for measure in part.getElementsByClass(stream.Measure):
            for element in measure.recurse().notes:
                onset = float(element.getOffsetInHierarchy(part))
                end = onset + float(element.quarterLength)
                voice = element.activeSite if isinstance(element.activeSite, stream.Voice) else None
                members = list(element.notes) if element.isChord else [element]
                for member in members:
                    key = (part_index, str(voice.id) if voice else "1", member.pitch.midi)
                    tie = member.tie.type if member.tie else None
                    previous = active.get(key)
                    if tie in ("continue", "stop"):
                        if previous is None or abs(previous[1] - onset) > 1e-6:
                            raise NotationIntegrityError(f"Orphan or non-contiguous exported tie: {key}")
                        start, _, velocity = previous
                    else:
                        if previous is not None:
                            raise NotationIntegrityError(f"Unclosed exported tie: {key}")
                        start = onset
                        velocity = member.volume.velocity
                        if velocity is None:
                            velocity = element.volume.velocity or 64
                    if tie in ("start", "continue"):
                        active[key] = (start, end, int(velocity))
                    else:
                        active.pop(key, None)
                        result.append(ExportedAttack(member.pitch.midi, start, end,
                                                     part_index, key[1], int(velocity)))
    if active:
        raise NotationIntegrityError("Unclosed exported ties at end of score")
    return result


def _compare_attacks(expected, actual, label, tolerance):
    wanted, found = defaultdict(list), defaultdict(list)
    for pitch, *timing in expected:
        wanted[pitch].append(tuple(timing))
    for pitch, *timing in actual:
        found[pitch].append(tuple(timing))
    if {p: len(v) for p, v in wanted.items()} != {p: len(v) for p, v in found.items()}:
        raise NotationIntegrityError(f"{label} added, removed, or changed pitched attacks")
    for pitch in wanted:
        for left, right in zip(sorted(wanted[pitch]), sorted(found[pitch])):
            if any(abs(a - b) > tolerance for a, b in zip(left, right)):
                raise NotationIntegrityError(f"{label} changed attack timing for pitch {pitch}")


def validate_exports(xml_path, midi_path, events):
    import mido

    try:
        xml = musicxml_attacks(xml_path)
        expected = [(e.pitch, e.start_beat, e.start_beat + e.duration_beats) for e in events]
        _compare_attacks(expected, xml, "MusicXML", 1e-6)
        midi = mido.MidiFile(midi_path)
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
                raise NotationIntegrityError("MIDI contains unterminated notes")
        _compare_attacks(expected, attacks, "MIDI", 1 / midi.ticks_per_beat + 1e-9)
        return {"status": "passed", "expected_attacks": len(events),
                "musicxml_attacks": len(xml), "midi_attacks": len(attacks)}
    except NotationIntegrityError:
        raise
    except Exception as exc:
        raise NotationIntegrityError(f"Cannot verify notation exports: {exc}") from exc
