export const ALGORITHM_VERSION_CURRENT = "performance-score-1";
export const ALGORITHM_VERSION_READABLE_V2 = "performance-score-2";

export type AlgorithmVersionChoice =
  | typeof ALGORITHM_VERSION_CURRENT
  | typeof ALGORITHM_VERSION_READABLE_V2;

export function algorithmVersionLabel(version: string): string {
  if (version === ALGORITHM_VERSION_READABLE_V2) return "Experimental";
  return "Standard";
}

export type ReadableGapStyle = "current" | "fill_tiny_gaps";

export const READABLE_GAP_OPTIONS = [
  { value: "current", label: "Keep tiny gaps" },
  { value: "fill_tiny_gaps", label: "Fill tiny gaps" },
] as const;

export function readableGapStyle(settings: {
  interpretation: string;
  algorithm_version: string;
}): ReadableGapStyle {
  if (
    settings.interpretation === "readable" &&
    settings.algorithm_version === ALGORITHM_VERSION_READABLE_V2
  ) {
    return "fill_tiny_gaps";
  }
  return "current";
}

export function patchForReadableGapStyle(style: ReadableGapStyle): {
  interpretation: "readable";
  algorithm_version: string;
} {
  return {
    interpretation: "readable",
    algorithm_version:
      style === "fill_tiny_gaps"
        ? ALGORITHM_VERSION_READABLE_V2
        : ALGORITHM_VERSION_CURRENT,
  };
}

const FEEL_LABELS: Record<string, string> = {
  auto: "Auto",
  straight: "Straight",
  swing_eighths: "Swing eighths",
  swing_sixteenths: "Swing 16ths",
  shuffle: "Shuffle",
  mixed: "Mixed",
};

export function rhythmicFeelLabel(feel: string | null | undefined): string {
  if (!feel) return "Unknown";
  return FEEL_LABELS[feel] || feel.replace(/_/g, " ");
}

export function detectedFeelSummary(detected: {
  rhythmic_feel?: string | null;
  maps_written_timing?: boolean;
  confidence?: number;
  origin?: string | null;
  user_summary?: string | null;
} | null | undefined): string | null {
  if (!detected) return null;
  if (detected.user_summary) return detected.user_summary;
  if (!detected.maps_written_timing) return null;
  const confidence = detected.confidence ?? 0;
  if (confidence < 0.55 && detected.origin !== "user_override") return null;
  if (
    detected.rhythmic_feel === "swing_eighths" ||
    detected.rhythmic_feel === "shuffle" ||
    detected.rhythmic_feel === "mixed"
  ) {
    return "Swing detected — shown using conventional eighth-note notation.";
  }
  if (detected.rhythmic_feel === "swing_sixteenths") {
    return "Swing 16ths detected — shown using conventional sixteenth-note notation.";
  }
  return null;
}
