/** Written → sounded mapping for score playback. Matches mir/swing.py. */

export type SwingSpan = {
  start_beat: number;
  end_beat: number;
  feel?: string | null;
  subdivision_unit?: number | null;
  ratio?: number | null;
  maps_written_timing?: boolean;
  triplet_exceptions?: Array<number[] | { start: number; end: number; stream?: string | null }>;
  unmapped_streams?: string[];
};

export type PlaybackNote = {
  start: number;
  duration: number;
  performed_start_beat?: number | null;
  performed_duration_beats?: number | null;
  stream_key?: string | null;
  track?: number;
  voice?: number;
  hand?: string | null;
  source_track_id?: string | null;
  score_timing_locked?: boolean;
  articulation?: string | null;
};

const DOWNBEAT = 0.12;
const DOTTED = 0.75;
const STRAIGHT = 0.5;
const TRIPLET_THIRD = 1 / 3;
const TRIPLET_OFF = 2 / 3;
const SWING_OFFBEAT_WINDOW = 0.11;
const SWING_FEELS = new Set(["swing_eighths", "swing_sixteenths", "shuffle"]);
const SWING_PARTICIPANTS = new Set(["downbeat", "swing_offbeat"]);

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

export function streamKey(note: PlaybackNote): string {
  if (note.stream_key) return note.stream_key;
  const hand = note.hand || (note.track === 1 ? "left" : "right");
  const track = note.source_track_id != null ? String(note.source_track_id) : note.track != null ? String(note.track) : "";
  const voice = Number(note.voice || 0);
  return `${track}|${hand}|${voice}`;
}

function spanAt(spans: SwingSpan[], beat: number): SwingSpan | null {
  const ordered = [...spans].sort((a, b) => a.start_beat - b.start_beat || a.end_beat - b.end_beat);
  for (const span of ordered) {
    if (beat + 1e-9 >= span.start_beat && beat < span.end_beat - 1e-9) {
      return span;
    }
  }
  return null;
}

function pairLength(span: SwingSpan): number {
  return Math.max(2 * Number(span.subdivision_unit || 0.5), 1e-6);
}

function mapsSpan(span: SwingSpan | null): span is SwingSpan {
  return Boolean(
    span &&
      span.maps_written_timing !== false &&
      span.ratio &&
      SWING_FEELS.has(String(span.feel || ""))
  );
}

function streamUnmapped(span: SwingSpan, stream: string): boolean {
  return (span.unmapped_streams || []).includes(stream);
}

function tripletAt(span: SwingSpan, beat: number, stream: string | null): boolean {
  for (const raw of span.triplet_exceptions || []) {
    const start = Array.isArray(raw) ? Number(raw[0]) : Number(raw.start);
    const end = Array.isArray(raw) ? Number(raw[1]) : Number(raw.end);
    const owner = Array.isArray(raw) ? (raw.length > 2 ? String(raw[2]) : null) : raw.stream || null;
    if (beat + 1e-9 >= start && beat < end + 1e-9) {
      if (owner == null || stream == null || owner === stream) return true;
    }
  }
  return false;
}

function classifyWritten(beat: number, span: SwingSpan, stream: string): string {
  if (!mapsSpan(span) || span.feel === "straight" || span.ratio == null) return "exception";
  if (streamUnmapped(span, stream)) return "straight";
  if (tripletAt(span, beat, stream)) return "triplet";
  const pair = pairLength(span);
  const frac = (beat % pair) / pair;
  if (frac <= DOWNBEAT || frac >= 1 - DOWNBEAT) return "downbeat";
  if (Math.abs(frac - DOTTED) <= 0.07) return "dotted";
  if (Math.abs(frac - STRAIGHT) <= 0.08) return "swing_offbeat";
  if (Math.min(Math.abs(frac - TRIPLET_THIRD), Math.abs(frac - TRIPLET_OFF)) <= 0.05) return "triplet";
  if (Math.abs(frac - performedOffbeatFraction(Number(span.ratio))) <= SWING_OFFBEAT_WINDOW) {
    return "exception";
  }
  return "ambiguous";
}

