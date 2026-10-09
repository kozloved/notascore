/** Written → sounded mapping for score playback. Matches mir/swing.py. */

export type SwingSpan = {
  start_beat: number;
  end_beat: number;
  feel?: string | null;
  subdivision_unit?: number | null;
  ratio?: number | null;
  maps_written_timing?: boolean;
  triplet_exceptions?: Array<number[] | { start: number; end: number }>;
  unmapped_streams?: string[];
};

const DOWNBEAT = 0.12;
const DOTTED = 0.75;
const STRAIGHT = 0.5;

export function performedOffbeatFraction(ratio: number): number {
  const r = Math.max(ratio, 1e-6);
  return r / (r + 1);
}

export function mapPairFraction(fraction: number, ratio: number, reverse = false): number {
  const f = ((fraction % 1) + 1) % 1;
  const performed = performedOffbeatFraction(ratio);
  const written = 0.5;
  const src = reverse ? written : performed;
  const dst = reverse ? performed : written;
  if (src <= 1e-9) return f;
  if (f <= src) return f * (dst / src);
  return dst + (f - src) * ((1 - dst) / Math.max(1 - src, 1e-9));
}

export function mapBeatThroughSwing(
  beat: number,
  pairLength: number,
  ratio: number,
  reverse = false
): number {
  const pair = Math.max(pairLength, 1e-6);
  const index = Math.floor(beat / pair);
  const frac = (beat - index * pair) / pair;
  return (index + mapPairFraction(frac, ratio, reverse)) * pair;
}

function spanAt(spans: SwingSpan[], beat: number): SwingSpan | null {
  for (const span of spans) {
    if (beat + 1e-9 >= span.start_beat && beat < span.end_beat - 1e-9) {
      return span;
    }
  }
  return null;
}

function pairLength(span: SwingSpan): number {
  return Math.max(2 * Number(span.subdivision_unit || 0.5), 1e-6);
}

function isSwingSpan(span: SwingSpan | null): span is SwingSpan {
  return Boolean(
    span &&
      span.maps_written_timing !== false &&
      span.ratio &&
      (span.feel === "swing_eighths" ||
        span.feel === "swing_sixteenths" ||
        span.feel === "shuffle")
  );
}

function tripletAt(span: SwingSpan, beat: number): boolean {
  for (const raw of span.triplet_exceptions || []) {
    const start = Array.isArray(raw) ? Number(raw[0]) : Number(raw.start);
    const end = Array.isArray(raw) ? Number(raw[1]) : Number(raw.end);
    if (beat + 1e-9 >= start && beat < end + 1e-9) return true;
  }
  return false;
}

function shouldSwingWritten(beat: number, span: SwingSpan): boolean {
  if (tripletAt(span, beat)) return false;
  const frac = (beat % pairLength(span)) / pairLength(span);
  if (frac <= DOWNBEAT || frac >= 1 - DOWNBEAT) return true;
  if (Math.abs(frac - DOTTED) <= 0.07) return false;
  if (Math.abs(frac - STRAIGHT) <= 0.08) return true;
  return false;
}

export function applyPlaybackTiming<T extends { start: number; duration: number }>(
  notes: T[],
  spans: SwingSpan[] | null | undefined
): T[] {
  const active = (spans || []).filter((span) => isSwingSpan(span));
  if (!active.length) return notes;
  return notes.map((note) => {
    const span = spanAt(active, note.start);
    if (!isSwingSpan(span) || !shouldSwingWritten(note.start, span)) return note;
    const ratio = Number(span.ratio);
    const pair = pairLength(span);
    const start = mapBeatThroughSwing(note.start, pair, ratio, true);
    let duration = note.duration;
    if (note.duration <= pair * 1.25) {
      const endBeat = note.start + note.duration;
      const endSpan = spanAt(active, endBeat) || span;
      if (isSwingSpan(endSpan) && !tripletAt(endSpan, endBeat)) {
        duration = Math.max(
          mapBeatThroughSwing(endBeat, pairLength(endSpan), Number(endSpan.ratio), true) - start,
          1e-4
        );
      }
    }
    return { ...note, start, duration };
  });
}
