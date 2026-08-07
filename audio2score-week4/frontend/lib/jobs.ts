import { API_URL, type Job } from "./api";

export async function getJob(id: string): Promise<Job> {
  const response = await fetch(`${API_URL}/jobs/${id}`);
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const detail =
      typeof data?.detail === "string" ? data.detail : "Failed to fetch job";
    throw new Error(detail);
  }

  return data as Job;
}

export async function listJobs(limit = 50): Promise<Job[]> {
  const response = await fetch(`${API_URL}/jobs?limit=${limit}`);
  const data = await response.json().catch(() => []);

  if (!response.ok) {
    throw new Error("Failed to list jobs");
  }

  return data as Job[];
}
