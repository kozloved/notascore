const CLAIM_KEY = "notascore-pending-claim";

export type PendingClaim = {
  job_id: string;
  token: string;
};

export function rememberPendingClaim(jobId: string, token: string) {
  try {
    sessionStorage.setItem(CLAIM_KEY, JSON.stringify({ job_id: jobId, token }));
  } catch {
    /* ignore */
  }
}

export function consumePendingClaim(): PendingClaim | null {
  try {
    const raw = sessionStorage.getItem(CLAIM_KEY);
    sessionStorage.removeItem(CLAIM_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.job_id || !parsed?.token) return null;
    return parsed as PendingClaim;
  } catch {
    return null;
  }
}

export function peekPendingClaim(): PendingClaim | null {
  try {
    const raw = sessionStorage.getItem(CLAIM_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed?.job_id || !parsed?.token) return null;
    return parsed as PendingClaim;
  } catch {
    return null;
  }
}
