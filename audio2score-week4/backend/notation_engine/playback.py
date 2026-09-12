"""Build MIDI input from unsplit attacks, never from engraving fragments."""

from music21 import instrument, meter, note, stream, tempo


def playback_score(events, time_signature, tempo_points):
    score = stream.Score()
    parts = {}
    for event in events:
        key = (event.hand, event.voice, event.source_track_id, event.source_program)
        if key not in parts:
            part = stream.Part()
            program = event.source_program if event.source_program is not None else 0
            part.insert(0, instrument.instrumentFromMidiProgram(program))
            score.insert(0, part)
            parts[key] = part
        attack = note.Note(midi=event.pitch, quarterLength=event.duration_beats)
        attack.volume.velocity = event.velocity
        parts[key].insert(event.start_beat, attack)
    if not parts:
        score.insert(0, stream.Part())
    first = score.parts[0]
    first.insert(0, meter.TimeSignature(time_signature))
    for beat, bpm in tempo_points:
        first.insert(beat, tempo.MetronomeMark(number=float(bpm)))
    return score
