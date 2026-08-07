"use client";

import { supabase } from "../lib/supabase";

export default function AuthButton() {
  async function login() {
    await supabase.auth.signInWithOAuth({ provider: "google" });
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
