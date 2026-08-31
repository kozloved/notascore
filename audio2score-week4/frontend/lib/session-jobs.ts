export type StoredScore = {
  job_id: string;
  filename: string;
  title?: string;
  status: string;
  created_at?: string;
  progress?: number;
  source_kind?: string;
  duration_seconds?: number | null;
};

const ACTIVE_KEY = "notascore-active-job";
const RECENT_KEY = "notascore-recent-jobs";

function readList(): StoredScore[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeList(items: StoredScore[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(items.slice(0, 40)));
  } catch {
    /* ignore quota */
  }
}

export function getActiveJobId(): string | null {
  try {
    return localStorage.getItem(ACTIVE_KEY);
  } catch {
    return null;
  }
}

export function setActiveJobId(id: string | null) {
  try {
    if (id) localStorage.setItem(ACTIVE_KEY, id);
    else localStorage.removeItem(ACTIVE_KEY);
  } catch {
    /* ignore */
  }
}

export function listStoredScores(): StoredScore[] {
  return readList();
}

export function upsertStoredScore(entry: StoredScore) {
  const next = readList().filter((item) => item.job_id !== entry.job_id);
  next.unshift(entry);
  writeList(next);
}

export function renameStoredScore(jobId: string, title: string) {
  writeList(
    readList().map((item) => (item.job_id === jobId ? { ...item, title } : item))
  );
}

export function removeStoredScore(jobId: string) {
  writeList(readList().filter((item) => item.job_id !== jobId));
  if (getActiveJobId() === jobId) setActiveJobId(null);
}

export function storedTitle(entry: StoredScore): string {
  return entry.title || entry.filename || "Untitled score";
}
