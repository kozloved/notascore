"use client";

import { isSupabaseConfigured, supabase } from "../lib/supabase";

export default function AuthButton() {
  async function login() {
    if (!isSupabaseConfigured) {
      window.alert(
        "Sign-in is not configured yet. Add NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY, then rebuild the frontend."
      );
      return;
    }

    const redirectTo = `${window.location.origin}/login`;
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo },
    });
    if (error) {
      window.alert(error.message);
    }
  }

  return (
    <button
      type="button"
      onClick={login}
      className="min-h-11 bg-ink px-6 text-sm font-medium text-mist transition hover:bg-score"
    >
      Continue with Google
    </button>
  );
}
