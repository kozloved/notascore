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
  if (source.Pitch?.getHalfTone) {
    const half = source.Pitch.getHalfTone();
    if (typeof half === "number" && Number.isFinite(half)) return half;
  }
  if (typeof source.halfTone === "number") return source.halfTone;
  return null;
}

function rawTimestamp(note: GraphicalNoteLike): number {
  const value = note.sourceNote?.getAbsoluteTimestamp?.()?.RealValue;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function inferBeatScale(graphical: GraphicalNoteLike[], notes: EditableNote[]): number {
  const maxRaw = graphical.reduce((max, item) => Math.max(max, rawTimestamp(item)), 0);
  const maxNote = notes.reduce((max, item) => Math.max(max, item.start), 0);
  if (maxNote <= 0) return 4;
  const asWhole = maxRaw * 4;
  const asQuarter = maxRaw;
  const wholeErr = Math.abs(asWhole - maxNote);
  const quarterErr = Math.abs(asQuarter - maxNote);
  return wholeErr <= quarterErr ? 4 : 1;
}

function startBeats(note: GraphicalNoteLike, scale: number): number {
  return rawTimestamp(note) * scale;
}

export function collectGraphicalNotes(osmd: { GraphicSheet?: { MeasureList?: unknown[][] } }): GraphicalNoteLike[] {
  const collected: GraphicalNoteLike[] = [];
  const measures = osmd.GraphicSheet?.MeasureList || [];
  for (const staffMeasures of measures) {
    for (const measure of staffMeasures || []) {
      const entries = (
        measure as {
          staffEntries?: Array<{ graphicalVoiceEntries?: Array<{ notes?: GraphicalNoteLike[] }> }>;
        }
      )?.staffEntries;
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

function matchGraphicalToNotes(
  graphical: GraphicalNoteLike[],
  notes: EditableNote[]
): Map<GraphicalNoteLike, EditableNote> {
  const scale = inferBeatScale(graphical, notes);
  const unused = new Set(notes.map((note) => note.id));
  const pairs = new Map<GraphicalNoteLike, EditableNote>();
  for (const item of graphical) {
    const pitch = midiFromGraphical(item);
    if (pitch == null) continue;
    const start = startBeats(item, scale);
    let best: EditableNote | null = null;
    let bestDist = Infinity;
    for (const note of notes) {
      if (!unused.has(note.id) || note.pitch !== pitch) continue;
      const dist = Math.abs(note.start - start);
      if (dist < bestDist) {
        bestDist = dist;
        best = note;
      }
    }
    if (!best && unused.size) {
      for (const note of notes) {
        if (!unused.has(note.id)) continue;
        const dist = Math.abs(note.start - start) + Math.abs(note.pitch - pitch) * 0.05;
        if (dist < bestDist) {
          bestDist = dist;
          best = note;
        }
      }
    }
    if (best && bestDist < 2) {
      unused.delete(best.id);
      pairs.set(item, best);
    }
  }
  return pairs;
}

function targetElements(graphical: GraphicalNoteLike): Element[] {
  const heads = graphical.getNoteheadSVGs?.() || [];
  if (heads.length) return heads.filter(Boolean) as Element[];
  const group = graphical.getSVGGElement?.();
  return group ? [group] : [];
}

export function stampNoteIds(
  osmd: { GraphicSheet?: { MeasureList?: unknown[][] } },
  notes: EditableNote[],
  selectedId: string | null
): void {
  const graphical = collectGraphicalNotes(osmd);
  const pairs = matchGraphicalToNotes(graphical, notes);
  for (const [item, match] of pairs) {
    for (const node of targetElements(item)) {
      node.setAttribute("data-note-id", match.id);
      node.setAttribute("tabindex", "0");
      node.setAttribute("role", "button");
      node.setAttribute("aria-pressed", match.id === selectedId ? "true" : "false");
      node.setAttribute("aria-label", `Note ${pitchName(match.pitch)}`);
      node.classList.toggle("ns-note-selected", match.id === selectedId);
    }
    if (item.setColor) {
      item.setColor(match.id === selectedId ? "#c87945" : "#1a1a1a", {
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

export function noteIdAtClientPoint(
  osmd: { GraphicSheet?: { MeasureList?: unknown[][] } },
  notes: EditableNote[],
  clientX: number,
  clientY: number
): string | null {
  const graphical = collectGraphicalNotes(osmd);
  const pairs = matchGraphicalToNotes(graphical, notes);
  let bestId: string | null = null;
  let bestDist = Infinity;
  for (const [item, match] of pairs) {
    for (const node of targetElements(item)) {
      const box = node.getBoundingClientRect();
      if (!box.width && !box.height) continue;
      const cx = box.left + box.width / 2;
      const cy = box.top + box.height / 2;
      const inside =
        clientX >= box.left - 8 &&
        clientX <= box.right + 8 &&
        clientY >= box.top - 8 &&
        clientY <= box.bottom + 8;
      const dist = Math.hypot(clientX - cx, clientY - cy);
      if (inside && dist < bestDist) {
        bestDist = dist;
        bestId = match.id;
      }
    }
  }
  if (bestId) return bestId;
  for (const [item, match] of pairs) {
    for (const node of targetElements(item)) {
      const box = node.getBoundingClientRect();
      const dist = Math.hypot(clientX - (box.left + box.width / 2), clientY - (box.top + box.height / 2));
      if (dist < bestDist) {
        bestDist = dist;
        bestId = match.id;
      }
    }
  }
  return bestDist < 48 ? bestId : null;
}
