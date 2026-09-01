export const SITE_NAME = "NotaScore";
export const SITE_TAGLINE = "Turn your recordings into editable sheet music.";
export const SITE_DESCRIPTION =
  "Give NotaScore a recording and get sheet music you can correct and export.";

export function siteUrl(): string {
  return process.env.NEXT_PUBLIC_SITE_URL || "https://notascore.com";
}

export const PUBLIC_NAV = [
  { href: "/how-it-works", label: "How it works" },
  { href: "/examples", label: "Examples" },
  { href: "/pricing", label: "Pricing" },
] as const;
