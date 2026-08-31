const FALLBACK = "/create";

export function safeNextPath(value: string | null | undefined): string {
  if (!value) return FALLBACK;
  if (!value.startsWith("/")) return FALLBACK;
  if (value.startsWith("//")) return FALLBACK;
  if (value.startsWith("/login") || value.startsWith("/signup")) return FALLBACK;
  return value;
}

const STORAGE_KEY = "notascore-auth-next";

export function rememberNextPath(path: string) {
  try {
    sessionStorage.setItem(STORAGE_KEY, safeNextPath(path));
  } catch {
    /* ignore */
  }
}

export function consumeNextPath(): string {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    sessionStorage.removeItem(STORAGE_KEY);
    return safeNextPath(stored);
  } catch {
    return FALLBACK;
  }
}
