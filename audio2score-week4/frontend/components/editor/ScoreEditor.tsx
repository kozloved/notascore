"use client";

import { useEffect, useRef, useState } from "react";

import { track } from "../../lib/analytics";
import { notesToMidiBytes } from "../../lib/score-midi";
import { MidiPreviewPlayer } from "../../lib/midiPlayback";
import { useScoreEditor } from "../../hooks/useScoreEditor";
import Button from "../ui/Button";
import SheetResult from "../SheetResult";
import NoteToolbar from "./NoteToolbar";

type ScoreEditorProps = {
  apiUrl: string;
  jobId: string;
  filename?: string;
  onExport?: (format: string) => void;
};

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

export default function ScoreEditor({
  apiUrl,
  jobId,
  filename,
  onExport,
}: ScoreEditorProps) {
  const editor = useScoreEditor(jobId);
  const rootRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<MidiPreviewPlayer | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => {
    playerRef.current = new MidiPreviewPlayer();
    return () => {
      void playerRef.current?.stop();
    };
  }, [jobId]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTypingTarget(event.target)) return;
      if (document.querySelector(".ns-dialog-backdrop")) return;
      const meta = event.metaKey || event.ctrlKey;
      if (meta && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) editor.onRedo();
        else editor.onUndo();
        return;
      }
      if (meta && event.key.toLowerCase() === "y") {
        event.preventDefault();
        editor.onRedo();
        return;
      }
      if (!editor.selectedId) return;
      if (event.key === "ArrowUp") {
        event.preventDefault();
        editor.onPitch(event.shiftKey ? 12 : 1);
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        editor.onPitch(event.shiftKey ? -12 : -1);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        editor.onMove(-1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        editor.onMove(1);
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        editor.onDelete();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [editor]);

  const togglePlay = async () => {
    const player = playerRef.current;
    if (!player) return;
    if (playing) {
      await player.stop();
      setPlaying(false);
      return;
    }
    const buffer = await notesToMidiBytes(editor.notes, editor.tempoBpm);
    await player.play(buffer, 0, {
      onEnd: () => setPlaying(false),
    });
    setPlaying(true);
  };

  const saveLabel =
    editor.status === "saving"
      ? "Saving…"
      : editor.status === "saved"
        ? "Saved"
        : editor.status === "error"
          ? "Couldn't save changes"
          : "";

  return (
    <div className="ns-score-editor" ref={rootRef} tabIndex={0} aria-label="Score editor">
      <div className="ns-editor-chrome">
        <div className="ns-editor-actions">
          <Button
            variant="secondary"
            size="sm"
            onClick={editor.onUndo}
            disabled={!editor.canUndo}
            aria-label="Undo"
          >
            Undo
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={editor.onRedo}
            disabled={!editor.canRedo}
            aria-label="Redo"
          >
            Redo
          </Button>
          {editor.dirty ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void editor.onReset()}
            >
              Reset changes
            </Button>
          ) : null}
        </div>
        <div className="ns-editor-actions">
          <p className="ns-editor-save" aria-live="polite">
            {saveLabel}
            {editor.status === "error" ? (
              <button type="button" className="ns-text-link" onClick={editor.retrySave}>
                Try again
              </button>
            ) : null}
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void togglePlay()}
            aria-label={playing ? "Stop" : "Play"}
          >
            {playing ? "Stop" : "Play"}
          </Button>
        </div>
      </div>

      {editor.status === "loading" ? (
        <p className="ns-editor-save">Loading the score…</p>
      ) : null}

      <SheetResult
        apiUrl={apiUrl}
        jobId={jobId}
        filename={filename}
        interactive
        revision={editor.renderKey}
        notes={editor.notes}
        selectedNoteId={editor.selectedId}
        onSelectNote={editor.selectNote}
        onSelectPosition={(start: number, track: number) => editor.selectPosition(start, track)}
        onBeforeExport={editor.flushSave}
        onExport={(format: string) => {
          if (editor.hasEdits || editor.dirty) track("edited_score_exported");
          onExport?.(format);
        }}
      />

      <NoteToolbar
        note={editor.selected}
        insertAt={editor.insertAt}
        onPitch={editor.onPitch}
        onDuration={editor.onDuration}
        onMove={editor.onMove}
        onDelete={editor.onDelete}
        onAdd={editor.onAdd}
      />
    </div>
  );
}
