import type { EditableNote } from "./score-editor";
import { beatsToSeconds } from "./score-editor";

export async function notesToMidiBytes(
  notes: EditableNote[],
  tempoBpm: number
): Promise<ArrayBuffer> {
  const { Midi } = await import("@tonejs/midi");
  const midi = new Midi();
  midi.header.setTempo(tempoBpm > 0 ? tempoBpm : 120);
  const tracks = new Map<number, ReturnType<typeof midi.addTrack>>();
  for (const note of notes) {
    let track = tracks.get(note.track);
    if (!track) {
      track = midi.addTrack();
      tracks.set(note.track, track);
    }
    track.addNote({
      midi: note.pitch,
      time: beatsToSeconds(note.start, tempoBpm),
      duration: Math.max(0.05, beatsToSeconds(note.duration, tempoBpm)),
      velocity: Math.max(0.1, Math.min(1, note.velocity / 127)),
    });
  }
  if (!midi.tracks.length) midi.addTrack();
  const bytes = midi.toArray();
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}
