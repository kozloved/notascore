import type { EditableNote } from "./score-editor";
import { pitchName } from "./score-editor";

type GraphicalNoteLike = {
  sourceNote?: {
    isRest?: () => boolean;
    halfTone?: number;
    Pitch?: { getHalfTone?: () => number };
    getAbsoluteTimestamp?: () => { RealValue?: number };
    Length?: { RealValue?: number };
  };
  getSVGGElement?: () => Element | null;
  getNoteheadSVGs?: () => Element[] | null;
  setColor?: (color: string, options?: object) => void;
};

function midiFromGraphical(note: GraphicalNoteLike): number | null {
  const source = note.sourceNote;
  if (!source || source.isRest?.()) return null;
  if (source.Pitch?.getHalfTone) return source.Pitch.getHalfTone();
  if (typeof source.halfTone === "number") return source.halfTone;
  return null;
}

function startBeatsFromGraphical(note: GraphicalNoteLike): number {
  const value = note.sourceNote?.getAbsoluteTimestamp?.()?.RealValue;
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return value * 4;
}

export function collectGraphicalNotes(osmd: { GraphicSheet?: { MeasureList?: unknown[][] } }): GraphicalNoteLike[] {
  const collected: GraphicalNoteLike[] = [];
  const measures = osmd.GraphicSheet?.MeasureList || [];
  for (const staffMeasures of measures) {
    for (const measure of staffMeasures || []) {
      const entries = (measure as { staffEntries?: Array<{ graphicalVoiceEntries?: Array<{ notes?: GraphicalNoteLike[] }> }> })
        ?.staffEntries;
      if (!entries) continue;
      for (const staffEntry of entries) {
        for (const voice of staffEntry.graphicalVoiceEntries || []) {
          for (const graphical of voice.notes || []) {
            if (graphical.sourceNote?.isRest?.()) continue;
            collected.push(graphical);
          }
        }
      }
    }
  }
  return collected;
}

export function stampNoteIds(
  osmd: { GraphicSheet?: { MeasureList?: unknown[][] } },
  notes: EditableNote[],
  selectedId: string | null
): void {
  const unused = new Set(notes.map((note) => note.id));
  for (const graphical of collectGraphicalNotes(osmd)) {
    const pitch = midiFromGraphical(graphical);
    if (pitch == null) continue;
    const start = startBeatsFromGraphical(graphical);
    const match = notes.find(
      (note) => unused.has(note.id) && note.pitch === pitch && Math.abs(note.start - start) < 0.2
    );
    if (!match) continue;
    unused.delete(match.id);
    const heads = graphical.getNoteheadSVGs?.() || [];
    const targets = heads.length ? heads : [graphical.getSVGGElement?.()].filter(Boolean);
    for (const node of targets) {
      if (!node) continue;
      node.setAttribute("data-note-id", match.id);
      node.setAttribute("tabindex", "0");
      node.setAttribute("role", "button");
      node.setAttribute("aria-pressed", match.id === selectedId ? "true" : "false");
      node.setAttribute("aria-label", `Note ${pitchName(match.pitch)}`);
      node.classList.toggle("ns-note-selected", match.id === selectedId);
    }
    if (graphical.setColor) {
      graphical.setColor(match.id === selectedId ? "#c87945" : "#1a1a1a", {
        applyToNoteheads: true,
        applyToStem: true,
      });
    }
  }
}

export function noteIdFromEvent(target: EventTarget | null): string | null {
  if (!(target instanceof Element)) return null;
  const hit = target.closest("[data-note-id]");
  return hit?.getAttribute("data-note-id") || null;
}
