import assert from "node:assert/strict";
import test from "node:test";

import {
  addNote,
  changeDuration,
  changePitch,
  deleteNote,
  emptyHistory,
  findNote,
  moveNote,
  notesEqual,
  pitchName,
  pushHistory,
  redoNotes,
  undoNotes,
} from "./score-editor.ts";

const chord = [
  { id: "n-0000", pitch: 60, start: 0, duration: 1, velocity: 80, track: 0 },
  { id: "n-0001", pitch: 64, start: 0, duration: 1, velocity: 80, track: 0 },
  { id: "n-0002", pitch: 67, start: 0, duration: 1, velocity: 80, track: 0 },
];

test("pitch names stay musician-facing", () => {
  assert.equal(pitchName(60), "C4");
  assert.equal(pitchName(61), "C♯4");
});

test("pitch change is one semitone and keeps the note selected by id", () => {
  const next = changePitch(chord, "n-0000", 1);
  assert.equal(findNote(next, "n-0000")?.pitch, 61);
  assert.equal(findNote(next, "n-0001")?.pitch, 64);
});

test("duration change uses the rhythmic grid", () => {
  const next = changeDuration(chord, "n-0002", 0.5);
  assert.equal(findNote(next, "n-0002")?.duration, 0.5);
  assert.equal(findNote(next, "n-0000")?.duration, 1);
});

test("move snaps to a sixteenth and never goes negative", () => {
  const next = moveNote(chord, "n-0001", 1);
  assert.equal(findNote(next, "n-0001")?.start, 0.25);
  assert.equal(moveNote(next, "n-0001", -8)[1].start, 0);
});

test("delete removes only the selected chord tone", () => {
  const next = deleteNote(chord, "n-0001");
  assert.deepEqual(
    next.map((note) => note.pitch),
    [60, 67]
  );
});

test("add note creates a new stable id and selects it", () => {
  const { notes, id } = addNote(chord, { start: 2, pitch: 62, duration: 1 });
  assert.equal(notes.length, 4);
  assert.ok(id.startsWith("n-"));
  assert.equal(findNote(notes, id)?.pitch, 62);
  assert.equal(findNote(notes, id)?.start, 2);
});

test("undo redo and reset-equivalent history", () => {
  let notes = chord;
  let history = emptyHistory();
  history = pushHistory(history, notes);
  notes = changePitch(notes, "n-0000", 1);
  history = pushHistory(history, notes);
  notes = changeDuration(notes, "n-0000", 0.5);
  const undone = undoNotes(history, notes);
  assert.ok(undone);
  assert.equal(findNote(undone.notes, "n-0000")?.duration, 1);
  const redone = redoNotes(undone.history, undone.notes);
  assert.ok(redone);
  assert.equal(findNote(redone.notes, "n-0000")?.duration, 0.5);
  const first = undoNotes(redone.history, redone.notes);
  assert.ok(first);
  const original = undoNotes(first.history, first.notes);
  assert.ok(original);
  assert.ok(notesEqual(original.notes, chord));
  const historyAfterEdit = pushHistory(original.history, original.notes);
  const afterUndo = changePitch(original.notes, "n-0000", 2);
  const invalidated = redoNotes(historyAfterEdit, afterUndo);
  assert.equal(invalidated, null);
});
