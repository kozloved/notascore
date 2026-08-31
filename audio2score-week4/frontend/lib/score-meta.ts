export function titleFromFilename(filename: string | null | undefined): string {
  const stem = (filename || "").replace(/\.[^/.]+$/, "");
  const cleaned = stem.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!cleaned) return "Untitled score";
  return cleaned.replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function formatScoreDate(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds < 0) return "";
  const total = Math.floor(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export type ScoreSort = "newest" | "oldest" | "name";

export function sortScores<T extends { title?: string; filename?: string; created_at?: string }>(
  items: T[],
  sort: ScoreSort
): T[] {
  const copy = [...items];
  copy.sort((a, b) => {
    if (sort === "name") {
      const left = (a.title || a.filename || "").toLowerCase();
      const right = (b.title || b.filename || "").toLowerCase();
      return left.localeCompare(right);
    }
    const left = Date.parse(a.created_at || "") || 0;
    const right = Date.parse(b.created_at || "") || 0;
    return sort === "oldest" ? left - right : right - left;
  });
  return copy;
}
