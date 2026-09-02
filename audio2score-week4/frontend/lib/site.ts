export const SITE_NAME = "NotaScore";
export const SITE_TAGLINE = "Turn your music into a score.";
export const SITE_DESCRIPTION =
  "From recordings to editable sheet music in minutes. Capture ideas. Transcribe performances. Keep your music.";

export function siteUrl(): string {
  return process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";
}

export const PUBLIC_NAV = [
  { href: "/how-it-works", label: "How it works" },
  { href: "/examples", label: "Examples" },
  { href: "/pricing", label: "Pricing" },
] as const;
