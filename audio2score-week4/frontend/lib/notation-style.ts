export const ALGORITHM_VERSION_CURRENT = "performance-score-1";
export const ALGORITHM_VERSION_READABLE_V2 = "performance-score-2";

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