function classifyOnset(beat: number, span: SwingSpan, stream: string): string {
  if (!mapsSpan(span) || span.feel === "straight" || span.ratio == null) return "exception";
  if (streamUnmapped(span, stream)) return "straight";
  if (tripletAt(span, beat, stream)) return "triplet";
  const pair = pairLength(span);
  const frac = (beat % pair) / pair;
  if (frac <= DOWNBEAT || frac >= 1 - DOWNBEAT) return "downbeat";
  const target = performedOffbeatFraction(Number(span.ratio));
  const swingD = Math.abs(frac - target);
  const dottedD = Math.abs(frac - DOTTED);
  const straightD = Math.abs(frac - STRAIGHT);
  const tripletD = Math.min(Math.abs(frac - TRIPLET_THIRD), Math.abs(frac - TRIPLET_OFF));
  if (dottedD + 0.015 < swingD && dottedD <= 0.07) return "dotted";
  if (straightD + 0.02 < swingD && straightD <= 0.08) return "straight";
  if (tripletD + 0.02 < swingD && tripletD <= 0.05 && tripletAt(span, beat, stream)) return "triplet";
  if (swingD <= SWING_OFFBEAT_WINDOW) return "swing_offbeat";
  return "ambiguous";
}

function onsetParticipates(note: PlaybackNote, span: SwingSpan | null, stream: string): boolean {
  if (!mapsSpan(span)) return false;
  if (!SWING_PARTICIPANTS.has(classifyWritten(note.start, span, stream))) return false;
  if (note.performed_start_beat != null) {
    return SWING_PARTICIPANTS.has(classifyOnset(Number(note.performed_start_beat), span, stream));
  }
  return true;
}

function mapRelease(endBeat: number, spans: SwingSpan[], stream: string): number {
  const endSpan = spanAt(spans, endBeat);
  if (!mapsSpan(endSpan)) return endBeat;
  if (!SWING_PARTICIPANTS.has(classifyWritten(endBeat, endSpan, stream))) return endBeat;
  return mapBeatThroughSwing(endBeat, pairLength(endSpan), Number(endSpan.ratio), true);
}

/**
 * Shared playback contract with mir/swing.py apply_playback_timing:
 * full span list, stream-owned exceptions, performed provenance, mapped
 * releases only when the endpoint participates. Duration does not decide onset.
 */
export function applyPlaybackTiming<T extends PlaybackNote>(
  notes: T[],
  spans: SwingSpan[] | null | undefined
): T[] {
  const all = spans || [];
  if (!all.some((span) => mapsSpan(span))) return notes;
  return notes.map((note) => {
    if (note.score_timing_locked) return note;
    const span = spanAt(all, note.start);
    const stream = streamKey(note);
    if (!onsetParticipates(note, span, stream) || !mapsSpan(span)) return note;
    const start = mapBeatThroughSwing(note.start, pairLength(span), Number(span.ratio), true);
    const mappedEnd = mapRelease(note.start + Math.max(note.duration, 1e-6), all, stream);
    return { ...note, start, duration: Math.max(mappedEnd - start, 1e-4) };
  });
}

export function allocateSoundingLanes<T extends { start: number; duration: number; pitch?: number; id?: string }>(
  notes: T[]
): number[] {
  const assigned = notes.map(() => 0);
  const lanePitchEnd: Array<Map<number, number>> = [];
  const order = notes
    .map((_, index) => index)
    .sort((a, b) => {
      const left = notes[a];
      const right = notes[b];
      return (
        left.start - right.start ||
        Number(left.pitch || 0) - Number(right.pitch || 0) ||
        String(left.id || "").localeCompare(String(right.id || ""))
      );
    });
  for (const index of order) {
    const note = notes[index];
    const start = note.start;
    const end = start + Math.max(note.duration, 1e-6);
    const pitch = Number(note.pitch || 0);
    let lane: number | null = null;
    for (let candidate = 0; candidate < lanePitchEnd.length; candidate += 1) {
      const last = lanePitchEnd[candidate].get(pitch);
      if (last == null || last <= start + 1e-9) {
        lane = candidate;
        lanePitchEnd[candidate].set(pitch, end);
        break;
      }
    }
    if (lane == null) {
      lane = lanePitchEnd.length;
      lanePitchEnd.push(new Map([[pitch, end]]));
    }
    assigned[index] = lane;
  }
  return assigned;
}
