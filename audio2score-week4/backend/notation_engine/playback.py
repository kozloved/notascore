"""Build MIDI input from unsplit attacks, never from engraving fragments."""

from music21 import instrument, meter, note, stream, tempo

from mir.swing import allocate_sounding_lanes, apply_playback_timing, spans_from_payload

STACCATO_PLAYBACK_FRACTION = 0.5


def playback_duration_beats(event) -> float:
    """Sounding length for score MIDI after swing mapping.

    Staccato shortens the already-mapped duration and must not rewrite
    swing onsets or releases.
    """
    written = float(event.duration_beats)
    if written <= 0:
        return written
    if (getattr(event, "articulation", None) or "") == "staccato":
        return max(written * STACCATO_PLAYBACK_FRACTION, 1e-3)
    return written


def _midi_channel_for_lane(lane: int) -> int:
    """Sounding lanes use channels 1–16, skipping GM percussion (10)."""
    index = int(lane) % 15
    channel = index + 1
    if channel >= 10:
        channel += 1
    return channel


def playback_score(events, time_signature, tempo_points, *, swing_spans=None):
    """Sound written attacks. Swing spans remap written even values once.

    Do not pass original-performance events through this mapping. Overlapping
    same-pitch sounding notes are split onto extra MIDI lanes/channels so
    SMF serialization does not collapse independent unisons.
    """
    sounding = apply_playback_timing(list(events), spans_from_payload(swing_spans or ()))
    lanes = allocate_sounding_lanes(sounding)
    score = stream.Score()
    parts = {}
    for event, lane in zip(sounding, lanes):
        key = (event.hand, event.voice, event.source_track_id, event.source_program, lane)
        if key not in parts:
            part = stream.Part()
            program = event.source_program if event.source_program is not None else 0
            inst = instrument.instrumentFromMidiProgram(program)
            inst.midiChannel = _midi_channel_for_lane(lane)
            part.insert(0, inst)
            score.insert(0, part)
            parts[key] = part
        attack = note.Note(midi=event.pitch, quarterLength=playback_duration_beats(event))
        attack.volume.velocity = event.velocity
        parts[key].insert(event.start_beat, attack)
    if not parts:
        score.insert(0, stream.Part())
    first = score.parts[0]
    first.insert(0, meter.TimeSignature(time_signature))
    for beat, bpm in tempo_points:
        first.insert(beat, tempo.MetronomeMark(number=float(bpm)))
    return score
