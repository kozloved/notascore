export type TranscriptionMode = "solo" | "polyphonic";

const ALIASES: Record<string, TranscriptionMode> = {
  solo: "solo",
  fast: "solo",
  polyphonic: "polyphonic",
  poly: "polyphonic",
  quality: "polyphonic",
  mt3: "polyphonic",
};

export function parseMode(raw?: string | null): TranscriptionMode {
  if (!raw) return "solo";
  return ALIASES[String(raw).toLowerCase()] ?? "solo";
}

/** MIDI skips note detection. Audio uses the mode the musician selected. */
export function uploadMode(args: {
  selected: TranscriptionMode;
  midi: boolean;
}): TranscriptionMode {
  if (args.midi) return "solo";
  return args.selected === "polyphonic" ? "polyphonic" : "solo";
}

export function polyphonicAvailable(health: unknown): boolean {
  if (!health || typeof health !== "object") return false;
  const payload = health as {
    modes?: { polyphonic?: boolean; quality?: boolean };
    polyphonic?: { available?: boolean };
    quality?: { available?: boolean };
  };
  return Boolean(
    payload.modes?.polyphonic ??
      payload.polyphonic?.available ??
      payload.quality?.available
  );
}
