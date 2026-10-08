import type { EditableNote, TempoCurvePoint } from "./score-editor";

/** Keep in sync with notation_engine.playback.STACCATO_PLAYBACK_FRACTION. */
export const STACCATO_PLAYBACK_FRACTION = 0.5;

export function playbackDurationBeats(
  note: Pick<EditableNote, "duration" | "articulation">
): number {
  const written = Number(note.duration);
  if (!(written > 0)) return written;
  if ((note.articulation || "") === "staccato") {
    return Math.max(written * STACCATO_PLAYBACK_FRACTION, 1e-3);
  }
  return written;
}

function sortedCurve(
  tempoBpm: number,
  tempoCurve?: TempoCurvePoint[]
): TempoCurvePoint[] {
  const bpm = tempoBpm > 0 ? tempoBpm : 120;
  const points = [...(tempoCurve || [])]
    .filter((point) => Number.isFinite(point.beat) && Number.isFinite(point.bpm) && point.bpm > 0)
    .sort((a, b) => a.beat - b.beat);
  if (!points.length) return [{ beat: 0, bpm }];
  if (points[0].beat > 0) points.unshift({ beat: 0, bpm: points[0].bpm });
  return points;
}

export async function notesToMidiBytes(
  notes: EditableNote[],
  tempoBpm: number,
  tempoCurve?: TempoCurvePoint[]
): Promise<ArrayBuffer> {
  const { Midi } = await import("@tonejs/midi");
  const midi = new Midi();
  const ppq = midi.header.ppq;
  const curve = sortedCurve(tempoBpm, tempoCurve);
  midi.header.tempos = curve.map((point) => ({
    ticks: Math.max(0, Math.round(point.beat * ppq)),
    bpm: point.bpm,
  }));
  const tracks = new Map<number, ReturnType<typeof midi.addTrack>>();
  for (const note of notes) {
    let track = tracks.get(note.track);
    if (!track) {
      track = midi.addTrack();
      tracks.set(note.track, track);
    }
    track.addNote({
      midi: note.pitch,
      ticks: Math.max(0, Math.round(note.start * ppq)),
      durationTicks: Math.max(1, Math.round(playbackDurationBeats(note) * ppq)),
      velocity: Math.max(0.1, Math.min(1, note.velocity / 127)),
    });
  }
  if (!midi.tracks.length) midi.addTrack();
  const bytes = midi.toArray();
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}
