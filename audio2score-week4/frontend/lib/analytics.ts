export type AnalyticsEvent =
  | "landing_view"
  | "hero_create_clicked"
  | "demo_played"
  | "pricing_viewed"
  | "login_started"
  | "signup_started"
  | "signup_completed"
  | "create_score_clicked"
  | "create_page_viewed"
  | "upload_started"
  | "upload_completed"
  | "audio_preview_played"
  | "score_creation_started"
  | "auth_interruption"
  | "job_processing_started"
  | "job_completed"
  | "job_failed"
  | "score_opened"
  | "export_pdf"
  | "export_midi"
  | "export_musicxml"
  | "retry_started"
  | "score_library_viewed"
  | "score_renamed"
  | "score_deleted"
  | "score_downloaded"
  | "score_editor_opened"
  | "note_selected"
  | "note_pitch_changed"
  | "note_duration_changed"
  | "note_moved"
  | "note_added"
  | "note_deleted"
  | "edit_undone"
  | "edit_redone"
  | "edit_reset"
  | "edit_saved"
  | "edit_save_failed"
  | "edited_score_exported";

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
