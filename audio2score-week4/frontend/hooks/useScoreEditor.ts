"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { track } from "../lib/analytics";
import { ApiRequestError, getScoreEdits, resetScoreEdits, saveScoreEdits } from "../lib/jobs";
import {
  addNote,
  changeDuration,
  changePitch,
  cloneNotes,
  cloneTempoCurve,
  deleteNote,
  emptyHistory,
  findNote,
  moveNote,
  nearestNoteId,
  notesEqual,
  pushHistory,
  redoNotes,
  undoNotes,
  type EditableNote,
  type HistoryState,
  type TempoCurvePoint,
} from "../lib/score-editor";

export type SaveStatus = "loading" | "ready" | "saving" | "saved" | "error" | "conflict";

const SAVE_DELAY_MS = 700;

export function useScoreEditor(scoreId: string | null) {
  const [status, setStatus] = useState<SaveStatus>("loading");
  const [error, setError] = useState("");
  const [notes, setNotes] = useState<EditableNote[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [insertAt, setInsertAt] = useState<{ start: number; track: number } | null>(null);
  const [revision, setRevision] = useState(0);
  const [hasEdits, setHasEdits] = useState(false);
  const [tempoBpm, setTempoBpm] = useState(120);
  const [timeSignature, setTimeSignature] = useState("4/4");
  const [tempoCurve, setTempoCurve] = useState<TempoCurvePoint[]>([{ beat: 0, bpm: 120 }]);
  const [printedTempoMarks, setPrintedTempoMarks] = useState<
    { beat: number; bpm: number | null; mark: string; reason: string }[]
  >([]);
  const [provenance, setProvenance] = useState<string | null>(null);
  const [renderKey, setRenderKey] = useState(0);
  const [historyTick, setHistoryTick] = useState(0);

  const originalRef = useRef<EditableNote[]>([]);
  const historyRef = useRef<HistoryState>(emptyHistory());
  const notesRef = useRef<EditableNote[]>([]);
  const revisionRef = useRef(0);
  const dirtyRef = useRef(false);
  const generationRef = useRef(0);
  const openGenerationRef = useRef(0);
  const savingGenerationRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const scoreIdRef = useRef(scoreId);

  notesRef.current = notes;
  revisionRef.current = revision;
  scoreIdRef.current = scoreId;

  const clearTimer = () => {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const persist = useCallback(async () => {
    const id = scoreIdRef.current;
    if (!id || !dirtyRef.current) return;
    const openGeneration = openGenerationRef.current;
    const submittedGeneration = generationRef.current;
    const submittedRevision = revisionRef.current;
    savingGenerationRef.current = submittedGeneration;
    setStatus("saving");
    setError("");
    try {
      const saved = await saveScoreEdits(id, {
        revision: submittedRevision,
        notes: notesRef.current,
        tempo_bpm: tempoBpm,
        time_signature: timeSignature,
        tempo_curve: tempoCurve,
        printed_tempo_marks: printedTempoMarks,
        provenance,
      });
      // Ignore responses for a score that is no longer open, or an older
      // in-flight save superseded by newer local edits.
      if (
        scoreIdRef.current !== id ||
        openGenerationRef.current !== openGeneration
      ) {
        return;
      }
      setRevision(saved.revision);
      setHasEdits(saved.has_edits);
      setRenderKey((value) => value + 1);
      if (generationRef.current === submittedGeneration) {
        dirtyRef.current = false;
        setStatus("saved");
      } else {
        dirtyRef.current = true;
        setStatus("ready");
        clearTimer();
        timerRef.current = window.setTimeout(() => {
          void persist();
        }, SAVE_DELAY_MS);
      }
      track("edit_saved");
    } catch (err) {
      if (scoreIdRef.current !== id || openGenerationRef.current !== openGeneration) {
        return;
      }
      if (err instanceof ApiRequestError && err.status === 409) {
        dirtyRef.current = true;
        setStatus("conflict");
        setError("This score was updated elsewhere. Reload to keep editing, or retry to reapply.");
        track("edit_save_failed");
        return;
      }
      dirtyRef.current = true;
      setStatus("error");
      setError("Changes couldn't be saved.");
      track("edit_save_failed");
    } finally {
      if (savingGenerationRef.current === submittedGeneration) {
        savingGenerationRef.current = null;
      }
    }
  }, [tempoBpm, timeSignature, tempoCurve, printedTempoMarks, provenance]);

  const scheduleSave = useCallback(() => {
    dirtyRef.current = true;
    generationRef.current += 1;
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      void persist();
    }, SAVE_DELAY_MS);
  }, [persist]);

  useEffect(() => {
    if (!scoreId) return undefined;
    let cancelled = false;
    openGenerationRef.current += 1;
    const loadGeneration = openGenerationRef.current;
    generationRef.current = 0;
    savingGenerationRef.current = null;
    setStatus("loading");
    setError("");
    setSelectedId(null);
    historyRef.current = emptyHistory();
    dirtyRef.current = false;
    getScoreEdits(scoreId)
      .then((payload) => {
        if (cancelled || openGenerationRef.current !== loadGeneration) return;
        originalRef.current = cloneNotes(payload.notes);
        setNotes(cloneNotes(payload.notes));
        setRevision(payload.revision);
        setHasEdits(payload.has_edits);
        setTempoBpm(payload.tempo_bpm);
        setTimeSignature(payload.time_signature);
        setTempoCurve(
          cloneTempoCurve(payload.tempo_curve || [{ beat: 0, bpm: payload.tempo_bpm }])
        );
        setPrintedTempoMarks(payload.printed_tempo_marks || []);
        setProvenance(payload.provenance || null);
        setRenderKey((value) => value + 1);
        setStatus("ready");
        track("score_editor_opened");
      })
      .catch(() => {
        if (cancelled || openGenerationRef.current !== loadGeneration) return;
        setStatus("error");
        setError("We couldn’t load this score.");
      });
    return () => {
      cancelled = true;
      clearTimer();
    };
  }, [scoreId]);

  const apply = useCallback(
    (next: EditableNote[], event?: string, selectId?: string | null) => {
      historyRef.current = pushHistory(historyRef.current, notesRef.current);
      setHistoryTick((value) => value + 1);
      setNotes(next);
      if (selectId !== undefined) setSelectedId(selectId);
      if (event) track(event as Parameters<typeof track>[0]);
      scheduleSave();
    },
    [scheduleSave]
  );

  const selectNote = useCallback((id: string | null) => {
    setSelectedId(id);
    if (id) {
      const note = findNote(notesRef.current, id);
      if (note) setInsertAt({ start: note.start, track: note.track });
      track("note_selected");
    }
  }, []);

  const selectPosition = useCallback((start: number, track: number) => {
    setSelectedId(null);
    setInsertAt({ start, track });
  }, []);

  const onPitch = useCallback(
    (delta: number) => {
      if (!selectedId) return;
      apply(changePitch(notesRef.current, selectedId, delta), "note_pitch_changed", selectedId);
    },
    [apply, selectedId]
  );

  const onDuration = useCallback(
    (beats: number) => {
      if (!selectedId) return;
      apply(changeDuration(notesRef.current, selectedId, beats), "note_duration_changed", selectedId);
    },
    [apply, selectedId]
  );

  const onMove = useCallback(
    (steps: number) => {
      if (!selectedId) return;
      apply(moveNote(notesRef.current, selectedId, steps), "note_moved", selectedId);
    },
    [apply, selectedId]
  );

  const onDelete = useCallback(() => {
    if (!selectedId) return;
    const next = deleteNote(notesRef.current, selectedId);
    apply(next, "note_deleted", nearestNoteId(next, selectedId));
  }, [apply, selectedId]);

  const onAdd = useCallback(() => {
    const selected = findNote(notesRef.current, selectedId);
    const start = insertAt?.start ?? selected?.start ?? 0;
    const track = insertAt?.track ?? selected?.track ?? 0;
    const duration = selected?.duration ?? 1;
    const created = addNote(notesRef.current, { start, track, duration });
    setInsertAt({ start: created.notes.find((note) => note.id === created.id)?.start ?? start, track });
    apply(created.notes, "note_added", created.id);
  }, [apply, insertAt, selectedId]);

  const onUndo = useCallback(() => {
    const result = undoNotes(historyRef.current, notesRef.current);
    if (!result) return;
    historyRef.current = result.history;
    setHistoryTick((value) => value + 1);
    setNotes(result.notes);
    track("edit_undone");
    scheduleSave();
  }, [scheduleSave]);

  const onRedo = useCallback(() => {
    const result = redoNotes(historyRef.current, notesRef.current);
    if (!result) return;
    historyRef.current = result.history;
    setHistoryTick((value) => value + 1);
    setNotes(result.notes);
    track("edit_redone");
    scheduleSave();
  }, [scheduleSave]);

  const onReset = useCallback(async () => {
    const id = scoreIdRef.current;
    if (!id) return;
    clearTimer();
    setStatus("saving");
    try {
      const restored = await resetScoreEdits(id, { revision: revisionRef.current });
      originalRef.current = cloneNotes(restored.notes);
      historyRef.current = emptyHistory();
      setHistoryTick((value) => value + 1);
      dirtyRef.current = false;
      generationRef.current = 0;
      setNotes(cloneNotes(restored.notes));
      setRevision(restored.revision);
      setHasEdits(false);
      setSelectedId(null);
      setInsertAt(null);
      setTempoBpm(restored.tempo_bpm);
      setTimeSignature(restored.time_signature);
      setTempoCurve(
        cloneTempoCurve(restored.tempo_curve || [{ beat: 0, bpm: restored.tempo_bpm }])
      );
      setPrintedTempoMarks(restored.printed_tempo_marks || []);
      setProvenance(restored.provenance || null);
      setRenderKey((value) => value + 1);
      setStatus("saved");
      track("edit_reset");
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 409) {
        dirtyRef.current = true;
        setStatus("conflict");
        setError("This score was updated elsewhere. Reload before resetting.");
        track("edit_save_failed");
        return;
      }
      setStatus("error");
      setError("We couldn’t reset these changes.");
      track("edit_save_failed");
    }
  }, []);

  const retrySave = useCallback(() => {
    dirtyRef.current = true;
    generationRef.current += 1;
    void persist();
  }, [persist]);

  const reloadRemote = useCallback(async () => {
    const id = scoreIdRef.current;
    if (!id) return;
    clearTimer();
    setStatus("loading");
    setError("");
    try {
      const payload = await getScoreEdits(id);
      originalRef.current = cloneNotes(payload.notes);
      historyRef.current = emptyHistory();
      setHistoryTick((value) => value + 1);
      dirtyRef.current = false;
      generationRef.current = 0;
      setNotes(cloneNotes(payload.notes));
      setRevision(payload.revision);
      setHasEdits(payload.has_edits);
      setTempoBpm(payload.tempo_bpm);
      setTimeSignature(payload.time_signature);
      setTempoCurve(
        cloneTempoCurve(payload.tempo_curve || [{ beat: 0, bpm: payload.tempo_bpm }])
      );
      setPrintedTempoMarks(payload.printed_tempo_marks || []);
      setProvenance(payload.provenance || null);
      setRenderKey((value) => value + 1);
      setStatus("ready");
    } catch {
      setStatus("error");
      setError("We couldn’t load this score.");
    }
  }, []);

  const flushSave = useCallback(async () => {
    clearTimer();
    await persist();
  }, [persist]);

  const dirty = !notesEqual(notes, originalRef.current) || hasEdits;
  const canUndo = historyRef.current.past.length > 0;
  const canRedo = historyRef.current.future.length > 0;
  const selected = findNote(notes, selectedId);
  void historyTick;

  return {
    status,
    error,
    notes,
    selected,
    selectedId,
    insertAt,
    revision,
    hasEdits,
    tempoBpm,
    timeSignature,
    tempoCurve,
    renderKey,
    dirty: dirty && (hasEdits || !notesEqual(notes, originalRef.current)),
    canUndo,
    canRedo,
    selectNote,
    selectPosition,
    onPitch,
    onDuration,
    onMove,
    onDelete,
    onAdd,
    onUndo,
    onRedo,
    onReset,
    retrySave,
    reloadRemote,
    flushSave,
  };
}
