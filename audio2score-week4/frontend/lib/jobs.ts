import { API_URL, type Job } from "./api";
import { apiFetch } from "./api-client";
import { consumePendingClaim } from "./pending-claim";
import { listStoredScores } from "./session-jobs";

async function readError(response: Response, fallback: string): Promise<string> {
  const data = await response.json().catch(() => ({}));
  return typeof data?.detail === "string" ? data.detail : fallback;
}

export async function getJob(id: string): Promise<Job> {
  const response = await apiFetch(`${API_URL}/jobs/${id}`);
  if (!response.ok) {
    throw new Error(await readError(response, "Failed to fetch job"));
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
