import { API_URL, type Job } from "./api";
import { apiFetch } from "./api-client";
import { consumePendingClaim } from "./pending-claim";
import type { EditableNote } from "./score-editor";
import { listStoredScores } from "./session-jobs";

export class ApiRequestError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

const STALE_REVISION = "This score was updated elsewhere. Reload and try again.";

type ParsedDetail = { message: string; code?: string };

function parseDetail(body: unknown, fallback: string): ParsedDetail {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return { message: detail };
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((row) =>
        row && typeof row === "object" && "msg" in row
          ? String((row as { msg: unknown }).msg)
          : ""
      )
      .filter(Boolean);
    return { message: parts.join("; ") || fallback };
  }
  if (detail && typeof detail === "object") {
    const row = detail as { message?: unknown; code?: unknown; detail?: unknown };
    const message =
      (typeof row.message === "string" && row.message) ||
      (typeof row.detail === "string" && row.detail) ||
      fallback;
    const code = typeof row.code === "string" ? row.code : undefined;
    return { message, code };
  }
  return { message: fallback };
}

async function readErrorDetail(response: Response, fallback: string): Promise<ParsedDetail> {
  const body = await response.json().catch(() => ({}));
  return parseDetail(body, fallback);
}

async function readError(response: Response, fallback: string): Promise<string> {
  return (await readErrorDetail(response, fallback)).message;
}

export function conflictMessage(err: unknown, stale = STALE_REVISION): string {
  if (!(err instanceof ApiRequestError)) {
    return err instanceof Error ? err.message : "Could not update notation.";
  }
  if (err.status !== 409) {
    return err.message;
  }
  if (err.code === "stale_revision") {
    return stale;
  }
  if (err.code === "missing_context") {
    return err.message || "This score is missing saved interpretation context.";
  }
  if (err.code === "edit_conflict" || err.code === "invalid_selection") {
    return err.message || "These changes could not be applied to the published score.";
  }
  return err.message || stale;
}

export async function getJob(id: string): Promise<Job> {
  const response = await apiFetch(`${API_URL}/jobs/${id}`);
  if (!response.ok) {
    throw new Error(await readError(response, "We couldn’t load this score."));
  }
  return (await response.json()) as Job;
}

export async function listScores(limit = 100): Promise<Job[]> {
  const response = await apiFetch(`${API_URL}/scores?limit=${limit}`);
  if (response.status === 401) {
    throw new Error("auth");
  }
  if (!response.ok) {
    throw new Error("Failed to list scores");
  }
  return (await response.json()) as Job[];
}

export async function renameScore(id: string, title: string): Promise<Job> {
  const response = await apiFetch(`${API_URL}/scores/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Could not rename this score"));
  }
  return (await response.json()) as Job;
}

export async function deleteScore(id: string): Promise<void> {
  const response = await apiFetch(`${API_URL}/scores/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(await readError(response, "Could not delete this score"));
  }
}

export async function claimScore(token: string): Promise<Job> {
  const response = await apiFetch(`${API_URL}/scores/claim`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Could not save this score"));
  }
  return (await response.json()) as Job;
}

export async function claimUnowned(jobIds: string[]): Promise<Job[]> {
  if (!jobIds.length) return [];
  const response = await apiFetch(`${API_URL}/scores/claim-unowned`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: jobIds.slice(0, 40) }),
  });
  if (!response.ok) {
    throw new Error(await readError(response, "Could not save scores"));
  }
  return (await response.json()) as Job[];
}

export async function retryJob(id: string): Promise<Job> {
  const response = await apiFetch(`${API_URL}/jobs/${id}/retry`, { method: "POST" });
  if (!response.ok) {
    throw new Error(await readError(response, "Could not try again"));
  }
  return (await response.json()) as Job;
}

export type ScoreEditsPayload = {
  score_id: string;
  revision: number;
  has_edits: boolean;
  tempo_bpm: number;
  time_signature: string;
  tempo_curve: { beat: number; bpm: number }[];
  printed_tempo_marks?: { beat: number; bpm: number | null; mark: string; reason: string }[];
  provenance?: string | null;
  notes: EditableNote[];
};

export async function getScoreEdits(id: string): Promise<ScoreEditsPayload> {
  const response = await apiFetch(`${API_URL}/scores/${id}/edits`);
  if (!response.ok) {
    throw new Error(await readError(response, "Could not load this score"));
  }
  return (await response.json()) as ScoreEditsPayload;
}

export async function saveScoreEdits(
  id: string,
  body: {
    revision: number;
    notes: EditableNote[];
    tempo_bpm: number;
    time_signature: string;
    tempo_curve?: { beat: number; bpm: number }[];
    printed_tempo_marks?: { beat: number; bpm: number | null; mark: string; reason: string }[];
    provenance?: string | null;
  }
): Promise<ScoreEditsPayload> {
  const response = await apiFetch(`${API_URL}/scores/${id}/edits`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const parsed = await readErrorDetail(response, "Changes couldn't be saved.");
    throw new ApiRequestError(parsed.message, response.status, parsed.code);
  }
  return (await response.json()) as ScoreEditsPayload;
}

export async function resetScoreEdits(
  id: string,
  body?: { revision?: number }
): Promise<ScoreEditsPayload> {
  const response = await apiFetch(`${API_URL}/scores/${id}/edits/reset`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const parsed = await readErrorDetail(response, "Could not reset changes");
    throw new ApiRequestError(parsed.message, response.status, parsed.code);
  }
  return (await response.json()) as ScoreEditsPayload;
}

export type NotationSettings = {
  display_grid: "auto" | "eighth" | "sixteenth" | "thirty-second";
  triplet_policy: "auto" | "enabled" | "disabled";
  interpretation: "literal" | "readable";
  syncopation: "preserve" | "show_meter";
  overlap_handling: "preserve" | "contextual";
  max_dots: number;
  algorithm_version: string;
  meter: string | null;
  pickup_beats: number | null;
  first_downbeat_beat: number | null;
  measure_overrides: Record<string, unknown>[];
};

export type PolicyException = {
  kind?: string;
  policy?: string;
  user_message?: string;
  reason?: string;
};

export type NotationSettingsPayload = {
  notation_settings: NotationSettings;
  algorithm_version: string;
  notation_cache_key: string;
  midi_sha256?: string | null;
  transcribed?: boolean;
  edit_revision?: number;
  has_edits?: boolean;
  fallback?: string | null;
  policy_exceptions?: PolicyException[];
};

export async function getNotationSettings(id: string): Promise<NotationSettingsPayload> {
  const response = await apiFetch(`${API_URL}/jobs/${id}/notation-settings`);
  if (!response.ok) {
    throw new Error(await readError(response, "Could not load notation settings"));
  }
  return (await response.json()) as NotationSettingsPayload;
}

export async function saveNotationSettings(
  id: string,
  body: Partial<NotationSettings> & { reset?: boolean; revision?: number }
): Promise<NotationSettingsPayload> {
  const response = await apiFetch(`${API_URL}/jobs/${id}/notation-settings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const parsed = await readErrorDetail(response, "Could not update notation");
    throw new ApiRequestError(parsed.message, response.status, parsed.code);
  }
  return (await response.json()) as NotationSettingsPayload;
}

export async function attachAccountScores(): Promise<void> {
  const pending = consumePendingClaim();
  if (pending?.token) {
    try {
      await claimScore(pending.token);
    } catch {
      /* claim is best-effort after OAuth */
    }
  }
  const ids = listStoredScores().map((row) => row.job_id);
  if (!ids.length) return;
  try {
    await claimUnowned(ids);
  } catch {
    /* local history may be empty or already owned */
  }
}
