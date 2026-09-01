"use client";

import Button from "../ui/Button";
import { DURATION_PRESETS, pitchName, type EditableNote } from "../../lib/score-editor";

type NoteToolbarProps = {
  note: EditableNote | null;
  insertAt: { start: number; track: number } | null;
  onPitch: (delta: number) => void;
  onDuration: (beats: number) => void;
  onMove: (steps: number) => void;
  onDelete: () => void;
  onAdd: () => void;
};

export default function NoteToolbar({
  note,
  insertAt,
  onPitch,
  onDuration,
  onMove,
  onDelete,
  onAdd,
}: NoteToolbarProps) {
  if (!note && !insertAt) return null;

  return (
    <div className="ns-note-toolbar" role="toolbar" aria-label="Edit score">
      {note ? (
        <>
          <div className="ns-note-toolbar-pitch">
            <p className="ns-note-pitch" aria-live="polite">
              {pitchName(note.pitch)}
            </p>
            <div className="ns-note-stepper">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onPitch(-1)}
                aria-label="Change pitch down"
              >
                −
              </Button>
              <span>{pitchName(note.pitch)}</span>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => onPitch(1)}
                aria-label="Change pitch up"
              >
                +
              </Button>
            </div>
          </div>
          <div className="ns-note-durations" role="group" aria-label="Change duration">
            {DURATION_PRESETS.map((preset) => (
              <button
                key={preset.beats}
                type="button"
                className={
                  "ns-note-duration" +
                  (note.duration === preset.beats ? " is-active" : "")
                }
                onClick={() => onDuration(preset.beats)}
                aria-label={preset.label}
                aria-pressed={note.duration === preset.beats}
              >
                <span aria-hidden="true">{preset.symbol}</span>
              </button>
            ))}
          </div>
          <div className="ns-note-stepper" role="group" aria-label="Move note">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onMove(-1)}
              aria-label="Move earlier"
            >
              ←
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => onMove(1)}
              aria-label="Move later"
            >
              →
            </Button>
          </div>
          <Button variant="destructive" size="sm" onClick={onDelete}>
            Delete note
          </Button>
        </>
      ) : (
        <p className="ns-note-toolbar-hint">Add a note at this place in the score.</p>
      )}
      <Button variant="secondary" size="sm" onClick={onAdd}>
        Add note
      </Button>
    </div>
  );
}
