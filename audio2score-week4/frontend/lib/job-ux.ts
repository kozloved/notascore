export type BackendJobStatus = string;

export type UserPhase =
  | "idle"
  | "preview"
  | "uploading"
  | "queued"
  | "processing"
  | "completed"
  | "failed";

export type StageId =
  | "listening"
  | "notes"
  | "rhythm"
  | "writing";

export const STAGES: { id: StageId; label: string }[] = [
  { id: "listening", label: "Listening to your recording" },
  { id: "notes", label: "Finding the notes" },
  { id: "rhythm", label: "Understanding the rhythm" },
  { id: "writing", label: "Writing your score" },
];

export function mapBackendStatus(status?: string | null): UserPhase {
  switch (status) {
    case "queued":
      return "queued";
    case "processing":
      return "processing";
    case "completed":
      return "completed";
    case "failed":
      return "failed";
    default:
      return "queued";
  }
}

export function currentStage(status?: string | null, progress?: number | null): StageId {
  const phase = mapBackendStatus(status);
  const value = typeof progress === "number" ? progress : 0;
  if (phase === "queued") return "listening";
  if (phase === "completed") return "writing";
  if (value < 20) return "listening";
  if (value < 40) return "notes";
  if (value < 75) return "rhythm";
  return "writing";
}

export function stageIndex(id: StageId): number {
  return STAGES.findIndex((s) => s.id === id);
}

export function headlineForJob(status?: string | null, progress?: number | null): string {
  const phase = mapBackendStatus(status);
  if (phase === "queued") return "Preparing your score…";
  if (phase === "failed") return "We couldn’t create your score.";
  if (phase === "completed") return "Your score is ready.";
  const stage = currentStage(status, progress);
  const found = STAGES.find((s) => s.id === stage);
  return found ? `${found.label}…` : "Listening to your recording…";
}

export function chipLabel(status?: string | null): string {
  const phase = mapBackendStatus(status);
  if (phase === "completed") return "Ready";
  if (phase === "failed") return "Failed";
  return "Processing…";
}
