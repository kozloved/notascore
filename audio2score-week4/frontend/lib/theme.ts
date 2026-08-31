export const THEME_STORAGE_KEY = "notascore-theme";

export type ThemePreference = "system" | "light" | "dark";

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

export function readStoredTheme(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (isThemePreference(stored)) return stored;
  } catch {
    /* ignore */
  }
  return "system";
}

export function prefersDark(): boolean {
  try {
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  } catch {
    return false;
  }
}

export function resolvedIsDark(preference: ThemePreference): boolean {
  if (preference === "dark") return true;
  if (preference === "light") return false;
  return prefersDark();
}

export function applyTheme(preference: ThemePreference): void {
  const root = document.documentElement;
  root.setAttribute("data-theme", preference);
  const dark = resolvedIsDark(preference);
  root.style.colorScheme = dark ? "dark" : "light";
  root.style.backgroundColor = dark ? "#0B1018" : "#F6F3EC";
}
