export type AnalyticsEvent =
  | "landing_view"
  | "hero_create_clicked"
  | "demo_played"
  | "pricing_viewed"
  | "login_started"
  | "signup_started"
  | "signup_completed"
  | "create_score_clicked";

/**
 * Lightweight, first-party events. No third-party pixels, no cookies,
 * no personal data. Listen via `window` `ns:analytics` if needed later.
 */
export function track(name: AnalyticsEvent, payload?: Record<string, string>) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent("ns:analytics", { detail: { name, payload, t: Date.now() } })
  );
}
