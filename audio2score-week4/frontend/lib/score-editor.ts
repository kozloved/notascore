export const GRID = 0.25;
export const MAX_NOTES = 4000;
export const MIN_PITCH = 21;
export const MAX_PITCH = 108;

export type EditableNote = {
  id: string;
  pitch: number;
  start: number;
  duration: number;
  velocity: number;
  track: number;
};

export type EditableScore = {
  revision: number;
  has_edits: boolean;
  tempo_bpm: number;
  time_signature: string;
  notes: EditableNote[];
};

export const DURATION_PRESETS = [
  { beats: 4, label: "Whole", symbol: "𝅝" },
  { beats: 2, label: "Half", symbol: "𝅗𝅥" },
  { beats: 1, label: "Quarter", symbol: "♩" },
  { beats: 0.5, label: "Eighth", symbol: "♪" },
  { beats: 0.25, label: "Sixteenth", symbol: "16" },
] as const;

const PITCH_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"];

export function snapGrid(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.round(value / GRID) * GRID;
}

export function clampPitch(pitch: number): number {
  if (!Number.isFinite(pitch)) return 60;
  return Math.max(MIN_PITCH, Math.min(MAX_PITCH, Math.round(pitch)));
}

export function pitchName(midi: number): string {
  const pitch = Math.round(midi);
  const octave = Math.floor(pitch / 12) - 1;
  return `${PITCH_NAMES[((pitch % 12) + 12) % 12]}${octave}`;
}

export function cloneNotes(notes: EditableNote[]): EditableNote[] {
  return notes.map((note) => ({ ...note }));
}

export function notesEqual(left: EditableNote[], right: EditableNote[]): boolean {
  if (left.length !== right.length) return false;
  const a = [...left].sort((x, y) => x.id.localeCompare(y.id));
  const b = [...right].sort((x, y) => x.id.localeCompare(y.id));
  return a.every((note, index) => {
    const other = b[index];
    return (
      note.id === other.id &&
      note.pitch === other.pitch &&
      note.start === other.start &&
      note.duration === other.duration &&
      note.velocity === other.velocity &&
      note.track === other.track
    );
  });
}

export function findNote(notes: EditableNote[], id: string | null): EditableNote | null {
  if (!id) return null;
  return notes.find((note) => note.id === id) || null;
}

export function changePitch(notes: EditableNote[], id: string, delta: number): EditableNote[] {
  return notes.map((note) =>
    note.id === id ? { ...note, pitch: clampPitch(note.pitch + delta) } : note
  );
}

export function changeDuration(notes: EditableNote[], id: string, beats: number): EditableNote[] {
  const duration = Math.max(GRID, snapGrid(beats));
  return notes.map((note) => (note.id === id ? { ...note, duration } : note));
}

export function moveNote(notes: EditableNote[], id: string, steps: number): EditableNote[] {
  return notes.map((note) => {
    if (note.id !== id) return note;
    const start = Math.max(0, snapGrid(note.start + steps * GRID));
    return { ...note, start };
  });
}

export function deleteNote(notes: EditableNote[], id: string): EditableNote[] {
  return notes.filter((note) => note.id !== id);
}

export function nextNoteId(notes: EditableNote[]): string {
  const used = new Set(notes.map((note) => note.id));
  for (let index = 0; index < MAX_NOTES + 8; index += 1) {
    const id = `n-a${index.toString(16)}`;
    if (!used.has(id)) return id;
  }
  return `n-${Date.now().toString(16)}`;
}

export function defaultPitchNear(notes: EditableNote[], start: number, track: number): number {
  const nearby = notes
    .filter((note) => note.track === track && Math.abs(note.start - start) <= 4)
    .sort((a, b) => Math.abs(a.start - start) - Math.abs(b.start - start));
  if (nearby[0]) return nearby[0].pitch;
  if (notes.length) {
    const sorted = [...notes].sort((a, b) => a.pitch - b.pitch);
    return sorted[Math.floor(sorted.length / 2)].pitch;
  }
  return 60;
}

export function addNote(
  notes: EditableNote[],
  at: { start: number; track?: number; pitch?: number; duration?: number }
): { notes: EditableNote[]; id: string } {
  if (notes.length >= MAX_NOTES) return { notes, id: notes[notes.length - 1]?.id || "" };
  const start = Math.max(0, snapGrid(at.start));
  const track = Math.max(0, Math.min(3, at.track ?? 0));
  const id = nextNoteId(notes);
  const created: EditableNote = {
    id,
    pitch: clampPitch(at.pitch ?? defaultPitchNear(notes, start, track)),
    start,
    duration: Math.max(GRID, snapGrid(at.duration ?? 1)),
    velocity: 80,
    track,
  };
  return { notes: [...notes, created], id };
}

export function nearestNoteId(notes: EditableNote[], fromId: string | null): string | null {
  if (!notes.length) return null;
  if (!fromId) return notes[0].id;
  const current = findNote(notes, fromId);
  if (!current) return notes[0].id;
  const ranked = notes
    .filter((note) => note.id !== fromId)
    .sort((a, b) => {
      const da = Math.abs(a.start - current.start) * 10 + Math.abs(a.pitch - current.pitch);
      const db = Math.abs(b.start - current.start) * 10 + Math.abs(b.pitch - current.pitch);
      return da - db;
    });
  return ranked[0]?.id || null;
}

export function beatsToSeconds(beats: number, tempoBpm: number): number {
  const bpm = tempoBpm > 0 ? tempoBpm : 120;
  return (beats * 60) / bpm;
}

export type HistoryState = {
  past: EditableNote[][];
  future: EditableNote[][];
};

export function emptyHistory(): HistoryState {
  return { past: [], future: [] };
}

export function pushHistory(history: HistoryState, current: EditableNote[]): HistoryState {
  return {
    past: [...history.past, cloneNotes(current)].slice(-80),
    future: [],
  };
}

export function undoNotes(
  history: HistoryState,
  current: EditableNote[]
): { notes: EditableNote[]; history: HistoryState } | null {
  if (!history.past.length) return null;
  const previous = history.past[history.past.length - 1];
  return {
    notes: cloneNotes(previous),
    history: {
      past: history.past.slice(0, -1),
      future: [cloneNotes(current), ...history.future].slice(0, 80),
    },
  };
}

export function redoNotes(
  history: HistoryState,
  current: EditableNote[]
): { notes: EditableNote[]; history: HistoryState } | null {
  if (!history.future.length) return null;
  const next = history.future[0];
  return {
    notes: cloneNotes(next),
    history: {
      past: [...history.past, cloneNotes(current)].slice(-80),
      future: history.future.slice(1),
    },
  };
}
